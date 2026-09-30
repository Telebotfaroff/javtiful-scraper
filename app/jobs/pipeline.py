from app.extractor.javtiful import JavtifulExtractor
from app.downloader.downloader import Downloader
from app.storage.cleanup import cleanup

class Pipeline:
    def __init__(self, extractor=None, downloader=None, uploaders=None):
        self.extractor=extractor or JavtifulExtractor(); self.downloader=downloader or Downloader(); self.uploaders=uploaders or {}
    def run(self,job,progress=None):
        video=self.extractor.extract(job.url)
        self.downloader.download(video,job.quality,lambda c,t,s: progress(s,c,t) if progress else None)
        try:
            uploader=self.uploaders[job.uploader]
            result=uploader.upload(video.local_path,job.target,caption=video.title,thumbnail=video.thumbnail,duration=video.duration,progress=lambda c,t,s: progress(s,c,t) if progress else None)
            return video,result
        finally:
            if video.local_path: cleanup([video.local_path])
