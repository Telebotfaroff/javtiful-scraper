import logging
import mimetypes
import time
from pathlib import Path

import requests

from .base import BaseUploader

logger = logging.getLogger(__name__)


class GoFileUploader(BaseUploader):
    name = "gofile"

    def __init__(self, timeout=120, retries=3):
        self.timeout = timeout
        self.retries = max(1, int(retries))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "JAVDL/1.0"})

    def upload(self, file_path, **kwargs):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(path)

        endpoint = "https://upload.gofile.io/uploadfile"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        last_error = None

        for attempt in range(1, self.retries + 1):
            try:
                logger.info(
                    "GOFILE UPLOAD: attempt %d/%d file=%s size=%d",
                    attempt,
                    self.retries,
                    path.name,
                    path.stat().st_size,
                )

                # Re-open the file for every attempt. A failed HTTP transfer
                # may leave the previous stream partially consumed.
                with path.open("rb") as fh:
                    response = self.session.post(
                        endpoint,
                        files={"file": (path.name, fh, content_type)},
                        timeout=self.timeout,
                    )

                response.raise_for_status()
                break

            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as exc:
                last_error = exc
                logger.warning(
                    "GOFILE UPLOAD: transient connection failure on attempt %d/%d: %s",
                    attempt,
                    self.retries,
                    exc,
                )

                if attempt >= self.retries:
                    raise RuntimeError(
                        f"GoFile upload failed after {self.retries} attempts: {exc}"
                    ) from exc

                # Throw away the connection pool so a broken keep-alive
                # connection is not reused for the retry.
                self.session.close()
                self.session = requests.Session()
                self.session.headers.update({"User-Agent": "JAVDL/1.0"})
                time.sleep(min(2 ** (attempt - 1), 5))

        else:
            raise RuntimeError(f"GoFile upload failed: {last_error}")

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
