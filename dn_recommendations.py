"""
dn_recommendations.py
Team: Blue Team
Members:
  - Arturo Arias (aaarias)
  - Madison Shen (mshen3)
  - Jiafu Wang (jiafuw)
  - Jiaqi Xu (jiaqix2)
  - Jiaming Zhu (jzhu7)

Purpose:
  Core recommendation engine and data pipeline. Loads cached or freshly
  fetched datasets, merges visa, cost-of-living, and internet-speed data,
  applies cleaning/normalization and user filters, and returns ranked
  destination recommendations and helper utilities.

Imported by: main.py

Imports:
  Local modules: cost_of_living, internet_speed, visa_restrictions
  Standard library: datetime, pathlib, typing, re, json
  Third-party: pandas
"""

from datetime import datetime
from pathlib import Path
import pandas as pd
from typing import Dict, List, Optional, Any
import re

from visa_restrictions import get_visa_data
from cost_of_living import fetch_cost_of_living
from internet_speed import fetch_speed_data

# -----------------------------------------------------------------------------
# Debug / logging
# -----------------------------------------------------------------------------
debug = False  # flip to False to silence debug prints

def dprint(*args, **kwargs):
    if debug:
        print(*args, **kwargs)

# -----------------------------------------------------------------------------
# Custom exceptions for COLI fetch issues (main.py shows user-friendly messages)
# -----------------------------------------------------------------------------
class CostOfLivingRateLimitError(Exception):
    """Raised when the cost-of-living source indicates HTTP 429 rate limiting."""


class CostOfLivingFetchError(Exception):
    """Raised when cost-of-living data cannot be fetched for other HTTP reasons."""

# -----------------------------------------------------------------------------
# Cache-only mode (toggled by UI at startup)
# -----------------------------------------------------------------------------
class NoCachedDataError(Exception):
    """Raised when cache-only mode is enabled but no local cache file exists."""

CACHE_ONLY_MODE: bool = False

def set_cache_only_mode(value: bool) -> None:
    """
    Toggle 'cache-only' behavior for this process.

    When True:
      • The engine will NEVER scrape.
      • It will first try today's cache, then fall back to the newest combined_*.csv it finds.
      • If no cache is present, a NoCachedDataError is raised so the UI can explain
        how to proceed.
    """
    global CACHE_ONLY_MODE
    CACHE_ONLY_MODE = bool(value)
    dprint(f"[mode] CACHE_ONLY_MODE={CACHE_ONLY_MODE}")

# -----------------------------------------------------------------------------
# Cache helpers — current working directory, one file per day
# -----------------------------------------------------------------------------
def _cache_dir() -> Path:
    """
    Use the current working directory for cache files.
    Keeping it local simplifies portability and user expectations.
    """
    p = Path.cwd()
    dprint("[cache] Using cache dir:", str(p))
    return p

def _today_tag() -> str:
    """YYYYMMDD tag for 'today' to name/find the per-day cache."""
    tag = datetime.now().strftime("%Y%m%d")
    dprint("[cache] Today tag:", tag)
    return tag

def _combined_csv_path(key: str = "default") -> Path:
    """
    Path to the combined CSV for today. We only keep today's file around.
    Example: combined_default_20251007.csv
    """
    fp = _cache_dir() / f"combined_{key}_{_today_tag()}.csv"
    dprint("[cache] Combined CSV path:", str(fp))
    return fp

def _extract_tag_from_filename(path: Path) -> Optional[str]:
    """
    Given a combined CSV filename, extract the YYYYMMDD tag.
    Expected pattern: combined_<key>_<YYYYMMDD>.csv
    """
    try:
        name = path.name
        if not name.startswith("combined_") or not name.endswith(".csv"):
            return None
        core = name[:-4]  # strip .csv
        tag = core.rsplit("_", 1)[-1]
        if tag.isdigit() and len(tag) == 8:
            return tag
        return None
    except Exception:
        return None

def _cleanup_old_caches(preserve_tag: str) -> None:
    """
    Delete *all* combined_*.csv files in the cache directory that do not have
    the given `preserve_tag`. This guarantees we never keep more than one cache day.
    """
    try:
        cache = _cache_dir()
        for fp in cache.glob("combined_*_*.csv"):
            tag = _extract_tag_from_filename(fp)
            if tag is None:
                continue
            if tag != preserve_tag:  # not today's -> delete
                try:
                    fp.unlink(missing_ok=True)
                    dprint(f"[cache] Deleted old cache: {fp.name}")
                except Exception as e:
                    dprint(f"[cache] Could not delete {fp.name}: {e}")
    except Exception as e:
        dprint("[cache] cleanup error:", repr(e))

