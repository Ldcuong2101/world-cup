import logging
from datetime import datetime
from bs4 import BeautifulSoup
from .base import get_client, _NEWS_URL, _BASE_URL

logger = logging.getLogger(__name__)


async def crawl_news_list():
    try:
        async with get_client() as client:
            resp = await client.get(_NEWS_URL)
            resp.raise_for_status()
    except Exception as e:
        logger.error("crawl_news_list failed: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try multiple selector patterns — finalize against live HTML
    cards = (
        soup.select("article.item-news") or
        soup.select("article") or
        soup.select("div.item-news") or
        soup.select("div.item") or
        []
    )

    items = []
    for card in cards:
        try:
            link = card.find("a", href=True)
            title_el = card.find(["h2", "h3", "h4"])
            if not link and not title_el:
                continue

            title = (title_el or link).get_text(strip=True)
            if not title:
                continue

            href = (link or card.find("a", href=True) or {}).get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = _BASE_URL + href
            elif not href.startswith("http"):
                href = _BASE_URL + "/" + href

            # Thumbnail — check lazy-load attributes first
            thumb = None
            img = card.find("img")
            if img:
                thumb = (
                    img.get("data-src") or
                    img.get("data-lazy-src") or
                    img.get("data-original") or
                    img.get("src")
                )
                if thumb and ("placeholder" in thumb or "blank" in thumb or len(thumb) < 15):
                    thumb = None

            # Excerpt
            desc_el = card.find(
                ["p", "div"],
                class_=lambda c: c and any(
                    x in " ".join(c) for x in ["desc", "summary", "sapo", "lead", "excerpt", "intro"]
                )
            )
            excerpt = desc_el.get_text(strip=True)[:280] if desc_el else ""

            # Published date
            published_at = None
            time_el = card.find("time")
            if time_el and time_el.get("datetime"):
                try:
                    parsed = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                    published_at = parsed.replace(tzinfo=None)
                except (ValueError, AttributeError):
                    pass

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

    return items
