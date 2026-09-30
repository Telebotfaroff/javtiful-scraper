import logging
import math
import os
import subprocess
import tempfile
from pathlib import Path

import requests
from pyrogram import Client
from app.storage.cleanup import cleanup

logger = logging.getLogger(__name__)

TELEGRAM_LIMIT = 2_000_000_000


class TelegramUploader:
    name = "telegram"

    def __init__(
        self,
        api_id=None,
        api_hash=None,
        session=None,
        bot_token=None,
        max_concurrent_transmissions=None,
    ):
        # Dedicated upload session: bot updates and large file transfers
        # do not share the same Pyrogram client/session.
        upload_session = (
            session
            or os.getenv("TELEGRAM_UPLOAD_SESSION", "javdl_uploads")
        )
        concurrency = int(
            max_concurrent_transmissions
            or os.getenv("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS", "4")
        )
        if concurrency < 1:
            raise ValueError("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS must be >= 1")

        self.max_concurrent_transmissions = concurrency
        self.app = Client(
            upload_session,
            api_id=int(api_id or os.environ["TELEGRAM_API_ID"]),
            api_hash=api_hash or os.environ["TELEGRAM_API_HASH"],
            bot_token=bot_token or os.getenv("TELEGRAM_BOT_TOKEN"),
            max_concurrent_transmissions=concurrency,
        )
        logger.info(
            "TELEGRAM UPLOAD: dedicated session=%s max_concurrent_transmissions=%d",
            upload_session,
            concurrency,
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
    def _prepare_thumbnail(thumbnail, video_path=None, referer=None):
        """Download/normalize a poster, with a video-frame fallback."""
        if not thumbnail:
            logger.warning("THUMBNAIL: crawler returned no thumbnail URL")
            return TelegramUploader._fallback_thumbnail(video_path)

        value = str(thumbnail).strip()
        if not value:
            logger.warning("THUMBNAIL: crawler returned an empty thumbnail URL")
            return TelegramUploader._fallback_thumbnail(video_path)

        if not value.startswith(("http://", "https://")):
            path = Path(value)
            if path.exists():
                logger.info("THUMBNAIL: using existing local file: %s", path)
                return str(path)
            logger.warning("THUMBNAIL: local file does not exist: %s", value)
            return TelegramUploader._fallback_thumbnail(video_path)

        raw_path = None
        jpg_path = None
        logger.info("THUMBNAIL: found URL: %s", value)

        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            if referer:
                headers["Referer"] = str(referer)

            response = requests.get(value, timeout=20, headers=headers)
            logger.info(
                "THUMBNAIL: HTTP %s, content-type=%s, bytes=%s",
                response.status_code,
                response.headers.get("content-type", "unknown"),
                len(response.content),
            )
            response.raise_for_status()

            raw = tempfile.NamedTemporaryFile(delete=False, suffix=".img")
            raw.write(response.content)
            raw.close()
            raw_path = raw.name

            jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            jpg.close()
            jpg_path = jpg.name

            for quality in (10, 20, 30, 40, 50):
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", raw_path,
                        "-vf",
                        "scale=320:320:force_original_aspect_ratio=decrease",
                        "-frames:v", "1",
                        "-q:v", str(quality),
                        jpg_path,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                size = Path(jpg_path).stat().st_size
                logger.info(
                    "THUMBNAIL: FFmpeg quality=%s -> %d bytes",
                    quality,
                    size,
                )
                if size <= 200_000:
                    logger.info("THUMBNAIL: ready: %s (%d bytes)", jpg_path, size)
                    return jpg_path

            logger.warning("THUMBNAIL: converted image is still over 200 KB")

        except Exception as exc:
            logger.exception("THUMBNAIL: download/conversion failed: %s", exc)
        finally:
            if raw_path:
                Path(raw_path).unlink(missing_ok=True)

        if jpg_path:
            Path(jpg_path).unlink(missing_ok=True)

        logger.warning("THUMBNAIL: website thumbnail failed; trying video frame fallback")
        return TelegramUploader._fallback_thumbnail(video_path)

    @staticmethod
    def _fallback_thumbnail(video_path):
        if not video_path or not Path(video_path).exists():
            logger.warning("THUMBNAIL FALLBACK: video file unavailable")
            return None

        jpg_path = None
        try:
            jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            jpg.close()
            jpg_path = jpg.name

            for quality in (10, 20, 30, 40, 50):
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", "1", "-i", str(video_path),
                        "-frames:v", "1",
                        "-vf",
                        "scale=320:320:force_original_aspect_ratio=decrease",
                        "-q:v", str(quality),
                        jpg_path,
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                size = Path(jpg_path).stat().st_size
                logger.info(
                    "THUMBNAIL FALLBACK: quality=%s -> %d bytes",
                    quality,
                    size,
                )
                if size <= 200_000:
                    logger.info("THUMBNAIL FALLBACK: ready: %s", jpg_path)
                    return jpg_path

        except Exception as exc:
            logger.exception("THUMBNAIL FALLBACK: FFmpeg failed: %s", exc)

        if jpg_path:
            Path(jpg_path).unlink(missing_ok=True)

        logger.error("THUMBNAIL: no usable thumbnail could be created")
        return None

    def upload(
        self,
        file_path,
        chat_id,
        caption="",
        thumbnail=None,
        duration=None,
        progress=None,
        referer=None,
    ):
        paths = self.split_if_needed(file_path)
        results = []

        logger.info(
            "TELEGRAM UPLOAD: file=%s size=%d bytes parts=%d",
            file_path,
            Path(file_path).stat().st_size,
            len(paths),
        )

        prepared_thumbnail = self._prepare_thumbnail(
            thumbnail,
            video_path=file_path,
            referer=referer,
        )
        logger.info(
            "TELEGRAM UPLOAD: final thumbnail=%s",
            prepared_thumbnail or "NONE",
        )

        try:
            # Keep the dedicated upload client alive across jobs.
            if not self.app.is_connected:
                self.app.start()
                logger.info("TELEGRAM UPLOAD: dedicated upload client started")

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

                logger.info(
                    "TELEGRAM UPLOAD: part %d/%d sent successfully",
                    index,
                    len(paths),
                )
        except Exception:
            logger.exception("TELEGRAM UPLOAD: send_video failed")
            raise
        finally:
            if (
                prepared_thumbnail
                and str(prepared_thumbnail).startswith(tempfile.gettempdir())
            ):
                Path(prepared_thumbnail).unlink(missing_ok=True)

        cleanup([path for path in paths if Path(path) != Path(file_path)])
        logger.info("TELEGRAM UPLOAD: completed successfully")
        return results

    @staticmethod
    def _progress(callback):
        if not callback:
            return None

        def cb(current, total):
            callback(current, total, "telegram_upload")

        return cb
