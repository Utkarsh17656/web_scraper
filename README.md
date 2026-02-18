# Advanced Web Scraper Tool

A powerful, dynamic web scraping tool designed for modern websites and government portals. It handles JavaScript rendering, captures metadata, and presents data in a beautiful interface.

## Features
- **Dynamic Scraping**: Uses Playwright (headless Chromium) to render JavaScript-heavy sites.
- **Smart Waiting**: Automatically waits for network idle to ensure full page load.
- **Data Extraction**: Extracts title, description, content length, text snippets, and links.
- **Modern UI**: Clean, responsive interface with real-time feedback.
- **API Access**: Includes a JSON API for programmatic access.

## Setup & Running

1. **Install Dependencies**:
   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Run the Tool**:
   - Double-click `run_scraper.bat`
   - OR run: `python main.py`

3. **Access**:
   Open [http://localhost:8000](http://localhost:8000) in your browser.

## API Usage

Send a POST request to `/api/scrape`:

```json
POST /api/scrape
Content-Type: application/json

{
    "url": "https://example.gov.in"
}
```

Response:
```json
{
    "url": "https://example.gov.in",
    "title": "Example Domain",
    "description": "...",
    ...
}
```

## Technologies
- **Backend**: Python, FastAPI
- **Scraping**: Playwright, BeautifulSoup4
- **Frontend**: HTML5, Modern CSS, Vanilla JavaScript
