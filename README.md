# JAVDL

Modular Javtiful extraction, quality-aware downloading, clipping and upload pipeline.

## Default cloud storage: GoFile

GoFile is the default cloud uploader and uses guest/anonymous uploads. No GoFile account token is required.

The uploader dynamically requests an available GoFile upload server, uploads the local file, and returns the resulting download page URL. The provider is isolated in app/uploaders/gofile.py.

Additional storage providers can be added later by implementing BaseUploader and registering them with UploadManager.

## Pipeline

URL -> extractor -> quality selection -> downloader -> optional clipping -> uploader -> verification -> cleanup.

## Telegram

Pyrogram uses TELEGRAM_API_ID and TELEGRAM_API_HASH. A bot token may be supplied for bot-account operation. Telegram uploads are sent as videos with metadata and progress handling.

## Colab

Run python scripts/colab.py to check GPU and FFmpeg availability.

Use only with content you are authorized to download and redistribute.
