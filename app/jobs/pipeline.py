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

    def run(self, job, progress=None):
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

        source_path = video.local_path
        logger.info("PIPELINE: download complete: %s", source_path)
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
                    "caption": video.title,
                    "thumbnail": video.thumbnail,
                    "duration": video.duration,
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

                result = uploader.upload(path, **kwargs)

                if hasattr(uploader, "verify") and not uploader.verify(result):
                    raise RuntimeError(
                        f"{job.uploader} upload verification failed for {path}"
                    )

                results.append(result)

                if progress:
                    progress(index, len(upload_paths), "upload")

            logger.info("PIPELINE: all uploads completed")
            return video, results

        finally:
            if len(results) == len(upload_paths) and upload_paths:
                cleanup([source_path, *temporary_paths])
