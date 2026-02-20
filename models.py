from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

class Alert(Base):
    __tablename__ = 'alerts'
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    keyword = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    max_depth = Column(Integer, default=2)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationship to track tenders found for this alert
    found_tenders = relationship("ScrapedTender", back_populates="alert", cascade="all, delete-orphan")

class ScrapedTender(Base):
    __tablename__ = 'scraped_tenders'
    
    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey('alerts.id'))
    tender_hash = Column(String(64), unique=True, index=True) # Unique ID for the tender row to prevent duplicates
    tender_title = Column(Text)
    found_url = Column(String(500))
    found_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    alert = relationship("Alert", back_populates="found_tenders")
