# Javtiful Scraper

A Python CLI scraper for extracting structured metadata from a Javtiful page.

## Features

- HTTP fetching with a browser-like User-Agent
- JSON-LD, OpenGraph/meta and DOM extraction
- Video code detection
- Title, date, duration and description extraction
- Thumbnail extraction
- Actress/studio/tag discovery
- Publicly referenced `<video>`, `<source>` and iframe URLs
- JSON output suitable for APIs or database ingestion

## Install

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
python javtiful_scraper.py "https://example.com/page"
```

Save JSON:

```bash
python javtiful_scraper.py "https://example.com/page" -o result.json
```

## Output

The scraper returns a normalized object containing `url`, `code`, `title`, `date`, `duration`, `thumbnail`, `actresses`, `studio`, `genres`, `description`, and `video_sources`.

## Notes

The scraper only extracts information present in the fetched HTML. If a player is populated dynamically by JavaScript, `video_sources` may be empty; a Playwright/network-capture layer can be added later.