_EXPECTED_CACHE_COLS = [
    "city", "country", "visa_free", "monthly_cost", "avg_internet_mbps", "nomad_score"
]

def _df_looks_valid(df: Optional[pd.DataFrame]) -> bool:
    """Basic sanity check for a cached combined dataset."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        dprint("[cache] Validation: DataFrame is None/empty/invalid")
        return False
    # Must include all expected columns
    if not all(c in df.columns for c in _EXPECTED_CACHE_COLS):
        dprint("[cache] Validation: Missing required columns in cache")
        return False
    # Must have at least one non-null city & country
    if df["city"].isna().all() or df["country"].isna().all():
        dprint("[cache] Validation: city/country entirely null")
        return False
    dprint("[cache] Validation: DataFrame looks valid")
    return True

def _try_read_today() -> Optional[pd.DataFrame]:
    """Try reading today's combined CSV; return None if absent/invalid."""
    fp = _combined_csv_path()
    dprint("[cache] Attempting to read cache:", str(fp))
    if not fp.exists():
        dprint("[cache] No cache file for today")
        return None
    try:
        df = pd.read_csv(fp)
        dprint("[cache] Loaded cache with shape", df.shape, "and columns", list(df.columns))
        # be forgiving about dtypes
        if "visa_free" in df.columns:
            try:
                df["visa_free"] = df["visa_free"].astype(bool)
                dprint("[cache] Coerced visa_free dtype to bool")
            except Exception:
                pass
        ok = _df_looks_valid(df)
        dprint("[cache] Cache valid?", ok)
        return df if ok else None
    except Exception as e:
        dprint("[cache] Failed to read cache:", repr(e))
        return None

def _try_write_today(df: pd.DataFrame) -> None:
    """
    Write today's cache CSV and delete caches from other days.
    Never raise; UX should not be blocked by caching issues.
    """
    try:
        tag = _today_tag()
        # First: delete caches from other days
        _cleanup_old_caches(preserve_tag=tag)

        fp = _combined_csv_path()
        df.to_csv(fp, index=False)
        dprint(f"[cache] Wrote cache to {fp} (shape={df.shape})")

        # Second (defensive): ensure again no stale files remain
        _cleanup_old_caches(preserve_tag=tag)
    except Exception as e:
        dprint("[cache] Failed to write cache:", repr(e))
        # swallow

def _find_latest_combined_cache() -> Optional[Path]:
    """Return the newest combined_*.csv in the cache directory, or None."""
    cache = _cache_dir()
    candidates: list[tuple[str, Path]] = []
    for fp in cache.glob("combined_*_*.csv"):
        tag = _extract_tag_from_filename(fp)
        if tag:
            candidates.append((tag, fp))
    if not candidates:
        dprint("[cache] No combined_*_*.csv files found")
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)  # newest tag first
    dprint(f"[cache] Latest cache on disk: {candidates[0][1].name}")
    return candidates[0][1]

