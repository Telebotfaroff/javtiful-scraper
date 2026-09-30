from abc import ABC, abstractmethod


class BaseProvider(ABC):
    """Common interface every scraping provider must implement."""

    name = "base"

    @abstractmethod
    def scrape_url(self, url, enrich=False, max_enrich=None):
        raise NotImplementedError

    def supports(self, url):
        return False
