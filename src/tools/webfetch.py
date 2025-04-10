# webfetch.py
import utils
from firecrawl import FirecrawlApp
import config

def FetchWebsite(url: str) -> str:
    """
    Fetches the content from a given website URL in Markdown format.

    Args:
        url (str): The URL of the website to fetch.

    Returns:
        str: The Markdown format of the website.
    """
    app = FirecrawlApp(
        api_key=config.FIRECRAWL_API, api_url=config.FIRECRAWL_ENDPOINT
    )
    scrape_result = utils.retry(exceptions=utils.network_errors, ignore_exceptions=utils.ignore_network_error)(utils.FetchLimiter()(app.scrape_url))(
        url,
        params={
            "formats": ["markdown"],
            "waitFor": 15_000,
            "proxy": "stealth",
            "timeout": 30_000,
            "removeBase64Images": True,
        },
    )
    return scrape_result["markdown"]