def _try_read_latest_any_day() -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Try reading the most recent combined cache (regardless of date).
    Returns (df, tag) or (None, None) if nothing usable exists.
    """
    fp = _find_latest_combined_cache()
    if not fp:
        return None, None
    try:
        df = pd.read_csv(fp)
        if "visa_free" in df.columns:
            try:
                df["visa_free"] = df["visa_free"].astype(bool)
            except Exception:
                pass
        if _df_looks_valid(df):
            return df, _extract_tag_from_filename(fp)
        dprint("[cache] Latest cache failed validation")
        return None, None
    except Exception as e:
        dprint("[cache] Failed to read latest cache:", repr(e))
        return None, None

# -----------------------------------------------------------------------------
# Region normalization and home-country visa override
# -----------------------------------------------------------------------------
REGION_BY_COUNTRY: Dict[str, str] = {
    "Switzerland": "Europe",
    "France": "Europe",
    "Germany": "Europe",
    "Australia": "Oceania",
    "Netherlands": "Europe",
    "South Korea": "Asia",
    "United Arab Emirates": "Asia",
    "Canada": "Americas",
    "Japan": "Asia",
    "United Kingdom": "Europe",
    "United States": "Americas",  # ensure US is Americas
    "Hong Kong": "Asia",
    "Spain": "Europe",
    "South Africa": "Africa",
    "Singapore": "Asia",
    "Czech Republic": "Europe",
    "Czechia": "Europe",
    "Portugal": "Europe",
    "Thailand": "Asia",
    "Mexico": "Americas",
    # Extend as needed…
}

def _ensure_region_column(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a 'region' column exists and is populated from country names."""
    dprint("[region] START ensure_region_column")
    if df is None or "country" not in df.columns:
        dprint("[region] No 'country' column — skipping region enrichment")
        return df

    region_map = dict(REGION_BY_COUNTRY or {})
    for us_alias in ("United States", "United States of America", "USA", "U.S.", "US"):
        region_map.setdefault(us_alias, "Americas")

    if "region" not in df.columns:
        df["region"] = df["country"].map(region_map)
        dprint("[region] Created 'region' from country map")
    else:
        needs = df["region"].isna() | (df["region"].astype(str).str.strip() == "")
        if needs.any():
            dprint("[region] Filling", int(needs.sum()), "missing/blank region values from country map")
            df.loc[needs, "region"] = df.loc[needs, "country"].map(region_map)

    before_na = int(df["region"].isna().sum())
    df["region"] = df["region"].fillna("Other").astype(str).str.strip()
    after_na = int(df["region"].isna().sum())
    dprint(f"[region] fillna Other: before_na={before_na} after_na={after_na}")

    def _canon(s: str) -> str:
        t = s.strip().casefold()
        if "amer" in t:
            return "Americas"
        if "euro" in t:
            return "Europe"
        if "asia" in t:
            return "Asia"
        if "afri" in t:
            return "Africa"
        if "ocea" in t or "austral" in t:
            return "Oceania"
        return s if s else "Other"

    df["region"] = df["region"].map(_canon)
    dprint("[region] DONE ensure_region_column; unique regions:", sorted(df["region"].dropna().unique().tolist()))
    return df

def _apply_home_country_visa_override(df: pd.DataFrame, home_country: str = "United States") -> pd.DataFrame:
    """Ensure home country is considered visa-free (U.S. citizens by default)."""
    if df is None or "country" not in df.columns or "visa_free" not in df.columns:
        return df
    mask = df["country"].astype(str).str.strip().isin([home_country, "United States of America", "USA", "US"])
    if mask.any():
        before_true = int(df.loc[mask, "visa_free"].sum())
        df.loc[mask, "visa_free"] = True
        after_true = int(df.loc[mask, "visa_free"].sum())
        dprint(f"[visa-override] '{home_country}' rows set to visa_free=True (before_true={before_true} after_true={after_true})")
    return df


