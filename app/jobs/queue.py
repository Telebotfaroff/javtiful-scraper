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
    # Optional custom caption used by batch/channel downloads.
    caption: Optional[str] = None
    # Send the thumbnail as a separate Telegram photo before the video.
    separate_thumbnail: bool = False
    # Retry a failed channel upload to the requesting chat when possible.
    fallback_target: str | int | None = None


class JobQueue:
    def __init__(self):
        self.queue = Queue()
        self._lock = Lock()
        self._counter = 0

    def add(self, url, quality="best", uploader="telegram", target=None, clips=None, caption=None, separate_thumbnail=False):
        with self._lock:
            self._counter += 1
            job = Job(
                f"JOB-{self._counter:06d}",
                url,
                quality,
                uploader,
                target,
                clips,
                caption,
                separate_thumbnail,
            )
            self.queue.put(job)
            return job

    def get(self):
        return self.queue.get()

    def done(self):
        self.queue.task_done()
