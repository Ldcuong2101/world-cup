import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EMAIL_MODE = os.environ.get("EMAIL_MODE", "smtp")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "") or SMTP_USER or "noreply@wcpredict.app"


def _render_otp_email(otp: str, username: str) -> str:
    return f"""<div style="background:#0f172a;padding:40px;font-family:sans-serif;max-width:480px;margin:auto;border-radius:12px;">
  <h1 style="color:#f59e0b;font-size:24px;margin-bottom:4px;">&#127942; WC Predict</h1>
  <p style="color:#94a3b8;font-size:14px;">World Cup 2026 Prediction Game</p>
  <hr style="border-color:#1e293b;margin:24px 0;">
  <p style="color:#e2e8f0;font-size:16px;">Hi <strong>{username}</strong>,</p>
  <p style="color:#94a3b8;font-size:14px;">Your verification code is:</p>
  <div style="background:#1e293b;border:2px solid #f59e0b;border-radius:12px;padding:24px;text-align:center;margin:24px 0;letter-spacing:12px;">
    <span style="color:#f59e0b;font-size:40px;font-weight:900;">{otp}</span>
  </div>
  <p style="color:#64748b;font-size:13px;">
    This code expires in <strong style="color:#e2e8f0;">10 minutes</strong>.<br>
    If you didn&rsquo;t request this, ignore this email.
  </p>
  <hr style="border-color:#1e293b;margin:24px 0;">
  <p style="color:#475569;font-size:12px;">WC Predict 2026 &middot; Private group &middot; Not affiliated with FIFA</p>
</div>"""


def _render_reset_email(otp: str, username: str) -> str:
    return f"""<div style="background:#0f172a;padding:40px;font-family:sans-serif;max-width:480px;margin:auto;border-radius:12px;">
  <h1 style="color:#f59e0b;font-size:24px;margin-bottom:4px;">&#127942; WC Predict</h1>
  <p style="color:#94a3b8;font-size:14px;">World Cup 2026 Prediction Game</p>
  <hr style="border-color:#1e293b;margin:24px 0;">
  <p style="color:#e2e8f0;font-size:16px;">Hi <strong>{username}</strong>,</p>
  <p style="color:#94a3b8;font-size:14px;">Use this code to reset your password:</p>
  <div style="background:#1e293b;border:2px solid #f59e0b;border-radius:12px;padding:24px;text-align:center;margin:24px 0;letter-spacing:12px;">
    <span style="color:#f59e0b;font-size:40px;font-weight:900;">{otp}</span>
  </div>
  <p style="color:#64748b;font-size:13px;">
    This code expires in <strong style="color:#e2e8f0;">10 minutes</strong>.<br>
    If you didn&rsquo;t request a password reset, ignore this email.
  </p>
  <hr style="border-color:#1e293b;margin:24px 0;">
  <p style="color:#475569;font-size:12px;">WC Predict 2026 &middot; Private group &middot; Not affiliated with FIFA</p>
</div>"""


def send_reset_email(to_email: str, otp: str, username: str) -> None:
    if EMAIL_MODE == "sendgrid":
        _send_reset_via_sendgrid(to_email, otp, username)
    else:
        _send_reset_via_smtp(to_email, otp, username)


def _send_reset_via_smtp(to_email: str, otp: str, username: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"WC Predict password reset code: {otp}"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(_render_reset_email(otp, username), "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())


def _send_reset_via_sendgrid(to_email: str, otp: str, username: str) -> None:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=f"WC Predict password reset code: {otp}",
        html_content=_render_reset_email(otp, username),
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)


def send_otp_email(to_email: str, otp: str, username: str) -> None:
    if EMAIL_MODE == "sendgrid":
        _send_via_sendgrid(to_email, otp, username)
    else:
        _send_via_smtp(to_email, otp, username)


def _send_via_smtp(to_email: str, otp: str, username: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your WC Predict verification code: {otp}"
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg.attach(MIMEText(_render_otp_email(otp, username), "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())


def _send_via_sendgrid(to_email: str, otp: str, username: str) -> None:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=f"Your WC Predict code: {otp}",
        html_content=_render_otp_email(otp, username),
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    sg.send(message)
