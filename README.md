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

Force a provider explicitly:

```bash
python javtiful_scraper.py "https://javtiful.com/main" --provider javtiful
```
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

Listing results include:

- `items`
- `total_found`
- `page`
- `pagination.current_page`
- `pagination.total_pages`
- `pagination.has_next`
- `pagination.has_prev`

## GitHub Actions

Open **Actions → Test scraper → Run workflow** and enter a Javtiful URL.

The workflow accepts optional enrichment controls and validates the result according to its detected page type. The generated JSON is uploaded as the `scraper-result` artifact.

## Notes

The scraper extracts metadata present in the fetched HTML. It does not persist temporary/IP-locked player URLs. If a future provider needs JavaScript for metadata, that provider can implement its own extraction layer.
