from abc import ABC, abstractmethod
class BaseUploader(ABC):
    name="base"
    @abstractmethod
    def upload(self, file_path, **kwargs): raise NotImplementedError
