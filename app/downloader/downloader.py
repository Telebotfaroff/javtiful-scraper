from pathlib import Path
import requests
from .quality import choose_quality

class Downloader:
    def __init__(self, workdir="downloads", chunk_size=1024*1024): self.workdir=Path(workdir); self.workdir.mkdir(parents=True,exist_ok=True); self.chunk_size=chunk_size
    def download(self, video, quality="best", progress=None):
        selected,url=choose_quality(video.qualities, quality); video.selected_quality=selected
        path=self.workdir / (self._filename(video.title, selected)+".mp4")
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent":"Mozilla/5.0"}) as r:
            r.raise_for_status(); total=int(r.headers.get("content-length",0)); done=0
            with path.open("wb") as f:
                for chunk in r.iter_content(self.chunk_size):
                    if chunk: f.write(chunk); done+=len(chunk); progress and progress(done,total,"download")
        video.local_path=str(path); return path
    @staticmethod
    def _filename(title, quality):
        import re
        return re.sub(r"[^A-Za-z0-9._ -]+","_",f"{title or 'video'} [{quality}]").strip()[:180]