# -----------------------------------------------------------------------------
# Core recommender
# -----------------------------------------------------------------------------
class DigitalNomadRecommender:
    """
    Main class for the Digital Nomad Recommendation System.
    Builds and caches a combined city-level dataset with:
      city, country, region, cost columns, visa flags, mobile/fixed speeds, avg speed, scores.
    """

    def __init__(self):
        dprint("[init] DigitalNomadRecommender __init__")
        self.visa_dict: Optional[Dict[str, List[str]]] = None
        self.cost_df: Optional[pd.DataFrame] = None
        self.speed_mobile_df: Optional[pd.DataFrame] = None
        self.speed_fixed_df: Optional[pd.DataFrame] = None
        self.combined_data: Optional[pd.DataFrame] = None
        self._cache_tag: Optional[str] = None  # which YYYYMMDD the in-memory data belongs to

    # --------------------- cache-or-scrape orchestrator ---------------------
    def ensure_daily_dataset(self, cities: Optional[List[str]] = None) -> pd.DataFrame:
        """
        If today's combined CSV exists and looks valid -> load and return it.
        Otherwise:
        • When CACHE_ONLY_MODE is False -> scrape now, merge, score, write today's CSV.
        • When CACHE_ONLY_MODE is True  -> NEVER scrape. Try latest cache on disk (any day).
            If none exists, raise NoCachedDataError so the UI can guide the user.
        """
        dprint("[ensure_daily_dataset] START")

        # 1) Try today's cache first (works for both modes)
        cached = _try_read_today()
        if cached is not None:
            cached = _ensure_region_column(cached)
            cached = _apply_home_country_visa_override(cached)
            self.combined_data = cached
            if "nomad_score" not in self.combined_data.columns:
                self.calculate_nomad_score()
            dprint("[ensure_daily_dataset] Using today's cached dataset")
            self._cache_tag = _today_tag()
            return self.combined_data

        # 2) If cache-only mode is on, fall back to *any* latest cache and never scrape
        if CACHE_ONLY_MODE:
            dprint("[ensure_daily_dataset] CACHE_ONLY_MODE=True -> will not scrape")
            latest, tag = _try_read_latest_any_day()
            if latest is None:
                raise NoCachedDataError(
                    "Cache-only mode is enabled but no local cache file was found."
                )
            latest = _ensure_region_column(latest)
            latest = _apply_home_country_visa_override(latest)
            self.combined_data = latest
            if "nomad_score" not in self.combined_data.columns:
                self.calculate_nomad_score()
            self._cache_tag = tag
            dprint(f"[ensure_daily_dataset] Loaded latest available cache (tag={tag})")
            return self.combined_data

        # 3) No cache or invalid -> scrape and build (regular mode)
        dprint("[ensure_daily_dataset] No valid cache -> scraping")
        visa_dict = get_visa_data() or {}
        dprint("[ensure_daily_dataset] Visa dict keys:", list(visa_dict.keys())[:5], "… total:", len(visa_dict))

        cost_df = fetch_cost_of_living(cities=cities)
        if isinstance(cost_df, pd.DataFrame) and "source" in cost_df.columns:
            sources = (cost_df["source"].dropna().astype(str)).tolist()
            joined = " | ".join(sources)
            if "HTTP 429" in joined:
                raise CostOfLivingRateLimitError("Cost of living fetch hit a rate limit (HTTP 429).")
            if "ERROR: HTTP" in joined:
                raise CostOfLivingFetchError("Cost of living fetch failed with an HTTP error.")
        if cost_df is None:
            raise CostOfLivingFetchError("Cost of living fetch returned no data.")

        mobile_country, fixed_country = fetch_speed_data()
        if mobile_country is None:
            mobile_country = pd.DataFrame()
        if fixed_country is None:
            fixed_country = pd.DataFrame()

        # Build pipeline
        self.load_visa_data(visa_dict)
        self.load_cost_data(cost_df)
        self.load_speed_data(mobile_country, fixed_country)
        self.merge_datasets()
        self.calculate_nomad_score()

        # 4) Write today's CSV and delete any old-day caches
        if self.combined_data is not None and not self.combined_data.empty:
            _try_write_today(self.combined_data)

        self._cache_tag = _today_tag()
        dprint("[ensure_daily_dataset] DONE")
        return self.combined_data

    # --------------------- loading individual datasets ---------------------
    def load_visa_data(self, visa_dict: Dict[str, List[str]]):
        """Load visa data from dictionary and transform to a flat DataFrame."""
        dprint("[load_visa_data] START")
        self.visa_dict = visa_dict

        visa_records = []
        for category, countries in visa_dict.items():
            for country in countries:
                visa_records.append({
                    'country': country,
                    'visa_category': category,
                    'visa_free': 'visa-free' in category.lower(),
                    'visa_on_arrival': 'visa on arrival' in category.lower(),
                    'eta_required': 'eta' in category.lower() or 'electronic' in category.lower(),
                    'evisa_required': 'e-visa' in category.lower(),
                    'visa_required': 'requiring visas' in category.lower()
                })

        self.visa_data = pd.DataFrame(visa_records)
        dprint("[load_visa_data] rows=", len(self.visa_data), "cols=", list(self.visa_data.columns))
        return self.visa_data

    def load_cost_data(self, cost_df: pd.DataFrame):
        """Load cost of living data and compute a 'monthly_cost' field."""
        dprint("[load_cost_data] START")
        self.cost_df = cost_df.copy()

        self.cost_df['monthly_cost'] = self.cost_df.apply(
            lambda row: sum([
                row.get('rent_1br_city_center_usd', 0) or 0,
                row.get('utilities_basic_usd', 0) or 0,
                row.get('internet_60mbps_usd', 0) or 0,
                row.get('transport_monthly_pass_usd', 0) or 0,
                row.get('food_estimate_usd', 0) or 0
            ]), axis=1
        )

        dprint("[load_cost_data] rows=", len(self.cost_df), "sample:\n", self.cost_df.head(3))
        return self.cost_df

    def load_speed_data(self, mobile_df: pd.DataFrame, fixed_df: pd.DataFrame):
        """Load internet speed data (mobile & fixed) and standardize column names."""
        dprint("[load_speed_data] START")
        self.speed_mobile_df = mobile_df.copy()
        self.speed_fixed_df = fixed_df.copy()
        self.speed_mobile_df = self.speed_mobile_df.rename(columns={'Mbps': 'mobile_mbps'})
        self.speed_fixed_df = self.speed_fixed_df.rename(columns={'Mbps': 'fixed_mbps'})
        dprint("[load_speed_data] mobile shape=", self.speed_mobile_df.shape, "cols=", list(self.speed_mobile_df.columns))
        dprint("[load_speed_data] fixed  shape=", self.speed_fixed_df.shape, "cols=", list(self.speed_fixed_df.columns))
        return self.speed_mobile_df, self.speed_fixed_df

    # --------------------- merging + scoring ---------------------
    def merge_datasets(self) -> pd.DataFrame:
        """
        Merge all datasets into a unified recommendation database.
        Cost data is city-level; visa + speeds are country-level -> we map cities to countries.
        """
        dprint("[merge_datasets] START")
        base = self.cost_df.copy()

        city_to_country = {
            'Zurich': 'Switzerland', 'Paris': 'France', 'Berlin': 'Germany',
            'Sydney': 'Australia', 'Amsterdam': 'Netherlands', 'Seoul': 'South Korea',
            'Dubai': 'United Arab Emirates', 'Toronto': 'Canada', 'Tokyo': 'Japan',
            'London': 'United Kingdom', 'New York': 'United States',
            'Hong Kong': 'Hong Kong', 'Barcelona': 'Spain',
            'Johannesburg': 'South Africa', 'Singapore': 'Singapore',
            'Prague': 'Czech Republic', 'Lisbon': 'Portugal',
            'Bangkok': 'Thailand', 'Mexico City': 'Mexico'
        }

        dprint("[merge_datasets] base from cost_df shape=", base.shape)
        base['country'] = base['city'].map(city_to_country)
        dprint("[merge_datasets] mapped countries sample:\n", base[['city', 'country']].head())

        # Visa-free flag from visa_dict
        visa_free_countries: set = set()
        if self.visa_dict:
            for key, countries in self.visa_dict.items():
                if 'visa-free' in key.lower():
                    visa_free_countries.update(countries)
        base['visa_free'] = base['country'].isin(visa_free_countries)
        dprint("[merge_datasets] visa_free_countries count:", len(visa_free_countries))
        dprint("[merge_datasets] visa_free True count:", int(base['visa_free'].sum()))

        # Merge with speeds
        if self.speed_mobile_df is not None and not self.speed_mobile_df.empty:
            before = len(base)
            speed_mobile = self.speed_mobile_df.reset_index()[['Country', 'mobile_mbps']]
            base = base.merge(speed_mobile, left_on='country', right_on='Country', how='left')
            base = base.drop('Country', axis=1)
            dprint(f"[merge_datasets] merged mobile: rows_before={before} rows_after={len(base)}")

        if self.speed_fixed_df is not None and not self.speed_fixed_df.empty:
            before = len(base)
            speed_fixed = self.speed_fixed_df.reset_index()[['Country', 'fixed_mbps']]
            base = base.merge(speed_fixed, left_on='country', right_on='Country', how='left')
            base = base.drop('Country', axis=1)
            dprint(f"[merge_datasets] merged fixed: rows_before={before} rows_after={len(base)}")

        # Average speed
        base['avg_internet_mbps'] = base[['mobile_mbps', 'fixed_mbps']].mean(axis=1)
        dprint("[merge_datasets] avg_internet_mbps NaN count:", int(base['avg_internet_mbps'].isna().sum()))

        # Enrich region + apply home-country override
        base = _ensure_region_column(base)
        base = _apply_home_country_visa_override(base)

        self.combined_data = base
        dprint("[merge_datasets] DONE shape=", base.shape, "columns=", list(base.columns))
        return base

    def calculate_nomad_score(self,
                              visa_weight: float = 0.25,
                              cost_weight: float = 0.40,
                              speed_weight: float = 0.35) -> pd.DataFrame:
        """
        Calculate composite nomad score.
        Visa score: 100 if visa-free else 50
        Cost score: Lower cost = higher score (normalized inverse)
        Speed score: Higher speed = higher score (normalized)
        """
        dprint("[calculate_nomad_score] START")
        if self.combined_data is None:
            raise ValueError("Data not merged. Call merge_datasets() first.")

        df = self.combined_data.copy()

        df['visa_score'] = df['visa_free'].apply(lambda x: 100 if bool(x) else 50)

        max_cost = df['monthly_cost'].max()
        min_cost = df['monthly_cost'].min()
        dprint(f"[calculate_nomad_score] cost min={min_cost} max={max_cost}")
        denom_cost = (max_cost - min_cost) if max_cost != min_cost else 1.0
        df['cost_score'] = ((max_cost - df['monthly_cost']) / denom_cost) * 100

        max_speed = df['avg_internet_mbps'].max() if 'avg_internet_mbps' in df.columns else 0
        dprint(f"[calculate_nomad_score] speed max={max_speed}")
        denom_speed = max_speed if max_speed not in (0, None, float('nan')) else 1.0
        df['speed_score'] = (df['avg_internet_mbps'] / denom_speed) * 100

        df['nomad_score'] = (
            df['visa_score'] * visa_weight +
            df['cost_score'] * cost_weight +
            df['speed_score'] * speed_weight
        )

        dprint("[calculate_nomad_score] nomad_score summary:\n", df['nomad_score'].describe())
        self.combined_data = df
        dprint("✓ Calculated nomad scores (weights: visa=", visa_weight, ", cost=", cost_weight, ", speed=", speed_weight, ")")
        dprint("[calculate_nomad_score] DONE")
        return df

    # --------------------- recommendations ---------------------
    def get_recommendations(self,
                            max_budget: float,
                            min_speed: float = 25,
                            visa_free_only: bool = True,
                            top_n: int = 100,
                            region: Optional[str] = None) -> pd.DataFrame:
        """
        Get personalized recommendations. 'Global' region means NO region filtering.
        """
        dprint("[get_recommendations] START max_budget=", max_budget,
               " min_speed=", min_speed, " visa_free_only=", visa_free_only,
               " top_n=", top_n, " region=", region)
        if self.combined_data is None or 'nomad_score' not in self.combined_data.columns:
            raise ValueError("Calculate scores first using calculate_nomad_score()")

        df = self.combined_data.copy()
        dprint("[get_recommendations] initial rows:", len(df))

        filtered = df[df['monthly_cost'] <= max_budget]
        dprint("[get_recommendations] after budget filter:", len(filtered))

        if region and region.strip() and region.strip().lower() != "global":
            if "region" in filtered.columns:
                before = len(filtered)
                target = region.strip().casefold()
                filtered = filtered[filtered["region"].astype(str).str.casefold() == target]
                dprint("[get_recommendations] after region filter:", len(filtered), f"(dropped {before - len(filtered)})")
            else:
                dprint("[get_recommendations] region column missing; skipping region filter")
        else:
            dprint("[get_recommendations] region='Global' or blank -> no region filter applied")

        if min_speed:
            before = len(filtered)
            filtered = filtered[filtered['avg_internet_mbps'] >= float(min_speed)]
            dprint("[get_recommendations] after speed filter:", len(filtered), f"(dropped {before - len(filtered)})")

        if visa_free_only:
            before = len(filtered)
            filtered = filtered[filtered['visa_free'] == True]
            dprint("[get_recommendations] after visa filter:", len(filtered), f"(dropped {before - len(filtered)})")

        recommendations = filtered.nlargest(top_n, 'nomad_score')

        result = recommendations[[
            'city', 'country', 'nomad_score', 'monthly_cost',
            'avg_internet_mbps', 'visa_free', 'rent_1br_city_center_usd',
            'internet_60mbps_usd', 'transport_monthly_pass_usd'
        ]].round(2)

        dprint("[get_recommendations] final count:", len(result))
        dprint("[get_recommendations] DONE")
        return result


