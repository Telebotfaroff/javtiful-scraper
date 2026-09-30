from dataclasses import dataclass
from queue import Queue
from threading import Lock
from typing import Optional


@dataclass
class Job:
    id: str
    url: str
    quality: str = "best"
    uploader: str = "telegram"
    target: str | int | None = None
    # None means full video. A list means only the selected clips are uploaded.
    clips: Optional[list[tuple[str, str]]] = None


class JobQueue:
    def __init__(self):
        self.queue = Queue()
        self._lock = Lock()
        self._counter = 0

    def add(self, url, quality="best", uploader="telegram", target=None, clips=None):
        with self._lock:
            self._counter += 1
            job = Job(
                f"JOB-{self._counter:06d}",
                url,
                quality,
                uploader,
                target,
                clips,
            )
            self.queue.put(job)
            return job

    def get(self):
        return self.queue.get()

    def done(self):
        self.queue.task_done()
