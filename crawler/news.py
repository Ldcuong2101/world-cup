import logging
from datetime import datetime
from bs4 import BeautifulSoup
from .base import get_client, _NEWS_URL, _BASE_URL

logger = logging.getLogger(__name__)

# Date format from the site: "16:34 - 09/06"  (no year — assume current year)
def _parse_date(text: str) -> datetime:
    text = text.strip()
    try:
        # "HH:MM - DD/MM"
        time_part, date_part = text.split(" - ")
        hh, mm = time_part.split(":")
        dd, mo = date_part.split("/")
        year = datetime.utcnow().year
        return datetime(year, int(mo), int(dd), int(hh), int(mm))
    except Exception:
        return None


async def crawl_news_list():
    try:
        async with get_client() as client:
            resp = await client.get(_NEWS_URL)
            resp.raise_for_status()
    except Exception as e:
        logger.error("crawl_news_list failed: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Both compact and featured cards are <li><article class="d-flex ...">
    cards = soup.select("li article.d-flex")
    logger.info("Found %d article cards", len(cards))

    items = []
    seen_urls = set()

    for card in cards:
        try:
            # Title + URL: from h2/h3 anchor, or fallback to thumbblock anchor
            title_el = card.select_one("h2 a, h3 a")
            thumb_link = card.select_one("a.thumbblock")

            if not title_el and not thumb_link:
                continue

            title = (title_el or thumb_link).get("title") or (title_el or thumb_link).get_text(strip=True)
            if not title:
                continue

            href = (title_el or thumb_link).get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = _BASE_URL + href
            elif not href.startswith("http"):
                href = _BASE_URL + "/" + href

            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Thumbnail — src is already the real URL (not lazy-loaded via data-src)
            thumb = None
            img = card.select_one("a.thumbblock img")
            if img:
                thumb = img.get("src") or img.get("data-src") or img.get("data-original")
                if thumb and ("placeholder" in thumb or "blank" in thumb or len(thumb) < 15):
                    thumb = None

            # Excerpt — only present on featured (larger) cards
            excerpt_el = card.select_one(".sapo_thumb_news")
            excerpt = excerpt_el.get_text(strip=True)[:300] if excerpt_el else ""

            # Published date — format: "16:34 - 09/06"
            time_el = card.select_one(".time_post")
            published_at = _parse_date(time_el.get_text()) if time_el else None

            items.append({
                "title": title,
                "source_url": href,
                "thumbnail_url": thumb,
                "excerpt": excerpt,
                "published_at": published_at,
                "crawled_at": datetime.utcnow(),
            })
        except Exception as e:
            logger.warning("Error parsing article card: %s", e)
            continue

    logger.info("Parsed %d articles", len(items))
    return items
