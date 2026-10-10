# Resumable media batch workflow

This workflow processes a JSON manifest of media you own or are authorized to
redistribute. It does not crawl a website or discover channel entries itself;
a permitted source integration must supply the manifest.

## Files

- `.github/workflows/resumable-authorized-media.yml`: scheduled/manual runner.
- `database/authorized_media.json`: input manifest.
- `database/processed.json`: persistent per-item checkpoint database.
- `app/jobs/checkpoint_store.py`: atomic JSON status store.
- `app/jobs/resumable_manifest_runner.py`: download/upload runner.

## Manifest format

Edit `database/authorized_media.json` and add entries with stable IDs:

```json
{
  "items": [
    {
      "id": "my-video-001",
      "url": "https://media.example.org/my-video.mp4",
      "title": "My video",
      "thumbnail": "https://media.example.org/my-video.jpg",
      "duration": 123,
      "source_url": "https://media.example.org/my-video-page"
    }
  ]
}
```

The `url` must be a direct HTTP(S) media URL that the runner is allowed to
download. Use a unique, stable `id` for each item. The example URLs are
placeholders and will not work as media sources.

## Required GitHub Actions secrets

In **Settings → Secrets and variables → Actions**, add:

- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `TELEGRAM_TARGET`

The bot must have permission to post in the destination channel. The workflow
uses the repository's `GITHUB_TOKEN` to commit checkpoint changes; the workflow
has `contents: write` permission. If repository policy restricts this token,
allow workflow write access before running.

## Run it

1. Commit the manifest to the `javdl` branch.
2. Open **Actions → Resumable Authorized Media Batch → Run workflow**.
3. Keep the default manifest/checkpoint paths unless you intentionally use
   alternate repository-relative JSON files.
4. Inspect the run logs and the updated `database/processed.json`.

The workflow is also scheduled hourly. GitHub scheduled workflows run from the
repository's **default branch** only; for automatic hourly runs, merge/copy the
workflow to the default branch or make `javdl` the default branch. Manual runs
can target `javdl`.

## Resume behavior

- Items marked `completed` are skipped on later runs.
- Failed items are recorded and retried on later runs until
  `MAX_ITEM_ATTEMPTS` (default 5) is reached.
- Checkpoint changes are committed and pushed after each item's final result.
- The workflow is limited to 350 minutes. The next scheduled/manual run resumes
  from the repository checkpoint after a timeout or runner disconnect.
- One run at a time is allowed for the same ref to avoid competing JSON writes.

A crash in the narrow interval after Telegram accepts an upload but before the
checkpoint push can still cause that item to be uploaded again on the next run.
This is an at-least-once workflow, not a guarantee of exactly-once delivery.

## Limitations

- This runner takes a manifest; it does not accept a channel URL and crawl it.
- It expects direct HTTP(S) video URLs that the existing downloader can process
  (regular media URLs or HLS playlists).
- A Telegram upload client must be able to authenticate in GitHub Actions using
  the configured credentials. Test with one small authorized media item first.
- Keep the repository private if the manifest contains URLs that should not be
  public. Never store tokens, session strings, or credentials in JSON files.
