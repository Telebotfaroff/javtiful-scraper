# Provider-based Metadata Scraper

A Python CLI scraper with a pluggable provider architecture. Javtiful is the first provider; additional providers can be added without changing the database layer.

## Provider architecture

```
CLI / API
   |
ProviderManager
   |
+-- JavtifulProvider
+-- FutureProvider
+-- FutureProvider
```

Every provider converts its website into the same normalized metadata format. The core application does not depend on Javtiful-specific selectors.

Provider files:

- `providers/base.py` — provider interface
- `providers/javtiful.py` — Javtiful implementation
- `providers/__init__.py` — provider exports
- `javtiful_scraper.py` — CLI + provider manager facade

## Architecture

The scraper follows the same core pattern as the original Javtiful project:

```
Javtiful page
    |
    +-- /main, search, category, listing
    |       |
    |       +--> shared video-card parser
    |
    +-- /actresses
    |       +--> actress directory parser
    |
    +-- /actress/{slug}
    |       +--> shared video-card parser
    |
    +-- /channels
    |       +--> studio/channel directory parser
    |
    +-- /channel/{slug}
    |       +--> shared video-card parser
    |
    +-- /video/{id}/{code}
            +--> full post-detail parser
```

## Features

- Shared video-card extraction for homepage/listing, actress, and studio/channel pages
- Actress directory extraction from `/actresses`
- Studio/channel directory extraction from `/channels`
- Pagination detection
- URL-first video code detection
- Title, thumbnail and duration extraction from listing cards
- Actress and studio/channel slug extraction from cards
- Optional enrichment by opening individual video pages
- JSON-LD and OpenGraph/meta extraction on individual posts
- Release/upload date extraction
- Description and genre extraction on post pages
- Persistent metadata only: no temporary/IP-locked video-source URLs are stored or returned
- Retry and timeout handling
- JSON output suitable for APIs or database ingestion

## Install

```bash
python -m pip install -r requirements.txt
```

## Usage

Scrape any Javtiful URL. The scraper automatically determines the page type:

```bash
python javtiful_scraper.py "https://javtiful.com/main"
python javtiful_scraper.py "https://javtiful.com/actresses"
python javtiful_scraper.py "https://javtiful.com/actress/ACTRESS-SLUG"
python javtiful_scraper.py "https://javtiful.com/channels"
python javtiful_scraper.py "https://javtiful.com/channel/CHANNEL-SLUG"
python javtiful_scraper.py "https://javtiful.com/video/12345/example-code"
```

Force a provider explicitly:

```bash
python javtiful_scraper.py "https://javtiful.com/main" --provider javtiful
```

Save JSON:

```bash
python javtiful_scraper.py "https://javtiful.com/main" -o result.json
```

### Listing without detail requests

This is the recommended mode for large pages:

```bash
python javtiful_scraper.py "https://javtiful.com/main" --no-enrich
```

### Enrich listing cards

This opens individual video pages to fill richer metadata:

```bash
python javtiful_scraper.py "https://javtiful.com/main" --max-enrich 10
```

### Specific page number

```bash
python javtiful_scraper.py "https://javtiful.com/actress/ACTRESS-SLUG" --page 2 --no-enrich
```

## Result types

The top-level `type` field identifies the parser used:

- `post` — individual `/video/...` page
- `listing` — homepage/search/category/actress/studio video listing
- `actress_directory` — `/actresses`
- `studio_directory` — `/channels`

Listing results include `items`, `total_found`, `page`, and pagination information.

## GitHub Actions

Open **Actions → Test scraper → Run workflow** and enter a Javtiful URL. The workflow accepts optional enrichment controls and validates the result according to its detected page type. The generated JSON is uploaded as the `scraper-result` artifact.

### Export video codes to Javcode

Open **Actions → Export Javtiful Video Codes → Run workflow** and provide a listing URL such as:

- `https://javtiful.com/actress/ACTRESS-SLUG`
- `https://javtiful.com/channel/CHANNEL-SLUG`
- `https://javtiful.com/category/CATEGORY-SLUG`

The workflow accepts a **Page Limit** input (1–10,000; default 10,000). For example, set it to `25` to scrape at most the first 25 listing pages. The run also stops early if it reaches an empty or repeated page. It extracts unique video codes and commits plain-text files into `Javcode/<url-slug>/`. Each `.txt` file contains **one clean video code per line**—no JSON formatting, titles, or other metadata—and contains at most 100 codes.

Example:

```
Javcode/
└── ACTRESS-SLUG/
    ├── codes-001.txt
    ├── codes-002.txt
    ├── codes-003.txt
    └── ...
```

Run the exporter locally:

```bash
python export_javcodes.py --url "https://javtiful.com/actress/ACTRESS-SLUG" --max-pages 25
```

The output folder is derived from the URL slug. The exporter normalizes codes, removes duplicates within the scraped listing, and skips codes already stored in other `Javcode/` folders (including legacy JSON chunks). It removes stale numbered `.json` and `.txt` chunks when refreshing the same slug.

## Notes

The scraper extracts metadata present in the fetched HTML. It does not persist temporary/IP-locked player URLs. If a future provider needs JavaScript for metadata, that provider can implement its own extraction layer.

## Full crawler

`crawler.py` turns the provider into a full database crawler. A single run can:

1. Crawl every page of `/main`
2. Crawl the `/actresses` directory and every actress video page
3. Crawl the `/channels` directory and every studio video page
4. Open each discovered video page for complete metadata
5. Deduplicate using video ID, normalized code, and canonical URL
6. Write the compact grouped JSON database
7. Rebuild database indexes and run statistics

Run locally in interactive single-URL mode:

```bash
python crawler.py
```

The crawler asks for an actress/studio/category/listing URL, then a start page and optional end page. Non-interactive mode is also supported:

```bash
python crawler.py --url "https://javtiful.com/actress/ACTRESS-SLUG" --start-page 1 --end-page 31 --delay 1
```

Legacy full-scope mode remains available:

```bash
python crawler.py --scope all --delay 1
python crawler.py --scope main
python crawler.py --scope actresses
python crawler.py --scope studios
```

### Database layout

```
database/
├── actress/<A-Z>/<slug>/videos.json
├── studio/<slug>/videos.json
├── code/<CODE>/videos.json
└── index/
    ├── indexactress.json
    ├── indexstudio.json
    ├── indexcode.json
    └── database.json
```

Video records contain persistent metadata only. Temporary/IP-locked video-source URLs are never stored.

### GitHub Actions crawler

All crawler workflows are manual-only (`workflow_dispatch`). Available workflows:

- **Actress Index** — refreshes the actress directory and crawl progress.
- **Crawl Actress** — processes one actress or the next pending/failed actress, with checkpoints.
- **Crawl Main** — crawls `/main`.
- **Crawl Studios** — crawls the studio/channel directory and listings.
- **Crawl Categories** — crawls category listings.
- **Test scraper** — manual scraper validation.
- **Export Javtiful Video Codes** — exports unique codes from a supplied actress, channel, or category URL.

The workflows commit and push their respective output files automatically. The actress queue is stored in `database/index/indexactress.json`.

The GitHub Actions crawler supports resumable runs through `database/crawler_state.json`. A checkpoint is saved after each successfully completed listing page; failed video-detail requests are retried before being recorded as errors. For a fresh crawl, disable Resume or remove the saved checkpoint. For an initial test, use a small `max_pages` value because a full crawl can make many detail-page requests.
