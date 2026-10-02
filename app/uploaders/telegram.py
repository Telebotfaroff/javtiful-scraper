import logging
import math
import os
import subprocess
import tempfile
import time
import threading
from pathlib import Path

import requests
from pyrogram import Client
from pyrogram.errors import FloodWait
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
        base_session = session or os.getenv("TELEGRAM_UPLOAD_SESSION", "javdl_uploads")
        sessions_env = os.getenv("TELEGRAM_UPLOAD_SESSIONS", "").strip()
        if sessions_env:
            sessions = [item.strip() for item in sessions_env.split(",") if item.strip()]
        else:
            client_count = int(os.getenv("TELEGRAM_UPLOAD_CLIENTS", "1"))
            if client_count < 1:
                raise ValueError("TELEGRAM_UPLOAD_CLIENTS must be >= 1")
            sessions = [base_session] + [
                f"{base_session}_{index}" for index in range(2, client_count + 1)
            ]

        concurrency = int(
            max_concurrent_transmissions
            or os.getenv("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS", "8")
        )
        if concurrency < 1:
            raise ValueError("TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS must be >= 1")

        self.max_concurrent_transmissions = concurrency
        self._clients = []
        self._client_loads = []
        self._pool_lock = threading.Lock()
        for upload_session in sessions:
            client = Client(
                upload_session,
                api_id=int(api_id or os.environ["TELEGRAM_API_ID"]),
                api_hash=api_hash or os.environ["TELEGRAM_API_HASH"],
                bot_token=bot_token or os.getenv("TELEGRAM_BOT_TOKEN"),
                max_concurrent_transmissions=concurrency,
            )
            self._clients.append(client)
            self._client_loads.append(0)

        # WZML-style helper-client pool: each client has its own MTProto
        # connection/session. A job is pinned to the least-loaded client for
        # its whole upload, avoiding contention on one Pyrogram session.
        logger.info(
            "TELEGRAM UPLOAD POOL: clients=%d concurrency_per_client=%d sessions=%s",
            len(self._clients),
            concurrency,
            ",".join(sessions),
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
        """Prepare the best possible Telegram-compatible thumbnail.

        If the source is already a JPEG within Telegram's thumbnail limits,
        keep the original bytes untouched. Otherwise convert it to JPEG using
        the highest quality that fits the limits.
        """
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
            content_type = response.headers.get("content-type", "").lower()
            logger.info(
                "THUMBNAIL: HTTP %s, content-type=%s, bytes=%s",
                response.status_code,
                content_type or "unknown",
                len(response.content),
            )
            response.raise_for_status()

            suffix = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".img"
            raw = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            raw.write(response.content)
            raw.close()
            raw_path = raw.name

            # Preserve a compliant JPEG exactly as downloaded. This avoids
            # an unnecessary recompression/quality loss.
            if (
                "jpeg" in content_type
                and len(response.content) <= 200_000
            ):
                try:
                    probe = subprocess.check_output(
                        [
                            "ffprobe", "-v", "error",
                            "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-of", "csv=p=0:s=x",
                            raw_path,
                        ],
                        text=True,
                    ).strip()
                    width, height = [int(x) for x in probe.split("x", 1)]
                    if width <= 320 and height <= 320:
                        logger.info(
                            "THUMBNAIL: preserving original JPEG unchanged: %dx%d, %d bytes",
                            width,
                            height,
                            len(response.content),
                        )
                        return raw_path
                    logger.info(
                        "THUMBNAIL: original JPEG is %dx%d; resizing is required",
                        width,
                        height,
                    )
                except Exception as exc:
                    logger.warning(
                        "THUMBNAIL: could not inspect original JPEG dimensions: %s",
                        exc,
                    )

            jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            jpg.close()
            jpg_path = jpg.name

            # Telegram video thumbnails are limited to 320x320 and 200 KB.
            # Start at the highest JPEG quality and keep the best encode that
            # fits, so quality is reduced only as much as Telegram requires.
            best_path = None
            best_size = 0
            for quality in range(2, 32, 2):
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
                if size <= 200_000 and size >= best_size:
                    if best_path:
                        Path(best_path).unlink(missing_ok=True)
                    best_path = jpg_path
                    best_size = size
                    jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    jpg.close()
                    jpg_path = jpg.name

            if best_path:
                logger.info(
                    "THUMBNAIL: selected highest-quality compliant encode: %s (%d bytes)",
                    best_path,
                    best_size,
                )
                return best_path

            logger.warning("THUMBNAIL: no JPEG encode fit under 200 KB")

        except Exception as exc:
            logger.exception("THUMBNAIL: download/conversion failed: %s", exc)
        finally:
            if raw_path:
                # Do not delete a raw JPEG that is being returned unchanged.
                if not (
                    jpg_path is None
                    and Path(raw_path).exists()
                    and "jpeg" in content_type
                    and len(response.content) <= 200_000
                ):
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

            best_path = None
            best_size = 0
            for quality in range(2, 32, 2):
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
                if size <= 200_000 and size >= best_size:
                    if best_path:
                        Path(best_path).unlink(missing_ok=True)
                    best_path = jpg_path
                    best_size = size
                    jpg = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
                    jpg.close()
                    jpg_path = jpg.name

            if best_path:
                logger.info(
                    "THUMBNAIL FALLBACK: selected highest-quality encode: %s (%d bytes)",
                    best_path,
                    best_size,
                )
                return best_path

        except Exception as exc:
            logger.exception("THUMBNAIL FALLBACK: FFmpeg failed: %s", exc)

        if jpg_path:
            Path(jpg_path).unlink(missing_ok=True)

        logger.error("THUMBNAIL: no usable thumbnail could be created")
        return None

    def _acquire_client(self):
        with self._pool_lock:
            index = min(range(len(self._clients)), key=lambda i: self._client_loads[i])
            self._client_loads[index] += 1
            return index, self._clients[index]

    def _release_client(self, index):
        with self._pool_lock:
            self._client_loads[index] = max(0, self._client_loads[index] - 1)

    def _ensure_started(self, client, session_name):
        if not client.is_connected:
            client.start()
            logger.info("TELEGRAM UPLOAD: client started session=%s", session_name)

    def send_preview(self, chat_id, thumbnail=None, title="Video", referer=None):
        """Send the extracted post thumbnail and title before the download starts."""
        if not thumbnail:
            logger.warning("TELEGRAM PREVIEW: no thumbnail available")
            return None

        prepared = self._prepare_thumbnail(
            thumbnail,
            video_path=None,
            referer=referer,
        )
        if not prepared:
            logger.warning("TELEGRAM PREVIEW: thumbnail preparation failed")
            return None

        try:
            index, client = self._acquire_client()
            try:
                self._ensure_started(client, self._clients[index].name)
                preview = client.send_photo(
                chat_id,
                prepared,
                caption=f"🎬 {title}",
            )
                logger.info("TELEGRAM PREVIEW: sent for %s", title)
                return preview
            except Exception:
            logger.exception("TELEGRAM PREVIEW: send_photo failed")
            return None
        finally:
            if str(prepared).startswith(tempfile.gettempdir()):
                Path(prepared).unlink(missing_ok=True)

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

        file_size = Path(file_path).stat().st_size
        logger.info(
            "TELEGRAM UPLOAD: file=%s size=%d bytes parts=%d concurrency=%d",
            file_path,
            file_size,
            len(paths),
            self.max_concurrent_transmissions,
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

        client_index, client = self._acquire_client()
        try:
            self._ensure_started(
                client,
                getattr(client, "name", f"client-{client_index + 1}"),
            )

            for index, path in enumerate(paths, 1):
                part_caption = (
                    caption
                    if len(paths) == 1
                    else f"{caption}\n\n📦 Part {index}/{len(paths)}"
                )

                logger.info(
                    "TELEGRAM UPLOAD: starting part %d/%d path=%s size=%d bytes",
                    index,
                    len(paths),
                    path,
                    Path(path).stat().st_size,
                )

                started_at = time.monotonic()
                last_logged_at = started_at
                last_logged_bytes = 0

                def upload_progress(current, total):
                    nonlocal last_logged_at, last_logged_bytes
                    if progress:
                        progress(current, total, "telegram_upload")

                    now = time.monotonic()
                    if now - last_logged_at >= 5:
                        delta_bytes = current - last_logged_bytes
                        delta_time = now - last_logged_at
                        mbps = (
                            delta_bytes / delta_time / 1024 / 1024
                            if delta_time > 0
                            else 0
                        )
                        logger.info(
                            "TELEGRAM SPEED: part=%d/%d %.2f MB/s %.1f%% (%d/%d bytes)",
                            index,
                            len(paths),
                            mbps,
                            (current / total * 100) if total else 0,
                            current,
                            total,
                        )
                        last_logged_at = now
                        last_logged_bytes = current

                while True:
                    try:
                        results.append(
                            client.send_video(
                                chat_id,
                                path,
                                caption=part_caption,
                                thumb=prepared_thumbnail,
                                duration=int(duration or 0),
                                supports_streaming=True,
                                progress=upload_progress,
                            )
                        )
                        break
                    except FloodWait as exc:
                        wait_seconds = int(getattr(exc, "value", 0) or getattr(exc, "x", 0) or 0)
                        wait_seconds = max(1, wait_seconds)
                        logger.warning(
                            "TELEGRAM FLOODWAIT: %ss before retrying part %d/%d",
                            wait_seconds,
                            index,
                            len(paths),
                        )
                        time.sleep(wait_seconds)

                elapsed = max(0.001, time.monotonic() - started_at)
                average_mbps = Path(path).stat().st_size / elapsed / 1024 / 1024
                logger.info(
                    "TELEGRAM SPEED: part=%d/%d completed in %.1fs average=%.2f MB/s",
                    index,
                    len(paths),
                    elapsed,
                    average_mbps,
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
            self._release_client(client_index)

        cleanup([path for path in paths if Path(path) != Path(file_path)])
        logger.info("TELEGRAM UPLOAD: completed successfully")
        return results

    @property
    def client_count(self):
        return len(self._clients)

    @staticmethod
    def _progress(callback):
        if not callback:
            return None

        def cb(current, total):
            callback(current, total, "telegram_upload")

        return cb