# -----------------------------------------------------------------------------
# Module-level singleton so we do not re-scrape on every click
# -----------------------------------------------------------------------------
_RECOMMENDER: Optional[DigitalNomadRecommender] = None

def build_recommender(cities: Optional[List[str]] = None) -> DigitalNomadRecommender:
    """
    Ensure dataset is ready, then return the singleton.

    Regular mode:
      • Reuse in-memory instance if it's tagged for today.
      • Else ensure today's dataset (load cache or scrape once), then clean old caches.

    Cache-only mode:
      • Reuse any in-memory instance regardless of its tag (never scrape).
      • Else load today's cache or the latest available cache on disk (never scrape).
      • Do NOT delete older cache files (they may be the only usable data).
    """
    dprint("[build_recommender] START cities=", cities)
    global _RECOMMENDER
    today = _today_tag()

    # Fast path: reuse an existing in-memory recommender
    if _RECOMMENDER is not None:
        if CACHE_ONLY_MODE:
            dprint("[build_recommender] Reusing in-memory recommender (cache-only mode)")
            return _RECOMMENDER
        if getattr(_RECOMMENDER, "_cache_tag", None) == today:
            dprint("[build_recommender] Reusing in-memory recommender for today")
            return _RECOMMENDER

    # Build/ensure data for this process
    rec = DigitalNomadRecommender()
    rec.ensure_daily_dataset(cities=cities)
    _RECOMMENDER = rec

    # Defensive cleanup only in regular mode (keep older caches in cache-only mode)
    if not CACHE_ONLY_MODE:
        _cleanup_old_caches(preserve_tag=today)

    dprint("[build_recommender] DONE; in-memory recommender set")
    return rec

