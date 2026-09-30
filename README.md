# JAVDL

Modular Javtiful extraction, quality-aware downloading, clipping and upload pipeline.

## Open in Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Telebotfaroff/javtiful-scraper/blob/javdl/colab/javdl.ipynb)

The Colab notebook is preconfigured for the `javdl` branch. It now tests the guide-based Javtiful stream detection and includes an optional direct stream-download test. Add your Telegram API ID, API hash, and bot token through **Colab Secrets** before starting the bot.

## Default cloud storage: GoFile

GoFile is the default cloud uploader and uses guest/anonymous uploads. No GoFile account token is required.

The uploader dynamically requests an available GoFile upload server, uploads the local file, and returns the resulting download page URL. The provider is isolated in `app/uploaders/gofile.py`.

Additional storage providers can be added later by implementing BaseUploader and registering them with UploadManager.

## Pipeline

Javtiful URL -> stream extraction -> quality selection -> stream downloader -> optional clipping -> uploader -> verification -> cleanup.

Clipping is optional. Selecting full video keeps the original video, while selecting clipping processes only the requested time ranges. Telegram uploads automatically split files above the configured 2 GB threshold.

## Telegram

Pyrogram uses `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`. A bot token may be supplied for bot-account operation. Telegram uploads are sent as videos with metadata and progress handling.

## Colab

Run `python scripts/colab.py` to check GPU and FFmpeg availability.

The full interactive test/runner is available in [`colab/javdl.ipynb`](https://github.com/Telebotfaroff/javtiful-scraper/blob/javdl/colab/javdl.ipynb).

Use only with content you are authorized to download and redistribute.
