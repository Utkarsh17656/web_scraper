@echo off
echo Starting Scraper Tool...
call .\venv\Scripts\activate
python -m playwright install chromium
echo Opening browser...
start http://127.0.0.1:8001
python main.py
pause
