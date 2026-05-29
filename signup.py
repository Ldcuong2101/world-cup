import random
import re
import string
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import SESSION_COOKIE, create_session_token, hash_password
from database import get_db
from email_sender import send_otp_email
from models import PendingRegistration, User

router = APIRouter()
templates = Jinja2Templates(directory="templates")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")

_OTP_TTL = timedelta(minutes=10)
_RESEND_COOLDOWN = timedelta(seconds=60)
_MAX_ATTEMPTS = 5


def _gen_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _cleanup_expired(db: Session) -> None:
    db.query(PendingRegistration).filter(
        PendingRegistration.otp_expires_at < datetime.utcnow()
    ).delete()
    db.commit()


# ─── GET /signup ─────────────────────────────────────────────────────────────

@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    expired = request.query_params.get("expired")
    locked = request.query_params.get("locked")
    notice = None
    if expired:
        notice = ("Your verification code has expired. Please sign up again.", "error")
    elif locked:
        notice = ("Too many incorrect attempts. Please sign up again.", "error")
    return templates.TemplateResponse(
        "signup.html",
        {"request": request, "errors": {}, "values": {}, "notice": notice},
    )


# ─── POST /signup ─────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    _cleanup_expired(db)

    username = username.strip()
    email = email.strip().lower()
    errors: dict[str, str] = {}

    if not _USERNAME_RE.match(username):
        errors["username"] = "3–20 characters, letters, numbers, and underscore only"
    if not _EMAIL_RE.match(email):
        errors["email"] = "Enter a valid email address"
    if len(password) < 8:
        errors["password"] = "Password must be at least 8 characters"
    if password != confirm_password:
        errors["confirm_password"] = "Passwords do not match"

    if not errors:
        if db.query(User).filter(User.username == username).first():
            errors["username"] = "Username is already taken"
        if db.query(User).filter(User.email == email).first():
            errors["email"] = "An account with this email already exists"

    if errors:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "errors": errors, "values": {"username": username, "email": email}, "notice": None},
            status_code=422,
        )

    otp = _gen_otp()
    now = datetime.utcnow()
    pw_hash = hash_password(password)

    existing = db.query(PendingRegistration).filter(PendingRegistration.email == email).first()
    if existing:
        existing.username = username
        existing.password_hash = pw_hash
        existing.otp_code = otp
        existing.otp_expires_at = now + _OTP_TTL
        existing.attempts = 0
        existing.last_sent_at = now
    else:
        db.add(PendingRegistration(
            email=email,
            username=username,
            password_hash=pw_hash,
            otp_code=otp,
            otp_expires_at=now + _OTP_TTL,
            attempts=0,
            last_sent_at=now,
            created_at=now,
        ))
    db.commit()

    try:
        send_otp_email(email, otp, username)
    except Exception as exc:
        print(f"[email] Failed to send OTP to {email}: {exc}")

    request.session["pending_email"] = email
    return RedirectResponse("/verify", status_code=302)


# ─── GET /verify ──────────────────────────────────────────────────────────────

@router.get("/verify", response_class=HTMLResponse)
async def verify_page(request: Request):
    email = request.session.get("pending_email")
    if not email:
        return RedirectResponse("/signup", status_code=302)
    return templates.TemplateResponse(
        "verify.html",
        {"request": request, "email": _mask_email(email), "error": None},
    )


# ─── POST /verify ─────────────────────────────────────────────────────────────

@router.post("/verify")
async def verify_submit(
    request: Request,
    otp: str = Form(...),
    db: Session = Depends(get_db),
):
    email = request.session.get("pending_email")
    if not email:
        return RedirectResponse("/signup", status_code=302)

    pending = db.query(PendingRegistration).filter(PendingRegistration.email == email).first()
    now = datetime.utcnow()

    def _render_error(msg: str):
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "email": _mask_email(email), "error": msg},
            status_code=422,
        )

    if not pending:
        request.session.pop("pending_email", None)
        return RedirectResponse("/signup?expired=1", status_code=302)

    if pending.otp_expires_at < now:
        db.delete(pending)
        db.commit()
        request.session.pop("pending_email", None)
        return RedirectResponse("/signup?expired=1", status_code=302)

    if pending.attempts >= _MAX_ATTEMPTS:
        db.delete(pending)
        db.commit()
        request.session.pop("pending_email", None)
        return RedirectResponse("/signup?locked=1", status_code=302)

    if otp.strip() != pending.otp_code:
        pending.attempts += 1
        db.commit()
        remaining = _MAX_ATTEMPTS - pending.attempts
        if remaining <= 0:
            db.delete(pending)
            db.commit()
            request.session.pop("pending_email", None)
            return RedirectResponse("/signup?locked=1", status_code=302)
        label = "attempt" if remaining == 1 else "attempts"
        return _render_error(f"Invalid code. {remaining} {label} remaining.")

    # OTP correct — promote to real user
    user = User(
        username=pending.username,
        email=pending.email,
        password_hash=pending.password_hash,
        is_admin=False,
        total_score=0,
    )
    db.add(user)
    db.delete(pending)
    db.flush()
    db.commit()
    db.refresh(user)

    request.session.pop("pending_email", None)

    token = create_session_token(user.id)
    r = RedirectResponse("/matches", status_code=302)
    r.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=86400 * 7)
    r.set_cookie("flash_msg", f"Welcome, {user.username}!", max_age=5)
    r.set_cookie("flash_cat", "success", max_age=5)
    return r


# ─── POST /resend-otp ─────────────────────────────────────────────────────────

@router.post("/resend-otp")
async def resend_otp(request: Request, db: Session = Depends(get_db)):
    email = request.session.get("pending_email")
    if not email:
        return JSONResponse({"success": False, "error": "Session expired"}, status_code=400)

    pending = db.query(PendingRegistration).filter(PendingRegistration.email == email).first()
    if not pending:
        return JSONResponse({"success": False, "error": "Registration not found"}, status_code=404)

    now = datetime.utcnow()
    if pending.last_sent_at:
        elapsed = now - pending.last_sent_at
        if elapsed < _RESEND_COOLDOWN:
            wait = int((_RESEND_COOLDOWN - elapsed).total_seconds())
            return JSONResponse({"success": False, "error": f"Wait {wait}s before resending"}, status_code=429)

    otp = _gen_otp()
    pending.otp_code = otp
    pending.otp_expires_at = now + _OTP_TTL
    pending.attempts = 0
    pending.last_sent_at = now
    db.commit()

    try:
        send_otp_email(email, otp, pending.username)
    except Exception as exc:
        print(f"[email] Failed to resend OTP to {email}: {exc}")
        return JSONResponse({"success": False, "error": "Failed to send email"}, status_code=500)

    return JSONResponse({"success": True})
