"""Read the public studio index maintained in the repository's main branch."""
from __future__ import annotations

import requests

STUDIO_INDEX_URL = (
    "https://raw.githubusercontent.com/Telebotfaroff/javtiful-scraper/"
    "main/database/index/indexstudio.json"
)
REQUEST_TIMEOUT = 20
PAGE_SIZE = 10


def fetch_studios(timeout: int = REQUEST_TIMEOUT) -> list[dict[str, str]]:
    """Fetch and validate studio name/URL pairs from the GitHub JSON index."""
    response = requests.get(STUDIO_INDEX_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    studios = payload.get("studios") if isinstance(payload, dict) else None
    if not isinstance(studios, dict):
        raise ValueError("Studio index has no valid 'studios' object.")

    result = []
    for key, value in studios.items():
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or key).strip()
        url = str(value.get("url") or "").strip()
        if not name or not url:
            continue
        result.append({"name": name, "url": url})
    if not result:
        raise ValueError("Studio index contains no usable entries.")
    return result


def page_studios(studios: list[dict[str, str]], page: int, page_size: int = PAGE_SIZE):
    """Return a one-based page slice and total page count."""
    if page_size < 1:
        raise ValueError("page_size must be at least 1")
    total_pages = max(1, (len(studios) + page_size - 1) // page_size)
    page = max(1, min(int(page), total_pages))
    start = (page - 1) * page_size
    return studios[start:start + page_size], page, total_pages
