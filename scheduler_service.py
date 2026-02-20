import asyncio
import hashlib
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from database import SessionLocal, init_db
from models import Alert, ScrapedTender
from scraper_engine import scrape_dynamic_page
from notifier import send_update_email
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

def generate_tender_hash(title, url):
    """Generates a unique hash for a tender to avoid duplicates."""
    return hashlib.sha256(f"{title}{url}".encode()).hexdigest()

async def run_alert_task(alert_id: int):
    """
    Background task that runs the scraper for a specific alert.
    """
    db = SessionLocal()
    try:
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert:
            return

        logger.info(f"Running background scan for Alert {alert_id} (Keyword: {alert.keyword})")
        
        # Run the scraper
        result = await scrape_dynamic_page(alert.url, search_keyword=alert.keyword, max_depth=alert.max_depth)
        
        if "pages" not in result:
            return

        new_tenders_to_notify = []
        
        for page in result["pages"]:
            for table in page.get("extracted_tables", []):
                for row in table.get("data", []):
                    # Find any column that looks like a title
                    title = next((val for key, val in row.items() if any(k in key.lower() for k in ['title', 'desc', 'subject']) and key != '_links'), "Unknown Tender")
                    
                    # Find the first link in the row
                    links = row.get("_links", {})
                    first_link = next(iter(links.values()), None)
                    link_url = first_link["url"] if isinstance(first_link, dict) else first_link
                    
                    if not link_url:
                        continue
                        
                    t_hash = generate_tender_hash(title, link_url)
                    
                    # Check if we already know this tender
                    exists = db.query(ScrapedTender).filter(ScrapedTender.tender_hash == t_hash).first()
                    if not exists:
                        new_tender = ScrapedTender(
                            alert_id=alert.id,
                            tender_hash=t_hash,
                            tender_title=title,
                            found_url=link_url
                        )
                        db.add(new_tender)
                        new_tenders_to_notify.append({"title": title, "url": link_url})
        
        db.commit()

        if new_tenders_to_notify:
            logger.info(f"Fount {len(new_tenders_to_notify)} new tenders! Sending email to {alert.email}")
            send_update_email(alert.email, alert.keyword, new_tenders_to_notify)
            
    except Exception as e:
        logger.error(f"Error in background alert task: {str(e)}")
    finally:
        db.close()

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Background Alert Scheduler started.")

def add_alert_to_scheduler(alert_id: int):
    # Run every 6 hours
    scheduler.add_job(
        run_alert_task, 
        'interval', 
        hours=6, 
        args=[alert_id], 
        id=f"alert_{alert_id}",
        replace_existing=True
    )
    logger.info(f"Scheduled alert {alert_id} for every 6 hours.")
