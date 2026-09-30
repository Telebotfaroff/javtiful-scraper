#!/usr/bin/env python3

import argparse
import json
import sys
from urllib.parse import urlparse

import requests

from providers.base import BaseProvider
from providers.javtiful import JavtifulProvider


class ProviderManager:
    """Registry and resolver for pluggable scraper providers."""

    def __init__(self, providers=None):
        self.providers = []
        for provider in providers or [JavtifulProvider]:
            self.register(provider())

    def register(self, provider):
        if not isinstance(provider, BaseProvider):
            raise TypeError(f"Provider {provider!r} must inherit BaseProvider")
        self.providers.append(provider)

    def names(self):
        return [provider.name for provider in self.providers]

    def resolve(self, url, name=None):
        if name:
            for provider in self.providers:
                if provider.name.lower() == name.lower():
                    return provider
            raise ValueError(f"Unknown provider: {name}")
        for provider in self.providers:
            if provider.supports(url):
                return provider
        raise ValueError(f"No provider supports URL: {url}")

    def scrape(self, url, provider=None, enrich=False, max_enrich=None):
        selected = self.resolve(url, provider)
        result = selected.scrape_url(url, enrich=enrich, max_enrich=max_enrich)
        result["provider"] = selected.name
        return result


class JavtifulScraper:
    """Backward-compatible facade around the provider manager."""

    def __init__(self, timeout=30, retries=2):
        self.manager = ProviderManager()
        for provider in self.manager.providers:
            provider.timeout = timeout
            provider.retries = retries
            provider.session.headers.update(provider.HEADERS if hasattr(provider, "HEADERS") else {})

    def scrape(self, url):
        return self.manager.scrape(url)

    def scrape_url(self, url, enrich=False, max_enrich=None, provider=None):
        selected = self.manager.resolve(url, provider)
        selected.timeout = getattr(selected, "timeout", 30)
        return self.manager.scrape(url, provider=provider, enrich=enrich, max_enrich=max_enrich)


def main():
    parser = argparse.ArgumentParser(description="Provider-based metadata scraper")
    parser.add_argument("url", help="Provider URL")
    parser.add_argument("-o", "--output", help="Write JSON result to this file")
    parser.add_argument("--provider", help="Force a provider, e.g. javtiful")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--max-enrich", type=int, default=None)
    parser.add_argument("--page", type=int, default=None)
    args = parser.parse_args()

    manager = ProviderManager()
    provider = manager.resolve(args.url, args.provider)
    provider.timeout = args.timeout
    if args.page:
        parsed = urlparse(args.url)
        path = parsed.path.rstrip("/").lower()
        if path == "/actresses":
            result = provider.scrape_actresses(args.url, args.page)
        elif path == "/channels":
            result = provider.scrape_studios(args.url, args.page)
        else:
            result = provider.scrape_listing(args.url, args.page, enrich=not args.no_enrich, max_enrich=args.max_enrich)
        result["provider"] = provider.name
    else:
        result = manager.scrape(args.url, provider=args.provider, enrich=not args.no_enrich, max_enrich=args.max_enrich)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"Saved: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    raise SystemExit(main())
