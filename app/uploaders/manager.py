from .base import BaseUploader
class UploadManager:
    def __init__(self): self.providers={}
    def register(self, provider: BaseUploader): self.providers[provider.name]=provider
    def get(self, name):
        if name not in self.providers: raise KeyError(f"Unknown uploader: {name}")
        return self.providers[name]
