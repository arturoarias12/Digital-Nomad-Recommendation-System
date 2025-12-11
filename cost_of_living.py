#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cost_of_living.py
Team: Blue Team
Members:
  - Arturo Arias (aaarias)
  - Madison Shen (mshen3)
  - Jiafu Wang (jiafuw)
  - Jiaqi Xu (jiaqix2)
  - Jiaming Zhu (jzhu7)

Purpose:
  This module scrapes a subset of cost-of-living metrics for a list of cities
  from Numbeo and returns them as a tidy pandas DataFrame. It can be executed
  as a script or imported by other analysis code (e.g., ETL jobs, notebooks,
  or reporting utilities) that need a quick, lightweight snapshot of selected
  prices by city. The scraper requests Numbeo pages using a desktop User-Agent
  and forces display currency to USD to simplify parsing.

Imported by: dn_recommendations.py

Imports:
  Third-party (if installed): requests, bs4, pandas
  Standard library: typing, re, time, json, pathlib
"""
import time
import re
from typing import Dict, List, Optional

import requests
import pandas as pd
from bs4 import BeautifulSoup

# HTTP request headers used to mimic a standard desktop browser.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/118.0 Safari/537.36"
    )
}

# Default set of cities scraped when the module is run as a script.
DEFAULT_CITIES = [
    "Zurich",
    "Paris",
    "Berlin",
    "Sydney",
    "Amsterdam",
    "Seoul",
    "Dubai",
    "Toronto",
    "Tokyo",
    "London",
    "New York",
    "Hong Kong",
    "Barcelona",
    "Johannesburg",
    "Singapore",
    "Prague",
    "Lisbon",
    "Bangkok",
    "Mexico City",
]

# Numbeo city page template. We force USD to simplify numeric parsing.
URL_TPL = "https://www.numbeo.com/cost-of-living/in/{city}?displayCurrency=USD"

# Compiled regex used to extract the first numeric token from a string.
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def parse_price(s: str) -> Optional[float]:
    """
    Extract the first numeric token from a price string and return it as float.

    Handles common thousands separators (e.g., commas) and gracefully returns
    None when parsing fails.

    Args:
        s: Raw text containing a price (e.g., "$1,234.56").

    Returns:
        A float representing the first parsed numeric value, or None if the
        string does not contain a parseable number.

    Raises:
        None.
    """
    if not s:
        return None

    # Remove common thousands separators before regex extraction.
    s = s.replace(",", "")
    match = _NUM_RE.search(s)
    if not match:
        return None

    try:
        return float(match.group(0))
    except Exception:
        # On any conversion issue, return None to keep the pipeline resilient.
        return None


def find_row_value(soup: BeautifulSoup, needles: List[str]) -> Optional[float]:
    """
    Locate a table row whose first cell contains all given keywords, and
    parse the numeric value from the second cell.

    The function scans table rows on the Numbeo page, matching on a
    case-insensitive label in the leftmost column.

    Args:
        soup: Parsed BeautifulSoup HTML of a Numbeo cost-of-living page.
        needles: Keywords that must all appear in the left cell text.
                 Example: ["apartment", "1 bedroom", "city"]

    Returns:
        The parsed numeric value from the second cell if found, else None.

    Raises:
        None.
    """
    # Iterate all table rows; Numbeo pages contain several tables.
    for tr in soup.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        # Normalize label text for robust substring matching.
        label = (tds[0].get_text(strip=True) or "").lower()

        # Require all keywords to appear in the label.
        if all(kw.lower() in label for kw in needles):
            value_text = tds[1].get_text(strip=True)
            value = parse_price(value_text)
            if value is not None:
                return value

    return None


def get_city_data(city: str, sleep: float = 0.8, retries: int = 3) -> Dict[str, Optional[float]]:
    """
    Scrape selected price metrics for a single city from Numbeo.

    Implements simple retry logic with exponential backoff and an optional
    fixed sleep after a successful request (to be polite to the site and to
    avoid rate-limiting).

    Metrics extracted:
        - Rent (1BR apartment in city center)
        - Utilities (basic 85 m^2)
        - Internet (60 Mbps, unlimited)
        - Transport (monthly pass)
        - Approximate "food basket" estimate (heuristic)

    Args:
        city: City name as displayed by Numbeo (e.g., "New York").
        sleep: Fixed number of seconds to sleep after a successful scrape.
        retries: Number of HTTP attempts before giving up.

    Returns:
        A dictionary with the following keys:
            - city
            - rent_1br_city_center_usd
            - utilities_basic_usd
            - internet_60mbps_usd
            - transport_monthly_pass_usd
            - food_estimate_usd
            - source  (URL or error metadata)

    Raises:
        None. All network/parse errors are caught and summarized in `source`.
    """
    url = URL_TPL.format(city=city.replace(" ", "-"))
    last_err: Optional[str] = None

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")

                # Individual item lookups rely on keywords present in the left cell.
                rent = find_row_value(soup, ["apartment", "1 bedroom", "city"])
                utilities = find_row_value(soup, ["utilities", "85"])
                internet = find_row_value(soup, ["internet", "60"])
                transport = find_row_value(soup, ["monthly", "pass"])
                milk = find_row_value(soup, ["milk", "1 liter"])
                bread = find_row_value(soup, ["bread", "500"])
                rice = find_row_value(soup, ["rice", "1kg"])
                eggs = find_row_value(soup, ["eggs", "12"])
                chicken = find_row_value(soup, ["chicken", "1kg"])
                apples = find_row_value(soup, ["apples", "1kg"])

                # ------------------------------------------------------------------
                # Heuristic "food basket" estimate:
                # - Pairs item price with an assumed monthly quantity.
                # - Uses only items that were successfully parsed.
                # - If at least 3 items are available, scale subtotal to a 6-item
                #   basket by multiplying by (6 / used), then round to cents.
                #   This preserves the original behavior while smoothing sparsity.
                # ------------------------------------------------------------------
                food: Optional[float] = None
                basket_pairs = [
                    (milk, 8),
                    (bread, 8),
                    (rice, 3),
                    (eggs, 2),
                    (chicken, 3),
                    (apples, 4),
                ]

                used = 0
                subtotal = 0.0
                for price, qty in basket_pairs:
                    if isinstance(price, (int, float)):
                        used += 1
                        subtotal += price * qty

                if used >= 3:
                    food = round(subtotal * (6 / used), 2)

                data = dict(
                    city=city,
                    rent_1br_city_center_usd=rent,
                    utilities_basic_usd=utilities,
                    internet_60mbps_usd=internet,
                    transport_monthly_pass_usd=transport,
                    food_estimate_usd=food,
                    source=url,
                )

                # Polite fixed delay after a successful request.
                time.sleep(sleep)
                return data

            # Non-200 responses are treated as transient errors and retried.
            last_err = f"HTTP {resp.status_code}"

        except Exception as exc:
            # Capture the last exception message for diagnostics in the result.
            last_err = str(exc)

        # Exponential backoff between attempts: 0.5, 1.0, 2.0, ...
        time.sleep(0.5 * (2 ** attempt))

    # If all attempts fail, return a structured error row with None values.
    return dict(
        city=city,
        rent_1br_city_center_usd=None,
        utilities_basic_usd=None,
        internet_60mbps_usd=None,
        transport_monthly_pass_usd=None,
        food_estimate_usd=None,
        source=f"ERROR: {last_err} @ {url}",
    )


def fetch_cost_of_living(cities: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Scrape Numbeo for a list of cities and return a tidy DataFrame.

    Prints basic progress to stdout as it iterates over cities, preserving the
    original user-visible side-effect.

    Args:
        cities: Optional list of city names. When omitted, falls back to
                DEFAULT_CITIES.

    Returns:
        A pandas DataFrame with one row per city and the columns documented
        in `get_city_data`.

    Raises:
        None.
    """
    target_cities = list(cities or DEFAULT_CITIES)
    rows: List[Dict[str, Optional[float]]] = []

    for city in target_cities:
        # Progress update mirrors the original behavior.
        print(f"Scraping {city} ...")
        rows.append(get_city_data(city))

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Script entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    df = fetch_cost_of_living()
    # Display a small preview without the index to match the original output style.
    print(df.head().to_string(index=False))
