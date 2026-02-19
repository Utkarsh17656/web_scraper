from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import asyncio
from scraper_engine import scrape_dynamic_page

import sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Verify policy application
if sys.platform == 'win32' and not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsProactorEventLoopPolicy):
    logger.warning("Event loop policy was not set correctly!")
else:
    print(f"Event Loop Policy: {type(asyncio.get_event_loop_policy()).__name__}")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

from typing import Optional

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
        # Check policy at runtime
        if sys.platform == 'win32':
             policy = asyncio.get_event_loop_policy()
             print(f"Active Policy: {type(policy).__name__}")
             
        data = await scrape_dynamic_page(
            request.url, 
            search_keyword=request.search_keyword, 
            max_depth=request.max_depth
        )
        return JSONResponse(content=data)
    except Exception:
        import traceback
        error_msg = traceback.format_exc()
        print(f"API Error: {error_msg}")
        return JSONResponse(content={"error": error_msg}, status_code=500)

if __name__ == "__main__":
    # Reload must be False on Windows to support ProactorEventLoopPolicy with Playwright
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
