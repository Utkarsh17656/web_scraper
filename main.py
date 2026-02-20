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

from database import init_db, SessionLocal
from scheduler_service import start_scheduler, add_alert_to_scheduler
from models import Alert
from sqlalchemy.orm import Session
from fastapi import Depends

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Startup event to initialize DB and Scheduler
@app.on_event("startup")
def startup_event():
    try:
        init_db()
        start_scheduler()
        # Resume existing alerts from DB
        db = SessionLocal()
        alerts = db.query(Alert).all()
        for alert in alerts:
            add_alert_to_scheduler(alert.id)
        db.close()
    except Exception as e:
        print(f"Startup Error: {e}")

# Dependency for database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

class AlertCreate(BaseModel):
    email: str
    keyword: str
    url: str
    max_depth: int = 1

@app.post("/api/alerts")
async def create_alert(alert_data: AlertCreate, db: Session = Depends(get_db)):
    try:
        new_alert = Alert(
            email=alert_data.email,
            keyword=alert_data.keyword,
            url=alert_data.url,
            max_depth=alert_data.max_depth
        )
        db.add(new_alert)
        db.commit()
        db.refresh(new_alert)
        
        # Add to background scheduler
        add_alert_to_scheduler(new_alert.id)
        
        return {"status": "success", "alert_id": new_alert.id, "message": "Alert created and scheduled!"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/alerts")
async def list_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).all()
    return alerts

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if alert:
        db.delete(alert)
        db.commit()
        return {"status": "success", "message": "Alert deleted"}
    return JSONResponse(content={"error": "Alert not found"}, status_code=404)

if __name__ == "__main__":
    # Reload must be False on Windows to support ProactorEventLoopPolicy with Playwright
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=False)
