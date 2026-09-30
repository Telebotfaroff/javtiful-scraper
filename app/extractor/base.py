from abc import ABC, abstractmethod
from app.models.video import Video

class BaseExtractor(ABC):
    name = "base"
    @abstractmethod
    def extract(self, url: str) -> Video: raise NotImplementedError
