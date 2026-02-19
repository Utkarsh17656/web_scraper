import asyncio
from typing import Optional
import random
import logging
import os
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
]

async def scrape_dynamic_page(url: str, search_keyword: Optional[str] = None, max_depth: int = 1):
    """
    Scrapes a dynamic web page using Playwright with optional keyword search and depth crawling.
    """
    results = []
    visited_urls = set()
    base_domain = urlparse(url).netloc
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Create a context with a random User-Agent
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080}
        )

        async def _crawl(current_url, current_depth):
            if current_depth > max_depth or current_url in visited_urls:
                return
            
            # Basic link validation
            parsed = urlparse(current_url)
            if not parsed.scheme or not parsed.netloc:
                return
            
            # Stay within same domain to avoid scraping the whole internet
            if parsed.netloc != base_domain:
                return

            visited_urls.add(current_url)
            logger.info(f"Crawling: {current_url} (Depth: {current_depth})")
            
            page = await context.new_page()
            try:
                # Navigate to the URL
                await page.goto(current_url, wait_until="networkidle", timeout=60000)

                # Extract content
                content = await page.content()
                title = await page.title()
                
                # Use BeautifulSoup for parsing
                soup = BeautifulSoup(content, 'html.parser')
                text_content = ' '.join(soup.stripped_strings)
                
                # Check for keyword
                keyword_found = False
                keyword_context = ""
                if search_keyword:
                    if search_keyword.lower() in text_content.lower():
                        keyword_found = True
                        # simple context extraction (50 chars before and after)
                        idx = text_content.lower().find(search_keyword.lower())
                        start = max(0, idx - 50)
                        end = min(len(text_content), idx + len(search_keyword) + 50)
                        snippet = text_content[start:end]
                        keyword_context = "..." + str(snippet) + "..."
                
                # Extract basic metadata
                meta_description = soup.find("meta", attrs={"name": "description"})
                description = meta_description["content"] if meta_description else "No description found"

                # Extract links for next depth
                links = [a['href'] for a in soup.find_all('a', href=True)]
                
                # Improve link resolution
                resolved_links = []
                from urllib.parse import urljoin
                for link in links:
                    link = link.strip()
                    if not link or link.startswith('#') or link.startswith('javascript:'):
                        continue
                    
                    # Correctly resolve all relative links
                    full_url = urljoin(current_url, link)
                    
                    # Only add if it's a valid http URL
                    if full_url.startswith('http'):
                        resolved_links.append(full_url)
                
                logger.debug(f"Resolved {len(resolved_links)} links from {current_url}")

                # Extract tables
                tables_data = []
                try:
                    # Explicit wait for any table to appear (up to 5s)
                    try:
                        await page.wait_for_selector("table", timeout=5000)
                    except:
                        pass # No tables found via selector within timeout

                    import pandas as pd
                    import io
                    
                    # Try pandas first (best for structured data)
                    dfs = []
                    try:
                        # try html5lib as flavor for better compatibility with messy gov portals
                        import pandas as pd
                        dfs = pd.read_html(io.StringIO(content), flavor='html5lib')
                        logger.info(f"Pandas found {len(dfs)} potential tables on {current_url}")
                    except Exception as pd_err:
                        logger.warning(f"Pandas read_html failed on {current_url}: {pd_err}. Falling back to manual extraction.")
                        dfs = []

                    # Fallback or supplementary extraction using BeautifulSoup
                    if not dfs:
                        soup_tables = soup.find_all('table')
                        logger.info(f"BS4 found {len(soup_tables)} table tags on {current_url}")
                        for st in soup_tables:
                            rows = st.find_all('tr')
                            if len(rows) >= 1: # Even 1 row might be a header-only table we can use
                                table_rows = []
                                for tr in rows:
                                    cols = tr.find_all(['td', 'th'])
                                    row_data = [c.get_text(separator=" ", strip=True) for c in cols]
                                    if any(row_data): # skip empty rows
                                        table_rows.append(row_data)
                                if table_rows:
                                    df = pd.DataFrame(table_rows)
                                    dfs.append(df)

                    for i, df in enumerate(dfs):
                        # Lower thresholds significantly
                        if len(df) >= 1 and len(df.columns) >= 1:
                            table_text = df.to_string().lower()
                            # Broader keyword list including common Indian gov procurement terms
                            keywords = [
                                'tender', 'bid', 'ref', 'opening', 'date', 'award', 'contract', 
                                'id', 'no', 'title', 'subject', 'sl.no', 'organisation', 
                                'published', 'closing', 'corrigendum', 'nit', 'aoc'
                            ]
                            is_tender_table = any(k in table_text for k in keywords)
                            
                            # Keep it if it has ANY tender keywords OR if it's a reasonably large data structure
                            if is_tender_table or (len(df) > 2 and len(df.columns) > 1):
                                df = df.fillna('')
                                # Ensure headers are unique strings
                                if not df.empty:
                                    df.columns = [f"Col_{idx}" if str(c).strip() == "" else str(c) for idx, c in enumerate(df.columns)]
                                
                                table_json = df.to_dict(orient='records')
                                if len(table_json) > 200: table_json = table_json[:200]
                                    
                                tables_data.append({
                                    "table_index": i,
                                    "row_count": len(df),
                                    "is_likely_tender": is_tender_table,
                                    "data": table_json
                                })
                    
                    logger.info(f"Extracted {len(tables_data)} valid tables from {current_url}")
                except Exception as table_err:
                    logger.error(f"Table extraction error on {current_url}: {table_err}")

                page_data = {
                    "url": current_url,
                    "depth": current_depth,
                    "title": title,
                    "description": description,
                    "keyword_found": keyword_found,
                    "keyword_context": keyword_context,
                    "content_length": len(text_content),
                    "links_found": len(resolved_links),
                    "tables_found": len(tables_data),
                    "extracted_tables": tables_data,
                    "text_snippet": text_content[:500] + "...",
                }
                
                # Only add to results if we aren't searching, OR if we are searching and found the keyword
                # defaulting to always adding page data for context, but marking if keyword was found
                results.append(page_data)

                # Recursive call for next depth
                if current_depth < max_depth:
                    # Prioritize links that look like tender lists
                    priority_links = []
                    other_links = []
                    
                    keywords = ['tender', 'bid', 'latest', 'active', 'result', 'award', 'procurement']
                    for link in resolved_links:
                        if any(k in link.lower() for k in keywords):
                            priority_links.append(link)
                        else:
                            other_links.append(link)
                    
                    # Follow priority links first, then others, up to a limit
                    all_follow_links = priority_links + other_links
                    links_to_follow = all_follow_links[:15]
                    
                    for link in links_to_follow: 
                        await _crawl(link, current_depth + 1)

            except Exception as e:
                print(f"Error crawling {current_url}: {str(e)}")
                results.append({"url": current_url, "error": str(e)})
            finally:
                await page.close()

        try:
            await _crawl(url, 1)
            
            return {
                "base_url": url,
                "total_pages_scraped": len(results),
                "pages": results
            }

        except Exception:
            import traceback
            error_msg = traceback.format_exc()
            print(f"Scraping error: {error_msg}")
            return {"error": error_msg}
        finally:
            if 'browser' in locals():
                await browser.close()

if __name__ == "__main__":
    # Test with a sample URL if run directly
    url = "https://example.com"
    print(asyncio.run(scrape_dynamic_page(url)))
