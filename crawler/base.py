import httpx

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi,en;q=0.9",
}
_TIMEOUT = 15.0
_NEWS_URL = "https://thethao247.vn/world-cup"
_BASE_URL = "https://thethao247.vn"


def get_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
