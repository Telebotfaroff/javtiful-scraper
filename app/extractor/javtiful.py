import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.models.video import Video
from .base import BaseExtractor


class JavtifulExtractor(BaseExtractor):
    name = "javtiful"

    _QUALITY_RE = re.compile(r"(?<!\d)(2160|1440|1080|720|480|360)p", re.I)
    _MEDIA_RE = re.compile(
        r"https?://[^\s"'<>\\]+(?:\.m3u8(?:\?[^\s"'<>\\]*)?|\.mp4(?:\?[^\s"'<>\\]*)?|\.webm(?:\?[^\s"'<>\\]*)?|/p/[A-Za-z0-9._~:/?#[\]@!$&()*+,;=%-]+)",
        re.I,
    )

    def extract(self, url: str) -> Video:
        response = requests.get(
            url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        title = self._title(soup)
        thumbnail = self._thumbnail(soup)
        duration = self._find_duration(soup)
        qualities = self._static_sources(soup, url)

        # Some Javtiful pages expose a placeholder/source element while the
        # real signed media URL is created by JavaScript. Search the raw HTML
        # for URLs before falling back to a browser/network probe.
        self._add_raw_media_urls(response.text, qualities)

        if not self._has_real_media_url(qualities):
            self._add_runtime_media_urls(url, qualities)

        if not duration:
            duration = self._runtime_duration(url)

        return Video(
            source_url=url,
            title=title,
            thumbnail=thumbnail,
            duration=duration,
            qualities=qualities,
        )

    @staticmethod
    def _title(soup):
        node = soup.find("h1")
        if node:
            return node.get_text(" ", strip=True)

        node = soup.find("meta", property="og:title")
        return node.get("content", "").strip() if node else ""

    @staticmethod
    def _thumbnail(soup):
        node = soup.find("meta", property="og:image")
        return node.get("content") if node else None

    def _find_duration(self, soup):
        # Prefer actual video metadata when present.
        for tag in soup.find_all(["video", "source"]):
            value = tag.get("duration") or tag.get("data-duration")
            if value:
                parsed = self._duration(str(value))
                if parsed is not None:
                    return parsed

        for tag in soup.find_all(attrs={"class": re.compile("duration|time", re.I)}):
            parsed = self._duration(tag.get_text(" ", strip=True))
            if parsed is not None:
                return parsed

        for tag in soup.find_all(attrs={"data-duration": True}):
            parsed = self._duration(str(tag.get("data-duration")))
            if parsed is not None:
                return parsed

        return None

    def _static_sources(self, soup, page_url):
        qualities = {}

        for tag in soup.find_all(["video", "source"]):
            src = (
                tag.get("src")
                or tag.get("data-src")
                or tag.get("data-url")
                or tag.get("data-video")
            )
            if not src:
                continue

            absolute = urljoin(page_url, src)
            q = (
                tag.get("label")
                or tag.get("res")
                or tag.get("data-quality")
                or self._quality_from_url(absolute)
                or "source"
            )
            qualities[str(q)] = absolute

        for tag in soup.find_all("a", href=True):
            text = tag.get_text(" ", strip=True)
            match = self._QUALITY_RE.search(text)
            if match:
                qualities[match.group(1) + "p"] = urljoin(page_url, tag["href"])

        return qualities

    def _add_raw_media_urls(self, html, qualities):
        # HTML/inline JS may contain escaped URLs generated before the player
        # starts. Decode common JSON/HTML escaping first.
        raw = (
            html.replace("\\/", "/")
            .replace("&amp;", "&")
            .replace("\\u002F", "/")
            .replace("\\u003A", ":")
        )

        for match in self._MEDIA_RE.finditer(raw):
            candidate = match.group(0).rstrip("\\.,);]}"'")
            if self._looks_like_media(candidate):
                qualities.setdefault(
                    self._quality_from_url(candidate) or "source",
                    candidate,
                )

    def _add_runtime_media_urls(self, page_url, qualities):
        # Runtime-generated/signed URLs are not visible to requests/BeautifulSoup.
        # Playwright observes the same network responses a normal browser uses.
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return

        media_urls = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0 Safari/537.36"
                    )
                )

                def on_response(response):
                    candidate = response.url
                    if self._looks_like_media(candidate):
                        media_urls.append(candidate)

                page.on("response", on_response)
                page.goto(url=page_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(6_000)

                # Read already-created media resources too.
                resources = page.evaluate(
                    """() => performance.getEntriesByType('resource')
                    .map(x => x.name)
                    .filter(x => /\\.(m3u8|mp4|webm)(\\?|$)|\\/p\\//i.test(x))"""
                )
                media_urls.extend(resources)

                browser.close()
        except Exception:
            return

        for candidate in media_urls:
            candidate = str(candidate).strip()
            if self._looks_like_media(candidate):
                qualities.setdefault(
                    self._quality_from_url(candidate) or "source",
                    candidate,
                )

    def _runtime_duration(self, page_url):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page()
                page.goto(url=page_url, wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(3_000)
                value = page.evaluate(
                    """() => {
                        const v = document.querySelector('video');
                        return v && Number.isFinite(v.duration) ? v.duration : null;
                    }"""
                )
                browser.close()
                return int(float(value)) if value else None
        except Exception:
            return None

    @staticmethod
    def _quality_from_url(url):
        match = re.search(r"(?<!\d)(2160|1440|1080|720|480|360)p", url, re.I)
        return match.group(1) + "p" if match else None

    @classmethod
    def _looks_like_media(cls, url):
        lowered = url.lower()
        return (
            ".m3u8" in lowered
            or ".mp4" in lowered
            or ".webm" in lowered
            or "/p/" in lowered
        )

    @classmethod
    def _has_real_media_url(cls, qualities):
        return any(cls._looks_like_media(value) for value in qualities.values())

    @staticmethod
    def _duration(value):
        value = str(value).strip()

        # Plain seconds.
        if re.fullmatch(r"\d+(?:\.\d+)?", value):
            return int(float(value))

        match = re.fullmatch(
            r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?",
            value,
            re.I,
        )
        if match and any(match.groups()):
            return (
                int(match.group(1) or 0) * 3600
                + int(match.group(2) or 0) * 60
                + int(match.group(3) or 0)
            )

        match = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", value)
        if match:
            if match.group(3) is None:
                return int(match.group(1)) * 60 + int(match.group(2))
            return (
                int(match.group(1)) * 3600
                + int(match.group(2)) * 60
                + int(match.group(3))
            )

        return None