def get_combined_dataset(cities: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Helper for consumers (like the Data Explorer) that want the latest combined
    dataset but should NOT trigger scraping unless necessary.

    This calls build_recommender() which:
      • returns today's in-memory data if present,
      • otherwise loads today's cache,
      • and only scrapes if today's cache is missing.
    """
    rec = build_recommender(cities=cities)
    if rec.combined_data is None or rec.combined_data.empty:
        # Should not happen, but keep a safe empty DataFrame shape
        columns = [
            "city", "country", "region", "visa_free", "monthly_cost",
            "mobile_mbps", "fixed_mbps", "avg_internet_mbps", "nomad_score"
        ]
        return pd.DataFrame(columns=columns)
    return rec.combined_data.copy()

def recommend(max_budget: float,
              min_speed: float = 25,
              visa_free_only: bool = True,
              top_n: int = 100,
              cities: Optional[List[str]] = None,
              region: Optional[str] = None) -> pd.DataFrame:
    """One-shot helper that returns a top-N recommendations table."""
    dprint("[recommend] START max_budget=", max_budget, " min_speed=", min_speed,
           " visa_free_only=", visa_free_only, " top_n=", top_n, " cities=", cities, " region=", region)
    rec = build_recommender(cities=cities)
    out = rec.get_recommendations(
        max_budget=max_budget,
        min_speed=min_speed,
        visa_free_only=visa_free_only,
        top_n=top_n,
        region=region,
    )
    dprint("[recommend] DONE shape:", out.shape)
    return out


# -----------------------------------------------------------------------------
# UI-facing helpers
# -----------------------------------------------------------------------------
def _normalize_budget(value) -> float:
    """Return a float USD amount from a possibly messy user input."""
    dprint("[_normalize_budget] raw value:", repr(value))
    if isinstance(value, (int, float)):
        try:
            out = float(value)
            dprint("[_normalize_budget] parsed:", out)
            return out
        except Exception:
            dprint("[_normalize_budget] parse failed for numeric")
            return 0.0

    s = str(value).strip()
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        out = float(s) if s else 0.0
        dprint("[_normalize_budget] parsed:", out)
        return out
    except Exception:
        dprint("[_normalize_budget] parse failed for string")
        return 0.0

def build_recommendations(filters: Dict[str, Any]) -> Optional[pd.DataFrame]:
    """Build a recommendations table from UI filters."""
    dprint("[build_recommendations] START filters:", filters)

    budget = _normalize_budget(filters.get("budget", ""))
    if budget <= 0:
        dprint("[build_recommendations] Invalid budget -> returning None")
        return None

    try:
        min_downlink = float(filters.get("min_downlink", 25) or 25)
    except Exception:
        min_downlink = 25.0

    visa_only = bool(filters.get("visa_free_only", True))
    region = (filters.get("region") or "").strip()

    dprint("[build_recommendations] Parsed params: budget=", budget,
           " min_downlink=", min_downlink, " visa_only=", visa_only, " region=", repr(region))

    try:
        df = recommend(
            max_budget=budget,
            min_speed=min_downlink,
            visa_free_only=visa_only,
            top_n=100,             # UI table shows up to 10
            region=region,
        )
        expected = ["city", "country", "visa_free", "monthly_cost", "avg_internet_mbps", "nomad_score"]
        dprint("[build_recommendations] recommend() returned shape:", df.shape, "cols:", list(df.columns))
        if not all(c in df.columns for c in expected):
            dprint("[build_recommendations] reindexing to expected columns")
            return df.reindex(columns=expected)
        dprint("[build_recommendations] DONE")
        return df
    except (CostOfLivingRateLimitError, CostOfLivingFetchError):
        raise
    except Exception as e:
        dprint("build_recommendations error:", repr(e))
        return pd.DataFrame(
            columns=["city", "country", "visa_free", "monthly_cost", "avg_internet_mbps", "nomad_score"]
        )

# -----------------------------------------------------------------------------
# Data Explorer passthroughs (cache-first; no direct scraping)
# -----------------------------------------------------------------------------
def fetch_visa_data(query: Optional[str] = None):
    """
    Keep visa rules as-is (this may scrape when ensure_daily_dataset decides to).
    If you want to also route visa through the combined cache, we can extend this,
    but your requirement was specifically for Cost of Living + Internet Speed.
    """
    # We still prefer to go through the daily pipeline to avoid redundant scrapes
    # unless the cache is missing today.
    rec = build_recommender()
    # Return the raw visa_dict if available; else fall back to scraper (rare)
    if getattr(rec, "visa_dict", None):
        return rec.visa_dict
    return get_visa_data()

def fetch_cost_of_living_data(query: Optional[str] = None) -> pd.DataFrame:
    """
    Return Cost of Living rows from the COMBINED CACHE (no direct scraping here).
    If today's cache is missing, ensure_daily_dataset() will scrape ONCE and build it.
    """
    dprint("[DataExplorer] fetch_cost_of_living_data (cache-first)")
    df = get_combined_dataset()
    cols = [
        "city",
        "rent_1br_city_center_usd",
        "utilities_basic_usd",
        "internet_60mbps_usd",
        "transport_monthly_pass_usd",
        "food_estimate_usd",
        "monthly_cost",
    ]
    # Some caches include the original 'source' column — keep it if present.
    if "source" in df.columns:
        cols.append("source")
    present = [c for c in cols if c in df.columns]
    out = df[present].copy()

    # Optional: apply a quick 'city contains' filter if query passed
    q = (query or "").strip().lower()
    if q and "city" in out.columns:
        out = out[out["city"].astype(str).str.lower().str.contains(q)]
    dprint("[DataExplorer] COLI rows returned:", len(out))
    return out.reset_index(drop=True)

def fetch_internet_speed_data(query: Optional[str] = None):
    """
    Return (mobile_df, fixed_df) by aggregating from the COMBINED CACHE (no direct scraping).
    If today's cache is missing, ensure_daily_dataset() will scrape ONCE and build it.
    """
    dprint("[DataExplorer] fetch_internet_speed_data (cache-first)")
    df = get_combined_dataset()
    # Derive country-level speeds by mean; ignore NaNs
    mobile = (
        df.groupby("country", dropna=True)["mobile_mbps"]
        .mean(numeric_only=True)
        .reset_index()
        .rename(columns={"country": "Country"})
    )
    fixed = (
        df.groupby("country", dropna=True)["fixed_mbps"]
        .mean(numeric_only=True)
        .reset_index()
        .rename(columns={"country": "Country"})
    )

    # Optional: apply country filter here as well
    q = (query or "").strip().lower()
    if q:
        if "Country" in mobile.columns:
            mobile = mobile[mobile["Country"].astype(str).str.lower().str.contains(q)]
        if "Country" in fixed.columns:
            fixed = fixed[fixed["Country"].astype(str).str.lower().str.contains(q)]

    # Sort for nicer display
    if "Country" in mobile.columns:
        mobile = mobile.sort_values("Country").reset_index(drop=True)
    if "Country" in fixed.columns:
        fixed = fixed.sort_values("Country").reset_index(drop=True)

    dprint("[DataExplorer] Speed rows returned: mobile=", len(mobile), " fixed=", len(fixed))
    return mobile, fixed

# -----------------------------------------------------------------------------
# Example usage (keep commented when used as a module)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Digital Nomad Recommendation System - Engine (debug run)")
    print("=" * 70)
    # Quick self-check: ensure dataset and show a small sample
    rec = build_recommender()
    data = rec.combined_data
    if data is not None:
        print("Combined rows:", len(data))
        print(data.head(5).to_string(index=False))
    else:
        print("No data available.")