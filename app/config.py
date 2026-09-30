import os

DEFAULT_UPLOADER = os.getenv("DEFAULT_UPLOADER", "gofile")
GOFILE_TIMEOUT = int(os.getenv("GOFILE_TIMEOUT", "120"))
