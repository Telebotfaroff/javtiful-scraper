# JAVDL

Modular Javtiful extraction, quality-aware downloading, clipping and upload pipeline.

Pipeline: URL -> extractor -> quality selection -> downloader -> optional clipping -> uploader -> cleanup.

Telegram uses Pyrogram API ID/hash and can use a bot token. Videos are sent as videos with title caption, thumbnail, duration and streaming enabled. Files above the Telegram upload ceiling are split before sending. Progress callbacks are throttled to avoid excessive Telegram edits.

Colab bootstrap: python scripts/colab.py. GPU is useful for compatible FFmpeg processing; downloading is primarily network-bound.

Use only with content you are authorized to download and redistribute.
