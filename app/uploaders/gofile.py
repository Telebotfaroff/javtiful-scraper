import mimetypes
from pathlib import Path

import requests

from .base import BaseUploader


class GoFileUploader(BaseUploader):
    name = "gofile"

    def __init__(self, timeout=120):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "JAVDL/1.0"})

    def upload(self, file_path, **kwargs):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        # GoFile's current guest-upload API uses the global upload endpoint.
        # No API token is required; omitting folderId creates a guest folder.
        endpoint = "https://upload.gofile.io/uploadfile"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        with path.open("rb") as fh:
            response = self.session.post(
                endpoint,
                files={"file": (path.name, fh, content_type)},
                timeout=self.timeout,
            )

        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"GoFile returned non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:500]}"
            ) from exc

        if data.get("status") != "ok":
            raise RuntimeError(f"GoFile upload failed: {data}")

        result = data.get("data", {})
        return {
            "provider": self.name,
            "file_id": result.get("id") or result.get("fileId"),
            "parent_folder": result.get("parentFolder"),
            "guest_token": result.get("guestToken"),
            "download_url": (
                result.get("downloadPage")
                or result.get("downloadUrl")
                or result.get("directLink")
            ),
            "raw": result,
        }

    def verify(self, result):
        return bool(result and result.get("download_url"))
