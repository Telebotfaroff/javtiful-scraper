import math
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from pyrogram import Client
from app.storage.cleanup import cleanup

TELEGRAM_LIMIT = 2_000_000_000


class TelegramUploader:
    name = "telegram"

    def __init__(self, api_id=None, api_hash=None, session="javdl", bot_token=None):
        self.app = Client(
            session,
            api_id=int(api_id or os.environ["TELEGRAM_API_ID"]),
            api_hash=api_hash or os.environ["TELEGRAM_API_HASH"],
            bot_token=bot_token or os.getenv("TELEGRAM_BOT_TOKEN"),
        )

    @staticmethod
    def _duration(path: Path) -> float:
        value = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
        ).strip()
        return float(value)

    @classmethod
    def split_if_needed(cls, file_path, limit=TELEGRAM_LIMIT):
        path = Path(file_path)
        if path.stat().st_size <= limit:
            return [str(path)]
        duration = cls._duration(path)
        part_count = math.ceil(path.stat().st_size / limit)
        segment = (duration / part_count) * 0.96
        parts = []
        for index in range(part_count):
            start = index * segment
            length = max(0.1, duration - start) if index == part_count - 1 else segment
            target = path.with_name(f"{path.stem}.part{index + 1}{path.suffix}")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(start), "-i", str(path),
                    "-t", str(length), "-c", "copy", str(target),
                ],
                check=True,
            )
            parts.append(str(target))
        return parts

    @staticmethod
    def _prepare_thumbnail(thumbnail):
        """Download a remote poster and normalize it to a Telegram-friendly JPEG."""
        if not thumbnail:
            return None

        value = str(thumbnail).strip()
        if not value:
            return None

        if not value.startswith(("http://", "https://")):
            return value if Path(value).exists() else None

        raw_path = None
        jpg_path = None
        try:
            response = requests.get(
                value,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()

            raw = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
            raw.write(response.content)
            raw.close()
            raw_path = raw.name

            jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            jpg.close()
            jpg_path = jpg.name

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", raw_path,
                    "-vf",
                    "scale=if(gt(iw,ih),320,-2):if(gt(iw,ih),-2,320)",
                    "-frames:v", "1",
                    "-q:v", "10",
                    jpg_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return jpg_path
        except Exception:
            if jpg_path:
                Path(jpg_path).unlink(missing_ok=True)
            return None
        finally:
            if raw_path:
                Path(raw_path).unlink(missing_ok=True)

    def upload(self, file_path, chat_id, caption="", thumbnail=None, duration=None, progress=None):
        paths = self.split_if_needed(file_path)
        results = []
        prepared_thumbnail = self._prepare_thumbnail(thumbnail)

        try:
            with self.app:
                for index, path in enumerate(paths, 1):
                    part_caption = (
                        caption
                        if len(paths) == 1
                        else f"{caption}\n\n📦 Part {index}/{len(paths)}"
                    )
                    results.append(
                        self.app.send_video(
                            chat_id,
                            path,
                            caption=part_caption,
                            thumb=prepared_thumbnail,
                            duration=int(duration or 0),
                            supports_streaming=True,
                            progress=self._progress(progress),
                        )
                    )
        finally:
            if prepared_thumbnail and str(prepared_thumbnail).startswith(tempfile.gettempdir()):
                Path(prepared_thumbnail).unlink(missing_ok=True)

        cleanup([path for path in paths if Path(path) != Path(file_path)])
        return results

    @staticmethod
    def _progress(callback):
        if not callback:
            return None

        def cb(current, total):
            callback(current, total, "telegram_upload")

        return cb
