import re, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from app.models.video import Video
from .base import BaseExtractor

class JavtifulExtractor(BaseExtractor):
    name = "javtiful"
    def extract(self, url: str) -> Video:
        r = requests.get(url, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        title = (soup.find("h1") or soup.find("meta", property="og:title"))
        title = title.get("content", "") if getattr(title, "name", None) == "meta" else title.get_text(" ", strip=True) if title else ""
        thumb = soup.find("meta", property="og:image")
        duration = None
        m = soup.find(attrs={"class": re.compile("duration|time", re.I)})
        if m:
            duration = self._duration(m.get_text(" ", strip=True))
        qualities = {}
        for tag in soup.find_all("source"):
            src = tag.get("src") or tag.get("data-src")
            if src:
                q = tag.get("label") or tag.get("res") or tag.get("data-quality") or "source"
                qualities[str(q)] = urljoin(url, src)
        # Also recognize explicit quality links exposed by the page.
        for tag in soup.find_all("a", href=True):
            text = tag.get_text(" ", strip=True)
            q = re.search(r"(?<!\\d)(2160|1440|1080|720|480|360)p", text, re.I)
            if q:
                qualities[q.group(1)+"p"] = urljoin(url, tag["href"])
        return Video(source_url=url, title=title, thumbnail=thumb.get("content") if thumb else None, duration=duration, qualities=qualities)
    @staticmethod
    def _duration(value):
        m=re.search(r"(?:(\\d+)\\s*h)?\\s*(?:(\\d+)\\s*m)?\\s*(?:(\\d+)\\s*s)?$", value, re.I)
        if m and any(m.groups()): return int(m.group(1) or 0)*3600+int(m.group(2) or 0)*60+int(m.group(3) or 0)
        return None
