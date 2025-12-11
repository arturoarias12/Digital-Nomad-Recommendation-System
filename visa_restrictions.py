"""
visa_restrictions.py
Team: Blue Team
Members:
  - Arturo Arias (aaarias)
  - Madison Shen (mshen3)
  - Jiafu Wang (jiafuw)
  - Jiaqi Xu (jiaqix2)
  - Jiaming Zhu (jzhu7)

Purpose:
  This module scrapes the country lists grouped by visa categories (e.g., visa-free,
  visa-on-arrival) from a specific page on visaindex.com. By default, it targets the
  United States passport page but can be directed to any compatible page URL.

Imported by: dn_recommendations.py

Imports:
  Standard library: typing, json, re, pathlib
  Third-party: requests, cloudscraper, bs4
"""


from __future__ import annotations
import json
import requests
from bs4 import BeautifulSoup

# Default target: United States passport page.
DEFAULT_VISA_URL = (
    "https://visaindex.com/visa-requirement/united-states-of-america-passport-visa-free-countries-list/"
)

# Default HTTP headers used for the initial request. A realistic User-Agent helps
# avoid simple bot blocks. Accept-Language and Accept are included to mimic a browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://google.com",
    "Connection": "keep-alive",
}


def get_visa_data(url: str = DEFAULT_VISA_URL) -> dict[str, list[str]]:
    """
    Retrieve the full visa dictionary for a given page URL.

    This is a thin wrapper over `scrape_all_visa_info` that guarantees a
    dictionary is returned (empty on failure), preserving existing behavior.

    Args:
        url (str): The visaindex.com page URL to scrape. Defaults to the
            United States passport page.

    Returns:
        dict[str, list[str]]: A mapping from section titles to lists of
            country names. Returns an empty dict if scraping fails.

    Raises:
        None: All exceptions are handled internally in `scrape_all_visa_info`.
    """
    data = scrape_all_visa_info(url)
    # Preserve the original behavior: return {} instead of None on failure.
    return data or {}


def scrape_all_visa_info(url: str) -> dict[str, list[str]] | None:
    """
    Scrape all visa sections and their associated country lists from a page.

    The function fetches the provided URL, attempts to parse the HTML for
    section headers (h2 tags with expected classes), and extracts the following
    sibling container of countries (div.countriesList). Each section title is
    mapped to a list of country names.

    Args:
        url (str): The visaindex.com page URL to scrape.

    Returns:
        dict[str, list[str]] | None:
            A dictionary where keys are section titles and values are lists of
            country names. Returns None if the page cannot be fetched, parsing
            fails, or the expected structure is not found.

    Raises:
        None: Network and parsing issues are handled internally with messages
        printed to stdout to preserve the original side effects.

    Notes:
        - If the server responds with HTTP 403 (Forbidden), the function will
          attempt a best-effort fallback using `cloudscraper` if available.
        - The parsing relies on current site structure: <h2 class="pb-4" or
          "pt-5 pb-4"> followed by a sibling <div class="countriesList">.
          Site changes may require updates to the parsing logic.
    """
    # Use a session for connection pooling and centralized header management.
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    try:
        # Conservative timeout to avoid hanging.
        response = session.get(url, timeout=15)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # On 403, try to bypass Cloudflare with cloudscraper (if installed).
        if response.status_code == 403:
            print("Got 403 Forbidden. Trying to bypass Cloudflare using cloudscraper...")
            try:
                import cloudscraper  # type: ignore
                scraper = cloudscraper.create_scraper()
                response = scraper.get(url)
            except Exception as e2:  # Broad catch preserves original behavior
                print(f"Cloudscraper failed: {e2}")
                return None
        else:
            print(f"HTTP error: {e}")
            return None
    except requests.exceptions.RequestException as e:
        # Handles timeouts, connection errors, etc.
        print(f"Error fetching the URL: {e}")
        return None

    # Parse the HTML document.
    soup = BeautifulSoup(response.text, "html.parser")
    visa_data: dict[str, list[str]] = {}

    # The site uses consistent classes on section headings; search for both variants.
    section_titles = soup.find_all("h2", class_=["pb-4", "pt-5 pb-4"])

    if not section_titles:
        print("No section titles found. The site structure may have changed or JS is required.")
        return None

    # Iterate over each section heading, collect its sibling countries list.
    for title_tag in section_titles:
        title_text = title_tag.text.strip()

        # Typical structure: the <div.countriesList> immediately follows the <h2>.
        countries_container = title_tag.find_next_sibling("div", class_="countriesList")

        # Fallback: in some layouts, the h2 is wrapped; check the parent's next sibling.
        if not countries_container and title_tag.parent:
            countries_container = title_tag.parent.find_next_sibling("div", class_="countriesList")

        if countries_container:
            # Each country name appears inside <span class="country-name"> elements.
            country_spans = countries_container.find_all("span", class_="country-name")
            countries = [span.text.strip() for span in country_spans]
            visa_data[title_text] = countries

    return visa_data


# Test run (preserves original side effects and output format).
if __name__ == "__main__":
    final_visa_dict = get_visa_data()
    if final_visa_dict:
        print("Successfully scraped all visa information:\n")
        print(json.dumps(final_visa_dict, indent=4, ensure_ascii=False))
    else:
        print("No data found or an error occurred.")