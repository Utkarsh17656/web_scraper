import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# MySQL connection string format: mysql+mysqlconnector://user:password@host:port/database
# For local dev, you can set this in your environment variables
MYSQL_URL = os.getenv("MYSQL_URL", "mysql+mysqlconnector://root:password@localhost/tender_scraper")

engine = create_engine(MYSQL_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
