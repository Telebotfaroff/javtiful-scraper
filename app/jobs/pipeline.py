import logging

from app.extractor.javtiful import JavtifulExtractor
from app.downloader.downloader import Downloader
from app.clipping.clipper import clip_video
from app.storage.cleanup import cleanup

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, extractor=None, downloader=None, uploaders=None):
        self.extractor = extractor or JavtifulExtractor()
        self.downloader = downloader or Downloader()
        self.uploaders = uploaders or {}

    def prepare_download(self, job, progress=None):
        """Extract and download a video, but leave upload for the caller."""
        logger.info("PIPELINE: extracting %s", job.url)
        video = self.extractor.extract(job.url)
        logger.info(
            "PIPELINE: extracted title=%r thumbnail=%s duration=%s qualities=%s",
            video.title,
            video.thumbnail or "NONE",
            video.duration or "UNKNOWN",
            ", ".join(video.qualities) or "NONE",
        )

        if progress:
            progress(0, 0, "extract")

        self.downloader.download(
            video,
            job.quality,
            lambda current, total, stage: (
                progress(current, total, stage) if progress else None
            ),
        )
        logger.info("PIPELINE: download complete: %s", video.local_path)
        return video

    def upload_prepared(self, job, video, progress=None):
        """Upload an already downloaded video and clean it up after success."""
        source_path = video.local_path
        upload_paths = [source_path]
        temporary_paths = []
        results = []

        try:
            if job.clips:
                if progress:
                    progress(0, len(job.clips), "clip")

                logger.info("PIPELINE: creating %d clip(s)", len(job.clips))
                upload_paths = clip_video(source_path, job.clips)
                temporary_paths.extend(upload_paths)

                if progress:
                    progress(len(upload_paths), len(job.clips), "clip")

            uploader = self.uploaders[job.uploader]

            for index, path in enumerate(upload_paths, 1):
                logger.info(
                    "PIPELINE: uploading part %d/%d via %s",
                    index,
                    len(upload_paths),
                    job.uploader,
                )
                kwargs = {
                    "caption": job.caption or video.title,
                    "thumbnail": video.thumbnail,
                    "duration": video.duration,
                    "separate_thumbnail": job.separate_thumbnail,
                    "progress": (
                        lambda current, total, stage: (
                            progress(current, total, stage) if progress else None
                        )
                    ),
                }

                if job.uploader == "telegram":
                    kwargs["referer"] = video.source_url

                if job.target is not None:
                    kwargs["chat_id"] = job.target

                try:
                    result = uploader.upload(path, **kwargs)
                    if hasattr(uploader, "verify") and not uploader.verify(result):
                        raise RuntimeError(
                            f"{job.uploader} upload verification failed for {path}"
                        )
                except Exception as channel_error:
                    fallback = getattr(job, "fallback_target", None)
                    if job.uploader != "telegram" or fallback is None or fallback == kwargs.get("chat_id"):
                        raise

                    logger.warning(
                        "PIPELINE: Telegram channel upload failed for %s; falling back to chat %s: %s",
                        path, fallback, channel_error,
                    )
                    # If earlier split parts were already returned, remove them before
                    # retrying the complete upload in the fallback chat.
                    if results and hasattr(uploader, "delete_uploaded_messages"):
                        try:
                            uploader.delete_uploaded_messages(kwargs.get("chat_id"), results)
                        except Exception:
                            logger.exception("PIPELINE: unable to clean partial channel upload")
                    results.clear()
                    fallback_kwargs = dict(kwargs)
                    fallback_kwargs["chat_id"] = fallback
                    result = uploader.upload(path, **fallback_kwargs)
                    if hasattr(uploader, "verify") and not uploader.verify(result):
                        raise RuntimeError(
                            f"Telegram fallback upload verification failed for {path}"
                        )

                results.append(result)

                if progress:
                    progress(index, len(upload_paths), "upload")

            logger.info("PIPELINE: all uploads completed")
            return video, results

        finally:
            if len(results) == len(upload_paths) and upload_paths:
                cleanup([source_path, *temporary_paths])

    def run(self, job, progress=None):
        video = self.prepare_download(job, progress)
        return self.upload_prepared(job, video, progress)
