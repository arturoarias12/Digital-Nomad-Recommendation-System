"""
internet_speed.py
Team: Blue Team
Members:
  - Arturo Arias (aaarias)
  - Madison Shen (mshen3)
  - Jiafu Wang (jiafuw)
  - Jiaqi Xu (jiaqix2)
  - Jiaming Zhu (jzhu7)

Purpose:
  This module fetches country-level mobile and fixed broadband speed data from
  Ookla's Speedtest Global Index webpage and provides a tiny command-line demo
  that prints the first few rows of each table. It can be imported by other
  analysis scripts or notebooks that need quick access to the latest country
  rankings and metrics.

Imported by: dn_recommendations.py

Imports:
  Standard library: typing, json, pathlib, time
  Third-party: pandas, requests
"""


from __future__ import annotations
import pandas as pd
import requests

# Source page that contains the data tables rendered as HTML.
url = "https://www.speedtest.net/global-index"

# A realistic User-Agent helps prevent basic bot blocking from the host.
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/117.0.0.0 Safari/537.36"
    )
}


def fetch_speed_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch and parse Speedtest Global Index country tables.

    This function downloads the Speedtest Global Index page, extracts the
    relevant HTML tables, and returns two cleaned DataFrames for mobile and
    fixed broadband country metrics. The logic preserves column positions and
    naming semantics used by the source page at the time this code was written.

    Args:
        None

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]:
            A two-tuple of DataFrames in the order:
            (mobile_country_df, fixed_country_df).
            - Index: Country name (unnamed index).
            - Includes a "rank_change" column mapped from the source column
              named "#.1".

    Raises:
        requests.HTTPError: If the HTTP request fails (non-2xx status).
        ValueError: If the expected HTML tables are not present or cannot be
            parsed by `pandas.read_html`.

    Notes:
        - The function relies on global variables `url` and `headers`.
        - The specific table indices (2 for mobile, 4 for fixed) reflect the
          structure of the page at the time of implementation. If the page
          layout changes, these indices may need updating.
    """
    # Retrieve the HTML for the Speedtest Global Index page.
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    # Parse all HTML tables present on the page.
    tables = pd.read_html(response.text)

    # Based on empirical inspection of the page structure:
    # - tables[2]: Mobile country-level table
    # - tables[4]: Fixed broadband country-level table
    mobile_country = tables[2]
    fixed_country = tables[4]

    # Normalize: use the first column as the index (country) and drop rows
    # that are entirely NA (some pages may include trailing empty rows).
    # Also, rename the "#.1" column (rank delta) to a clearer "rank_change".
    mobile_country = (
        mobile_country.set_index(mobile_country.columns[0]).dropna().rename(columns={"#.1": "rank_change"})
    )
    fixed_country = (
        fixed_country.set_index(fixed_country.columns[0]).dropna().rename(columns={"#.1": "rank_change"})
    )

    # Remove the index name to match the original behavior and keep output tidy.
    mobile_country.index.name = None
    fixed_country.index.name = None

    return mobile_country, fixed_country


# Simple CLI demo that mirrors the original behavior: fetch and print the heads.
if __name__ == "__main__":
    mobile_country_df, fixed_country_df = fetch_speed_data()

    # Print the first few rows of each table in a readable, aligned format.
    # `.to_string()` ensures consistent console formatting without truncation.
    print(mobile_country_df.head().to_string())
    print(fixed_country_df.head().to_string())