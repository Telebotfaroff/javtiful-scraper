from dataclasses import dataclass
from queue import Queue
from threading import Lock

@dataclass
class Job:
    id: str
    url: str
    quality: str = "best"
    uploader: str = "telegram"
    target: str | int | None = None

class JobQueue:
    def __init__(self):
        self.queue=Queue(); self._lock=Lock(); self._counter=0
    def add(self,url,quality="best",uploader="telegram",target=None):
        with self._lock:
            self._counter+=1
            job=Job(f"JOB-{self._counter:06d}",url,quality,uploader,target); self.queue.put(job); return job
    def get(self): return self.queue.get()
    def done(self): self.queue.task_done()
