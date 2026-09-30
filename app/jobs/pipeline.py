from app.extractor.javtiful import JavtifulExtractor
from app.downloader.downloader import Downloader
from app.clipping.clipper import clip_video
from app.storage.cleanup import cleanup


class Pipeline:
    def __init__(self, extractor=None, downloader=None, uploaders=None):
        self.extractor = extractor or JavtifulExtractor()
        self.downloader = downloader or Downloader()
        self.uploaders = uploaders or {}

    def run(self, job, progress=None):
        video = self.extractor.extract(job.url)

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
        upload_paths = [source_path]
        temporary_paths = []
        results = []

        try:
            # Clipping is strictly opt-in. None/empty means upload the full video.
            if job.clips:
                if progress:
                    progress(0, len(job.clips), "clip")

                upload_paths = clip_video(source_path, job.clips)
                temporary_paths.extend(upload_paths)

                if progress:
                    progress(len(upload_paths), len(job.clips), "clip")

            uploader = self.uploaders[job.uploader]

            for index, path in enumerate(upload_paths, 1):
                kwargs = {
                    "caption": video.title,
                    "thumbnail": video.thumbnail,
                    "duration": video.duration,
                    "progress": (
                        lambda current, total, stage: (
                            progress(stage, current, total) if progress else None
                        )
                    ),
                }

                # TelegramUploader expects chat_id; cloud uploaders accept **kwargs.
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

            return video, results

        finally:
            # Cleanup happens only after every requested upload completed and
            # verified. A partial/failed job keeps the files for retry/debugging.
            if len(results) == len(upload_paths) and upload_paths:
                cleanup([source_path, *temporary_paths])
