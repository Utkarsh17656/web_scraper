from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import uvicorn
import asyncio
import sys
import logging
from typing import Optional, List, Dict, Any

from scraper_engine import scrape_dynamic_page, fetch_tender_details_dict, export_tender_details_csv, export_all_tenders_with_details_csv

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


class TenderData(BaseModel):
    title: str
    ref: str
    closing: str
    opening: str
    link: str
    url: Optional[str] = None


class BulkExportRequest(BaseModel):
    tenders: List[Dict[str, Any]]  # List of tender objects with basic info


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


@app.get("/api/export-tender")
async def export_tender_api(url: str):
    try:
        csv_content = await export_tender_details_csv(url)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="tender_details.csv"'}
        )
    except Exception as e:
        logger.error(f"Export API Error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/export-bulk")
async def export_bulk_api(request: BulkExportRequest):
    """
    Exports all tenders with enriched details fetched from each tender URL.
    This provides comprehensive tender information in a single CSV file.
    """
    try:
        if not request.tenders or len(request.tenders) == 0:
            return JSONResponse(
                content={"error": "No tenders provided for export"},
                status_code=400
            )
        
        logger.info(f"Starting bulk export for {len(request.tenders)} tenders...")
        csv_content = await export_all_tenders_with_details_csv(request.tenders)
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="tender_results_with_details.csv"'}
        )
    except Exception as e:
        logger.error(f"Bulk Export API Error: {e}", exc_info=True)
@app.get("/api/tender-details")
async def tender_details_api(url: str):
    """
    Fetches detailed tender information AS JSON.
    This enables the frontend to enrich CSV exports on-demand.
    """
    try:
        details = await fetch_tender_details_dict(url)
        return JSONResponse(content=details)
    except Exception as e:
        logger.error(f"Tender Details API Error: {e}")
        return JSONResponse(content={"_error": str(e)}, status_code=500)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
