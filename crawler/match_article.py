import logging
from datetime import datetime
from bs4 import BeautifulSoup, Tag
from .base import get_client

logger = logging.getLogger(__name__)

_REMOVE_TAGS = {"script", "style", "nav", "header", "footer", "aside", "iframe", "form", "button", "input", "select", "textarea", "noscript"}
_REMOVE_CLASS_KW = ["ads", "advert", "related", "social", "share", "comment", "banner", "popup", "cookie", "widget", "sidebar", "recommend", "promotion", "newsletter"]

_BODY_SELECTORS = [
    # thethao247.vn
    ".txt_content",
    "#content_detail",
    # generic patterns
    ".article-body",
    ".article-content",
    ".detail-content",
    ".post-content",
    ".content-detail",
    ".entry-content",
    "#article-body",
    "#article-content",
    "article",
    "[class*='article-body']",
    "[class*='article-content']",
]


def _clean_body(tag: Tag) -> str:
    for el in tag.find_all(_REMOVE_TAGS):
        el.decompose()

    for el in list(tag.find_all(True)):
        if el.parent is None or el.attrs is None:
            continue
        classes = " ".join(el.get("class", []))
        if any(kw in classes.lower() for kw in _REMOVE_CLASS_KW):
            el.decompose()

    for el in list(tag.find_all(True)):
        if el.parent is None or el.attrs is None:
            continue
        allowed = {}
        if el.name == "img":
            src = (
                el.get("data-src") or
                el.get("data-lazy-src") or
                el.get("data-original") or
                el.get("src", "")
            )
            if src and "placeholder" not in src and "blank" not in src and len(src) > 15:
                allowed["src"] = src
            alt = el.get("alt", "")
            if alt:
                allowed["alt"] = alt
            allowed["loading"] = "lazy"
        elif el.name == "a":
            href = el.get("href", "")
            if href and href.startswith("http"):
                allowed["href"] = href
                allowed["target"] = "_blank"
                allowed["rel"] = "noopener noreferrer"
        el.attrs = allowed

    return str(tag)


async def crawl_match_article(url: str) -> dict:
    try:
        async with get_client() as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as e:
        logger.error("crawl_match_article(%s) failed: %s", url, e)
        return {"error": f"Không thể tải bài viết: {e}"}

    soup = BeautifulSoup(resp.text, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    body = None
    for sel in _BODY_SELECTORS:
        body = soup.select_one(sel)
        if body:
            break

    if not body:
        return {"error": "Không tìm thấy nội dung bài viết"}

    content_html = _clean_body(body)

    return {
        "title": title,
        "content_html": content_html,
        "source_url": url,
        "crawled_at": datetime.utcnow(),
    }
