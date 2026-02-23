from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn
import asyncio
import sys
import logging
from typing import Optional

from scraper_engine import scrape_dynamic_page

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    print(f"Event Loop Policy: {type(asyncio.get_event_loop_policy()).__name__}")

app = FastAPI(title="DataExtractor Pro", description="Advanced Web Scraper for Government & Modern Sites")
templates = Jinja2Templates(directory="templates")


class ScrapeRequest(BaseModel):
    url: str
    search_keyword: Optional[str] = None
    max_depth: int = 1


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/scrape")
async def scrape_api(request: ScrapeRequest):
    try:
        data = await scrape_dynamic_page(
            request.url,
            search_keyword=request.search_keyword,
            max_depth=request.max_depth
        )
        return JSONResponse(content=data)
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        logger.error(f"API Error: {error_msg}")
        return JSONResponse(content={"error": error_msg}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
