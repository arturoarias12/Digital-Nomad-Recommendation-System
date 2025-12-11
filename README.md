# Digital Nomad Recommendation System - Blue Team

**Team: Blue Team**

Members:
- Arturo Arias (aaarias)
- Madison Shen (mshen3)
- Jiafu Wang (jiafuw)
- Jiaqi Xu (jiaqix2)
- Jiaming Zhu (jzhu7)

---

## Executive Summary (read this first)

- What this is: A desktop Tkinter app that ranks cities for American digital nomads by a score that combines visa access, cost of living, and internet speed. One click generates a sorted list, a map, and small dashboards.
- How to run: Open main.py (the single entry point) in VS Code or any IDE; or run from a terminal with Python. On first launch, the app asks whether to download fresh data (slower) or to use local cache (faster and works offline). If the network is slow or scraping fails, choose cache mode. The app can run from previously saved data.
- Dependencies: Install with `pip install -r requirements.txt`. We DO NOT auto-install in code.

-------------------------------------------------------------------------------

## 1) Folder Naming and Contents

- Name your submission folder so it clearly identifies your team, for example: BlueTeam_FinalProject.
- Place all files inside this one folder (no absolute paths, no external directories).

Key files:
- `main.py` — single entry point for the app (Tkinter GUI).
- `dn_recommendations.py` — data pipeline and recommender engine.
- `cost_of_living.py` — scrapes selected Numbeo price metrics with polite pacing.
- `internet_speed.py` — fetches Ookla Speedtest Global Index tables (mobile and fixed).
- `visa_restrictions.py` — scrapes visa category lists for a target passport.
- `requirements.txt` — pinned Python packages to install.
- `world_map.png` — map visual background image.
- Created at runtime: `plans.json` — saved UI plans (stored in project folder).
- Created at runtime (or cached): `combined_<key>_<YYYYMMDD>.csv` — per-day combined dataset cache in the project folder.

-------------------------------------------------------------------------------

## 2) Required Python and Packages

- Python version: Tested on Python 3.11–3.14 (CPython) on Windows and MacOS.
- Install dependencies manually:
  - `pip install -r requirements.txt`
- Packages in requirements.txt (for reference):
  - beautifulsoup4==4.14.2
  - cloudscraper==1.2.71
  - matplotlib==3.10.7
  - numpy==2.3.3
  - pandas==2.3.3
  - requests==2.32.5

This project does not require environment variables or API keys.

-------------------------------------------------------------------------------

## 3) How to Run the Application

Important: Run the program from the project folder so all files (cache and plans.json) stay in this single directory.

### Option A — IDE
1. Open the project folder.
2. Open `main.py`.
3. Run the file.
4. On first launch, choose:
   - Download fresh data now (may take time), or
   - Use local cache only (fast/offline, if a cache CSV is present).

### Option B1 — Terminal (Windows PowerShell example)
- From the project folder:
  - `python .\main.py`

### Option B2 — Terminal (macOS or Linux)
- From the project folder:
  - `python3 main.py`

> Note: This is a Tkinter GUI app. Expect a window to open. The console remains mostly quiet unless `debug` in `dn_recommendations.py` is set to True.

### Virtual Environment

A Virtual Environment is optional, but recommended.

Windows (PowerShell or cmd):
```
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\main.py
deactivate
```

