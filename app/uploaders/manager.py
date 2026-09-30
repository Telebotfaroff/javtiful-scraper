from .base import BaseUploader
from .gofile import GoFileUploader

class UploadManager:
    def __init__(self, register_defaults=True):
        self.providers = {}
        if register_defaults:
            self.register(GoFileUploader())

    def register(self, provider: BaseUploader):
        self.providers[provider.name] = provider

    def get(self, name="gofile"):
        if name not in self.providers:
            raise KeyError(f"Unknown uploader: {name}")
        return self.providers[name]

    def names(self):
        return list(self.providers)
