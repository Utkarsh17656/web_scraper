# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

DataExtractor Pro — a web scraper targeting JavaScript-heavy sites (primarily Indian government tender portals like etenders.gov.in). It uses Playwright with stealth mode to render pages, extract table data, and export results as CSV. The frontend is a single-page Jinja2 template served by FastAPI.

## Build & Run

```powershell
# Setup (Windows)
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# Run locally (serves on http://127.0.0.1:8001)
python main.py

# Quick start (Windows batch)
.\run_scraper.bat

# Manual integration test against etenders.gov.in
python test_fetch.py
```

There is no formal test suite or linter configured. `test_fetch.py` is a manual Playwright script that navigates the live etenders portal and saves debug HTML files.

## Docker / Deployment

Built on `mcr.microsoft.com/playwright/python:v1.49.0-jammy`. Deployed to Render via `render.yaml`. The container listens on `$PORT` (default 10000). See `DEPLOY_INSTRUCTIONS.md` for Render-specific gotchas (geo-blocking of .gov.in sites, memory limits on free tier).

## Architecture

### Request flow

1. **`main.py`** — FastAPI app. Defines three API endpoints (`POST /api/scrape`, `GET /api/export-tender`, `POST /api/export-bulk`) and serves the Jinja2 frontend at `/`. Pydantic models for request validation live here (`ScrapeRequest`, `TenderData`, `BulkExportRequest`). Sets `WindowsProactorEventLoopPolicy` on Windows.

2. **`scraper_engine.py`** — All scraping logic. Three public async functions:
   - `scrape_dynamic_page(url, search_keyword, max_depth)` — Recursive crawler. Launches a persistent Chromium context (`user_data/` dir), applies `playwright-stealth`, simulates human scrolling/delays, optionally types into on-page search boxes, then extracts tables via BeautifulSoup. Filters results by keyword relevance and ranks by score.
   - `export_tender_details_csv(url)` — Visits a single tender page, extracts label-value pairs from tables, returns CSV string.
   - `export_all_tenders_with_details_csv(tender_data_list)` — Iterates a list of tenders, visits each URL to enrich with detail fields, returns combined CSV.

3. **`templates/index.html`** — Main UI. Vanilla JS frontend that calls `/api/scrape`, renders extracted tables, and offers per-tender and bulk CSV export via the export endpoints. `templates/admin.html` is a dashboard stub that fetches from `/api/alerts` and `/api/admin/history` (endpoints not yet implemented in `main.py`).

4. **`database.py` / `models.py`** — SQLAlchemy setup pointing at MySQL (`MYSQL_URL` env var). Models are currently placeholder — the DB layer is not actively used by any endpoint.

### Key design patterns

- **Persistent browser context**: `launch_persistent_context(user_data_dir=...)` reuses cookies/sessions across scrapes to avoid re-authentication and reduce CAPTCHA triggers.
- **Stealth + human simulation**: `playwright-stealth` patches navigator properties; `human_like_wait()` and `human_scroll()` add randomized delays and scroll events.
- **Keyword-driven relevance scoring**: Pages and table rows are scored by keyword match; results are sorted by `relevance_score` descending.
- **Priority link crawling**: When `max_depth > 1`, links containing tender/procurement keywords are followed first, capped at 15 links per page.
- **Layout junk filtering**: Tables containing known boilerplate strings (e.g., "screen reader", "nic chat") are skipped during extraction.

### Important caveats

- The `admin.html` template references API endpoints (`/api/alerts`, `/api/admin/history`) that do not exist in `main.py` — these will 404.
- `database.py` defaults to a local MySQL connection string. The DB is not used by any current route but will fail to import if MySQL is unavailable and `models.py`/`database.py` are imported directly.
- The `user_data/` directory stores persistent Chromium profile data and should not be committed.
