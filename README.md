# 🚀 JAVDL

**Javtiful downloader, Telegram uploader and batch-processing pipeline.**

JAVDL extracts available Javtiful video streams, downloads them, optionally clips them, and uploads the result to Telegram or GoFile.

> **Branch:** javdl

---

## ✨ Features

- 🔎 Javtiful stream extraction with browser fallback
- 🎬 Video metadata and thumbnail extraction
- 📥 Stream downloading with retries and Referer handling
- ✂️ Optional time-range clipping
- 🤖 Telegram bot interface with progress updates
- 📺 Channel/studio batch downloading
- ⚡ Parallel batch downloading and Telegram uploads
- 👥 Multiple Telegram upload clients
- 🖼️ Telegram video thumbnails
- 📊 Upload/download speed diagnostics
- ☁️ GoFile guest uploads
- 🧹 Automatic cleanup after successful uploads
- ☁️ Google Colab-ready runner

---

## 🚀 Run in Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Telebotfaroff/javtiful-scraper/blob/javdl/colab/javdl.ipynb)

The Colab notebook is the easiest way to run JAVDL without setting up a local environment.

### Required Colab Secrets

Add these under **Colab → Secrets**:

| Secret | Required |
|---|---|
| **TELEGRAM_API_ID** | ✅ |
| **TELEGRAM_API_HASH** | ✅ |
| **TELEGRAM_BOT_TOKEN** | ✅ |

The notebook automatically:

1. Clones the javdl branch.
2. Installs FFmpeg, Python dependencies and Playwright Chromium.
3. Loads Telegram credentials from Colab Secrets.
4. Configures the Telegram upload client pool.
5. Runs a syntax/import pre-flight check.
6. Starts the Telegram bot.

---

## 🤖 Telegram Bot

Send the bot a Javtiful video URL.

### Video flow

Javtiful URL → Preview → Download → Full / Clip → Telegram upload

Channel/studio URLs can also be sent to the bot for batch downloading.

### Clip mode

You can provide ranges such as:

    00:00-01:30

The requested segment is processed before upload.

---

## 📺 Channel / Studio Batch Downloads

Send a Javtiful channel or studio URL to the bot.

The bot can:

1. 🔎 Inspect the channel/studio.
2. 📊 Show the total video count and available pages.
3. 📄 Ask which page to process.
4. 📥 Download videos from that page.
5. 📤 Upload them to Telegram.
6. 🖼️ Include the video's thumbnail.
7. 📝 Generate a caption containing the video code and title.

### Page numbering

- **0** → website page 1
- **1** → website page 2
- **2** → website page 3

### Parallel mode

Parallel batch processing can download the next video while Telegram uploads are running.

The upload worker count and download buffer can be configured through environment variables.

---

## ⚡ Telegram Upload Performance

JAVDL supports a Telegram upload-client pool.

### Current Colab defaults

    TELEGRAM_UPLOAD_CLIENTS=2
    TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS=8

Two upload clients allow multiple batch uploads to progress independently.

TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS controls Pyrogram's transmission concurrency inside an upload. It is **not** the number of videos uploaded simultaneously.

For batch uploads, the application also supports multiple upload workers.

Optional configuration:

    TELEGRAM_BATCH_UPLOAD_WORKERS=2
    TELEGRAM_BATCH_BUFFER=2

---

## ☁️ GoFile

GoFile is the default cloud uploader.

It uses guest/anonymous uploads, so no GoFile account token is required.

The provider dynamically selects an available upload server and returns the resulting download URL.

Provider implementation: **app/uploaders/gofile.py**

Additional upload providers can be added through the uploader manager.

---

## 🧩 Architecture

    Telegram Bot
         │
         ▼
    URL / Channel Handler
         │
         ▼
      Job Queue
         │
         ├── Javtiful Extractor
         │       └── Playwright fallback
         │
         ├── Stream Downloader
         │
         ├── Optional Clipper
         │
         └── Upload Manager
                  ├── Telegram
                  └── GoFile

### Main components

| Component | Location |
|---|---|
| Telegram handlers | app/bot/handlers.py |
| Telegram progress | app/bot/progress.py |
| Javtiful extractor | app/extractor/javtiful.py |
| Channel extractor | app/extractor/channel.py |
| Downloader | app/downloader/downloader.py |
| Quality handling | app/downloader/quality.py |
| Pipeline | app/jobs/pipeline.py |
| Queue | app/jobs/queue.py |
| Telegram uploader | app/uploaders/telegram.py |
| GoFile uploader | app/uploaders/gofile.py |
| Upload manager | app/uploaders/manager.py |
| Clipping | app/clipping/clipper.py |
| Cleanup | app/storage/cleanup.py |

---

## 🛠️ Local Setup

Clone the repository and switch to the javdl branch:

    git clone --branch javdl --depth 1 https://github.com/Telebotfaroff/javtiful-scraper.git
    cd javtiful-scraper

Install dependencies:

    pip install -r requirements.txt
    python -m playwright install chromium

Install FFmpeg separately if it is not already available.

Set the required Telegram environment variables:

    TELEGRAM_API_ID=your_api_id
    TELEGRAM_API_HASH=your_api_hash
    TELEGRAM_BOT_TOKEN=your_bot_token

Then start the application using the project's normal bot entry point.

---

## 📁 Google Colab

The maintained Colab runner is:

**colab/javdl.ipynb**

It is intentionally kept minimal and contains only the setup, configuration, pre-flight check and bot startup flow.

[**Open javdl.ipynb →**](https://github.com/Telebotfaroff/javtiful-scraper/blob/javdl/colab/javdl.ipynb)

---

## ⚙️ Environment Variables

### Telegram

    TELEGRAM_API_ID=
    TELEGRAM_API_HASH=
    TELEGRAM_BOT_TOKEN=

    TELEGRAM_SESSION=javdl_colab
    TELEGRAM_UPLOAD_SESSION=javdl_uploads
    TELEGRAM_UPLOAD_CLIENTS=2
    TELEGRAM_MAX_CONCURRENT_TRANSMISSIONS=8

### Batch processing

    TELEGRAM_BATCH_UPLOAD_WORKERS=2
    TELEGRAM_BATCH_BUFFER=2

Increase batch settings carefully depending on available bandwidth and Telegram limits.

---

## 📦 Requirements

The project uses:

- Python
- Pyrogram
- TgCrypto
- Requests
- BeautifulSoup
- Playwright
- FFmpeg
- ffmpeg-python

See [requirements.txt](https://github.com/Telebotfaroff/javtiful-scraper/blob/javdl/requirements.txt) for the current dependency list.

---

## ⚠️ Usage

Use JAVDL only with content you are legally authorized to access, download, process and redistribute.

Respect the terms of the websites and services you interact with, as well as applicable copyright and privacy laws.

---

## 📌 Project Status

The javdl branch is the active downloader/Telegram pipeline.

The project is under active development, so configuration and implementation details may change.
