# JAVDL

Modular video extraction, quality-aware downloading, clipping, cloud uploading and Pyrogram Telegram uploading.

## Pipeline

URL → extractor → quality selection → download → optional clips → Telegram/cloud upload → verify → cleanup.

Telegram uploads use Pyrogram API ID/hash. Files over the configured Telegram ceiling must be split before upload. Progress updates are throttled to avoid excessive Telegram edits.

Use only with content you are authorized to download and redistribute.
