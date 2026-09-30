# Javtiful Scraper

A Python CLI scraper for extracting structured Javtiful post and catalog metadata.

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
- Description, genres and referenced video/iframe sources on post pages
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

The scraper extracts information present in the fetched HTML. It does not require a browser for normal card/post metadata. If a player or field is populated only after JavaScript execution, a Playwright/network-capture layer can be added separately.
