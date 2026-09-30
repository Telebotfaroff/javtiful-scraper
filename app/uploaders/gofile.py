import requests
from pathlib import Path
from .base import BaseUploader

class GoFileUploader(BaseUploader):
    name = "gofile"

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "JAVDL/1.0"})

    def _server(self):
        r = self.session.get("https://api.gofile.io/servers", timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"GoFile server lookup failed: {data}")
        servers = data.get("data", {}).get("servers", [])
        if not servers:
            raise RuntimeError("GoFile returned no upload servers")
        return servers[0].get("name") or servers[0].get("server")

    def upload(self, file_path, **kwargs):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        server = self._server()
        endpoint = f"https://{server}.gofile.io/contents/upload"
        with path.open("rb") as fh:
            response = self.session.post(endpoint, files={"file": (path.name, fh, "video/mp4")}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            raise RuntimeError(f"GoFile upload failed: {data}")
        result = data.get("data", {})
        return {
            "provider": self.name,
            "file_id": result.get("fileId"),
            "parent_folder": result.get("parentFolder"),
            "download_url": result.get("downloadPage") or result.get("directLink") or result.get("downloadUrl"),
            "raw": result,
        }

    def verify(self, result):
        return bool(result and result.get("download_url"))