macOS or Linux:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
deactivate
```

-------------------------------------------------------------------------------

## 4) Data Modes (Fresh vs Cache) and Runtime Files

- **Fresh data mode**:
  - Scrapes sources (visa, cost-of-living, internet speed) only if there is no cache file from the same date as today.
  - Builds today’s combined dataset in the project folder:
    - `combined_<key>_<YYYYMMDD>.csv` (example: `combined_default_20251010.csv`)

- **Cache-only mode**:
  - Never scrapes. Loads the latest combined CSV found in the project folder.
  - If none exists, the app provides guidance on creating one once via Fresh mode.

**Saved plans are stored in `plans.json` in this same folder. Delete this file to reset plans.**

This arrangement avoids long blocking scrapes for graders and keeps everything inside one directory.

-------------------------------------------------------------------------------

## 5) File-by-File Summary Overview

### `main.py` — GUI Application (single entry point)
- Tkinter app with pages: Home, Plan Trip, Data Explorer, Saved, Compare, Settings.
- Prompts for Fresh vs Cache mode; reads and writes plans.json.
- Plan Trip renders a ranked Table, a Map with a world background, and small dashboards.
- Data Explorer is a read-only view of the currently loaded combined dataset (from the engine). Supports basic sorting and quick filtering by text (city/country). Useful for spot-checking columns/values without triggering any scraping. Respects Cache-only mode.
- Saved manages saved plans stored in `plans.json` (project folder). Create a plan from current filters, load a plan to repopulate filters, rename plans, and delete plans. Changes persist across sessions.
- Compare lets you choose Plan A and Plan B from your saved plans. Shows side-by-side summaries of each plan’s filters and provides a quick way to re-run recommendations for either plan to review differences in results.
- In Settings, the theme (light/dark/blue) and default region preferences can be defined.

### `dn_recommendations.py` — Data Pipeline and Recommender
- Orchestrates cache-or-scrape logic and writes/reads per-day combined CSVs.
- Merges visa, cost, and speed data; computes `monthly_cost`, `avg_internet_mbps`, and a composite `nomad_score`.

### `cost_of_living.py` — Numbeo Scraper (selected metrics)
- Scrapes a modest set of city-level metrics; politely paced; returns a tidy DataFrame.

### `internet_speed.py` — Speedtest Tables
- Fetches and cleans mobile and fixed internet speed tables; returns DataFrames.

### `visa_restrictions.py` — Visa Lists
- Scrapes visa categories for a target passport; on HTTP 403, optionally falls back to cloudscraper.

-------------------------------------------------------------------------------

## 6) Detailed Function and Class Reference

### `main.py` (Tkinter UI)

#### Top-level state and store
- `APP_DIR`, `PLANS_FILE`: Project-local files in the current working directory.
- `_ensure_app_dir()`: Creates the local app/storage directory if missing.
- `_read_plans_store()` and `_write_plans_store()`: Load/save plans.json atomically.
- `load_all_plans_from_store()`, `save_plan_to_store()`, `delete_plan_from_store()`, `rename_plan_in_store()`: Plan CRUD (Create, Read, Update, Delete) utilities.
- `Plan` (dataclass): id, name, created_at, filters.
- `AppState` (dataclass): theme, default region, saved_plans.

#### Utilities
- `now_iso()`: Current timestamp string.
- `ask_save_path()` and `ask_open_path()`: Standard file dialogs.

#### Top-level UI class
- `class NomadUI(tk.Tk)`: Builds the app window and navigation.
  - `_prompt_for_data_mode()`: Asks user to pick Fresh vs Cache mode; informs engine via `set_cache_only_mode()`.
  - `_create_header()`, `_create_menubar()`, `_create_statusbar()`, `_create_body()`: Compose UI.
  - `show_page(key)`: Switch active page; refresh Compare page choices.
  - Menu actions: `new_plan()`, `file_save_state()`, `file_open_state()`, `export_results_csv()`, `show_help()`, `show_about()`, `on_exit()`.
  - Theme helpers: `toggle_theme()`, `_apply_theme()`.
  - Saved plans load: `_load_plans_from_disk()`.

#### Pages (frames)
- `HomePage`: Welcome and quick links.
- `PlanTripPage`: Filters to Get Recommendations, then renders Table, Map, and Dashboard.
  - `on_get_recs()`: Validate budget; call engine; handle friendly exceptions; fill table; call `_render_map(df)` and `_render_dashboard(df)`.
  - `_months()`, `current_filters()`, `on_save_plan()`, `reset_filters()`.
- `DataExplorerPage`: Simple data browsing helpers.
- `SavedPage`: View and manage saved plans.
- `ComparePage`: Select two saved plans (A and B).
- `SettingsPage`: Theme and region defaults.
- `PromptWindow`: Small prompt dialogs leveraged by the UI.

#### Rendering helpers (excerpts)
- `_render_map(df)`: Draws a world PNG background and overlays points (lon/lat); adds colorbar and labels; handles the no-data case gracefully.
- `_render_dashboard(df)`: Updates top recommendation and small charts (cost, speed, visa composition).

### B) `dn_recommendations.py` (Engine)

#### Public API used by main.py
- `build_recommendations(filters: dict) -> pandas.DataFrame`
  - Orchestrates a full run for the given UI filters; returns a city-ranked DataFrame with columns such as `city`, `country`, `visa_free`, `monthly_cost`, `avg_internet_mbps`, `nomad_score`, and `region`.
- `fetch_visa_data() -> dict`
- `fetch_cost_of_living_data(cities=None) -> pandas.DataFrame`
- `fetch_internet_speed_data() -> tuple of (pandas.DataFrame, pandas.DataFrame)`
- `set_cache_only_mode(flag: bool)` — When true, the engine never scrapes.

#### Error classes
- `NoCachedDataError`
- `CostOfLivingRateLimitError`
- `CostOfLivingFetchError`

#### Caching helpers (project-local)
- `_cache_dir()`, `_today_tag()`, `_combined_csv_path()`, `_extract_tag_from_filename()`
- `_cleanup_old_caches()`, `_df_looks_valid()`
- `_try_read_today()`, `_try_write_today(df)`
- `_find_latest_combined_cache()`, `_try_read_latest_any_day()`

#### ETL and scoring helpers
- `_ensure_region_column(df)`
- `_apply_home_country_visa_override(df, home_country="United States")`
- merge steps that produce a consolidated DataFrame and a nomad_score (higher is better).

#### Daily dataset orchestrator
- `DigitalNomadRecommender.ensure_daily_dataset(cities=None) -> pandas.DataFrame`
  - Tries "today’s" cache; otherwise, behavior depends on mode:
    - cache-only mode: use latest cache (any day) or raise `NoCachedDataError`
    - regular mode: scrape, merge, score; write today’s cache; return DataFrame

### C) `cost_of_living.py` (Numbeo)

#### Public function
- `fetch_cost_of_living(cities=None) -> pandas.DataFrame`
  - Scrapes selected cities and returns a tidy DataFrame with normalized columns.

#### Helpers
- `parse_price(s: str) -> Optional[float]`
- `find_row_value(soup, needles: list[str]) -> Optional[float]`
- `get_city_data(city: str, sleep=0.8, retries=3) -> dict`
  - Polite backoff; returns a dict of metrics and a source field with context or error info.

### D) `internet_speed.py` (Speedtest)

#### Public function
- `fetch_speed_data() -> tuple of (pandas.DataFrame, pandas.DataFrame)`
  - Returns (`mobile_country_df`, `fixed_country_df`); cleans the numeric and delta columns and sets the country index.

### E) `visa_restrictions.py` (VisaIndex)

#### Public functions
- `get_visa_data(url=DEFAULT_VISA_URL) -> dict[str, list[str]]`
  - Top-level convenience wrapper that always returns a dict (empty on failure).
- `scrape_all_visa_info(url: str) -> dict[str, list[str]] or None`
  - Core scraper; attempts requests first; on HTTP 403, best-effort fallback to cloudscraper if installed.

-------------------------------------------------------------------------------

## 7) Expected Inputs and Outputs

### Inputs
- GUI filters: budget, region, minimum Mbps, visa-free toggle, and related options.

### Outputs
- Ranked table: `city`, `country`, `visa_free`, `monthly_cost`, `avg_internet_mbps`, `nomad_score`, `region`.
- Map with plotted candidate cities.
- Small charts (cost, speed, visa composition).
- Plan comparisons.

-------------------------------------------------------------------------------

## 8) Performance, Rate-Limits, and Offline Use

- Web scraping can be slow or rate-limited (for example, HTTP 429). The app:
  - Offers cache-only mode (no downloads).
  - Surfaces friendly messages on typical scraping errors.
- Offline operation: If a combined CSV exists in the project folder, cache-only mode works without internet.

-------------------------------------------------------------------------------

## 9) Notes

- Install dependencies manually using the provided requirements.txt.
- No environment variables or API keys are required.
- If scraping breaks due to site changes, the app still runs in cache-only mode using the latest local CSV.
- HTML on third-party sites can change; if scraping fails, use cache-only mode.
- City coordinates are approximate for visualization and are not intended for precise GIS analysis.
- Scoring is transparent: cost (lower is better), connectivity and visa access (higher is better). Weights can be adjusted in the engine.
- All files are read and written relative to the current working directory (the project folder).
- No external databases or services beyond the listed Python packages.
- No in-code installation of packages (manual pip install -r requirements.txt only).

-------------------------------------------------------------------------------

## 10) Acknowledgments

- Data sources: Numbeo (selected price metrics), Ookla Speedtest Global Index (mobile and fixed tables), and VisaIndex (visa categories). Educational use only.

## 11) AI Appendix

This project was developed with the assistance of artificial intelligence tools, such as ChatGPT, Copilot and Gemini, which were used to enhance productivity and code quality throughout the development process. All AI-generated content was reviewed, tested, and validated manually by the team to ensure correctness, consistency, and compliance with academic integrity guidelines.