from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Common interface every scraping provider must implement."""

    name = "base"

    @abstractmethod
    def scrape_url(self, url, enrich=False, max_enrich=None):
        raise NotImplementedError

    def supports(self, url):
        return False

    def scrape_listing(self, url, page=1, enrich=False, max_enrich=None):
        raise NotImplementedError

    def scrape_actresses(self, url, page=1):
        raise NotImplementedError

    def scrape_studios(self, url, page=1):
        raise NotImplementedError

    def enrich_post(self, url):
        raise NotImplementedError
