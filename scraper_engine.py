import asyncio
from typing import Optional, List, Dict, Any
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
    Features:
      - Smart Portal Accelerator: Uses native search boxes on GePNIC/NIC portals
      - Point-to-Point Filtering: Shows only exact keyword matches when searching
      - Safety Net: Always returns useful feedback even if no tables found
    """
    results: List[Dict[str, Any]] = []
    visited_urls: set = set()
    base_domain = urlparse(url).netloc

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--no-sandbox']
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080}
        )

        async def _crawl(current_url: str, current_depth: int):
            if current_depth > max_depth or current_url in visited_urls:
                return

            parsed = urlparse(current_url)
            if not parsed.scheme or not parsed.netloc:
                return

            # Stay within same domain
            if parsed.netloc != base_domain:
                return

            visited_urls.add(current_url)
            logger.info(f"Crawling: {current_url} (Depth: {current_depth})")

            page = await context.new_page()
            captcha_detected = False
            try:
                await page.goto(current_url, wait_until="networkidle", timeout=60000)

                # ================================================================
                # SMART PORTAL ACCELERATOR
                # On the first page, try to use the portal's native search box.
                # This is specifically tuned for GePNIC / etenders.gov.in portals.
                # ================================================================
                if current_depth == 1 and search_keyword:
                    try:
                        # Selectors verified by live testing on etenders.gov.in
                        search_selectors = [
                            'input.textbox2',           # GePNIC Standard quick search
                            'input[id*="SearchKeyword"]',
                            'input[title*="Search"]',
                            'input#SearchKeyword'
                        ]

                        found_search = False
                        for selector in search_selectors:
                            try:
                                is_visible = await page.is_visible(selector, timeout=2000)
                                if is_visible:
                                    logger.info(f"Using native search box: {selector}")
                                    await page.click(selector)
                                    await page.fill(selector, search_keyword)

                                    # Try clicking the associated "Go" button first
                                    go_btn = page.locator('input[value="Go"], input.gobutton')
                                    if await go_btn.count() > 0 and await go_btn.first.is_visible(timeout=1000):
                                        await go_btn.first.click()
                                    else:
                                        await page.keyboard.press("Enter")

                                    # Wait for results (government sites are slow)
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=15000)
                                    except Exception:
                                        pass

                                    found_search = True
                                    logger.info("Native search submitted successfully.")
                                    break
                            except Exception:
                                continue

                        if not found_search:
                            # Fallback: look for "Search" or "Tender Search" link in nav
                            menu_link = page.locator('a:has-text("Search"), a:has-text("Tender Search")')
                            if await menu_link.count() > 0 and await menu_link.first.is_visible(timeout=1500):
                                logger.info("Navigating to dedicated Search page.")
                                await menu_link.first.click()
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=8000)
                                except Exception:
                                    pass

                                search_page_input = page.locator('input[id*="tenderId"], input[id*="keyword"], input[id*="SearchKeyword"]')
                                if await search_page_input.count() > 0 and await search_page_input.first.is_visible(timeout=2000):
                                    await search_page_input.first.fill(search_keyword)
                                    await page.keyboard.press("Enter")
                                    try:
                                        await page.wait_for_load_state("networkidle", timeout=8000)
                                    except Exception:
                                        pass
                                    logger.info("Deep search submitted via Search page.")

                    except Exception as se:
                        logger.debug(f"Native search accelerator skipped: {se}")

                # Extract content after any navigation
                content = await page.content()
                title = await page.title()

                # Check for CAPTCHA
                if "captcha" in content.lower():
                    captcha_detected = True
                    logger.warning(f"CAPTCHA detected on {current_url}")

                soup = BeautifulSoup(content, 'html.parser')

                # Detect <base> tag for correct relative link resolution
                base_tag = soup.find('base', href=True)
                base_url_for_links = urljoin(current_url, base_tag['href']) if base_tag else current_url

                text_content = ' '.join(soup.stripped_strings)

                # Check for keyword in page text
                keyword_found: bool = False
                keyword_context: str = ""
                relevance_score: int = 0
                if search_keyword:
                    sk_lower = search_keyword.lower()
                    if sk_lower in text_content.lower():
                        keyword_found = True
                        relevance_score += 50
                        idx = text_content.lower().find(sk_lower)
                        start = max(0, idx - 50)
                        end = min(len(text_content), idx + len(search_keyword) + 50)
                        keyword_context = "..." + text_content[start:end] + "..."

                # Extract metadata
                meta_description = soup.find("meta", attrs={"name": "description"})
                description = meta_description["content"] if meta_description else "No description found"

                # Resolve all links for recursive crawling
                resolved_links: List[str] = []
                for a in soup.find_all('a', href=True):
                    link = str(a['href']).strip()
                    if not link or link.startswith('#') or link.startswith('javascript:'):
                        continue
                    full_url = urljoin(current_url, link)
                    if full_url.startswith('http'):
                        resolved_links.append(full_url)

                logger.debug(f"Resolved {len(resolved_links)} links from {current_url}")

                # ================================================================
                # TABLE EXTRACTION WITH POINT-TO-POINT FILTERING
                # ================================================================
                tables_data: List[Dict[str, Any]] = []
                try:
                    try:
                        await page.wait_for_selector("table", timeout=5000)
                    except Exception:
                        pass

                    soup_tables = soup.find_all('table')
                    logger.info(f"BS4 found {len(soup_tables)} table tags on {current_url}")

                    # Keywords that indicate layout/nav tables to skip
                    layout_junk = [
                        'screen reader', 'skip to main', 'nic chat', 'site compatibility',
                        'visitor no', 'mis reports', 'tenders by location', 'tenders by organisation',
                        'tenders by classification', 'tenders in archive', 'tenders status',
                        'cancelled/retendered', 'debarment list', 'announcements', 'awards', 'downloads',
                        'help for contractors', 'information about dsc', 'guidelines', 'bidders manual',
                    ]

                    for i, st in enumerate(soup_tables):
                        rows = st.find_all('tr')
                        if not rows or len(rows) < 2:
                            continue

                        # Identify headers
                        thead = st.find('thead')
                        if thead:
                            header_elements = thead.find_all(['th', 'td'])
                        else:
                            header_elements = rows[0].find_all(['th', 'td'])

                        headers = [h.get_text(strip=True) for h in header_elements]
                        header_string = " ".join(headers).lower()
                        table_classes = str(st.get('class', '')).lower()

                        # Skip layout tables
                        if any(jk in header_string for jk in layout_junk) or 'logintext' in table_classes:
                            nav_count = sum(1 for jk in layout_junk if jk in header_string)
                            if len(headers) < 2 or nav_count > 2:
                                continue

                        # Skip if header looks like raw layout text
                        if len(headers) > 0 and len(headers[0]) > 300:
                            continue

                        headers = [f"Col_{idx}" if not str(h).strip() else str(h) for idx, h in enumerate(headers)]

                        table_rows: List[Dict[str, Any]] = []
                        data_rows = rows[1:] if len(rows) > 1 else rows

                        for tr in data_rows:
                            cols = tr.find_all(['td', 'th'])
                            if not cols:
                                continue

                            row_dict: Dict[str, Any] = {}
                            row_links: Dict[str, Any] = {}
                            for idx, c in enumerate(cols):
                                if idx >= len(headers):
                                    break
                                header_name = headers[idx]

                                # Better text cleaning
                                for br in c.find_all("br"):
                                    br.replace_with("\n")
                                text = c.get_text(separator=" ", strip=True)
                                text = " ".join(text.split())
                                row_dict[header_name] = text

                                # Extract links from cells
                                a_tag = c.find('a', href=True)
                                if a_tag:
                                    link_href = str(a_tag['href']).strip()
                                    if not link_href.startswith(('javascript:', '#')):
                                        full_link = urljoin(base_url_for_links, link_href)
                                        row_links[header_name] = {"url": full_link.replace(" ", "%20")}

                            if row_dict:
                                row_text_check = " ".join(str(v) for v in row_dict.values()).lower()

                                # Skip navigation rows
                                if len(row_text_check) < 10:
                                    continue
                                if any(jk in row_text_check for jk in ['screen reader', 'updates every', 'click here']):
                                    continue
                                if row_text_check in ['next', 'previous', 'none', 'more...']:
                                    continue

                                row_data: Dict[str, Any] = dict(row_dict)
                                if row_links:
                                    row_data["_links"] = row_links
                                table_rows.append(row_data)

                        if not table_rows:
                            continue

                        table_text: str = str(table_rows).lower()
                        table_relevance: int = 0

                        # POINT-TO-POINT FILTERING: When searching, only return exact matches
                        if search_keyword:
                            sk_lower = (search_keyword or "").lower()

                            # Skip entire table if it doesn't contain the keyword
                            if sk_lower not in table_text:
                                continue

                            # Keep ONLY the rows that contain the exact keyword
                            exact_match_rows: List[Dict[str, Any]] = []
                            for r in table_rows:
                                r_text = " ".join(str(v) for v in r.values()).lower()
                                if sk_lower in r_text:
                                    r["_highlight"] = True
                                    exact_match_rows.append(r)

                            if not exact_match_rows:
                                continue

                            table_rows = exact_match_rows
                            table_relevance = 1000  # Max priority for exact matches

                        # Secondary relevance for non-keyword searches
                        tender_patterns = ['tender', 'bid', 'ref', 'opening', 'date', 'id', 'no', 'title', 'organisation']
                        is_tender_table = any(p in table_text for p in tender_patterns)
                        if is_tender_table and table_relevance == 0:
                            table_relevance += 20

                        # Store the table
                        if table_rows and (table_relevance > 0 or (len(table_rows) > 2 and len(headers) > 2)):
                            if len(table_rows) > 200:
                                table_rows = table_rows[:200]
                            tables_data.append({
                                "table_index": i,
                                "row_count": len(table_rows),
                                "is_likely_tender": is_tender_table,
                                "relevance": table_relevance,
                                "data": table_rows
                            })
                            relevance_score += table_relevance

                    # Sort tables within page by relevance
                    if tables_data:
                        tables_data.sort(key=lambda x: x.get('relevance', 0), reverse=True)

                    logger.info(f"Extracted {len(tables_data)} relevant tables from {current_url}")

                except Exception as table_err:
                    logger.error(f"Table extraction error on {current_url}: {table_err}")

                page_data: Dict[str, Any] = {
                    "url": current_url,
                    "depth": current_depth,
                    "title": title,
                    "description": description,
                    "keyword_found": keyword_found,
                    "relevance_score": relevance_score,
                    "keyword_context": keyword_context,
                    "content_length": len(text_content),
                    "links_found": len(resolved_links),
                    "tables_found": len(tables_data),
                    "captcha_detected": captcha_detected,
                    "extracted_tables": tables_data,
                    "text_snippet": text_content[:500] + "...",
                }

                # Only keep pages with relevant content when searching
                if search_keyword:
                    if keyword_found or tables_data:
                        results.append(page_data)
                else:
                    results.append(page_data)

                await page.close()

                # Recursive crawl for next depth
                if current_depth < max_depth:
                    priority_links: List[str] = []
                    other_links: List[str] = []

                    nav_keywords = ['tender', 'bid', 'latest', 'active', 'result', 'award', 'procurement']
                    for link in resolved_links:
                        if any(k in link.lower() for k in nav_keywords):
                            priority_links.append(link)
                        else:
                            other_links.append(link)

                    links_to_follow = (priority_links + other_links)[:15]
                    for link_item in links_to_follow:
                        await _crawl(link_item, current_depth + 1)

            except Exception as e:
                logger.error(f"Error crawling {current_url}: {str(e)}")
            finally:
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass

        try:
            await _crawl(url, 1)

            # Sort all pages by relevance score
            results.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

            # SAFETY NET: Always return something useful
            if not results:
                logger.info("No matching pages found. Returning informative stub.")
                results.append({
                    "url": url,
                    "title": "Search Completed - No Matches Found",
                    "description": (
                        f"The scraper explored {len(visited_urls)} page(s) starting from {url} "
                        f"but could not find any tables matching '{search_keyword}'. "
                        "This may be due to a CAPTCHA, session requirement, or the tender ID is not listed in the currently accessible pages."
                    ),
                    "keyword_found": False,
                    "relevance_score": 0,
                    "captcha_detected": False,
                    "extracted_tables": []
                })

            return {
                "base_url": url,
                "total_pages_scraped": len(results),
                "pages": results
            }

        except Exception:
            import traceback
            error_msg = traceback.format_exc()
            logger.error(f"Scraping error: {error_msg}")
            return {"error": error_msg}
        finally:
            await browser.close()


if __name__ == "__main__":
    url = "https://etenders.gov.in/eprocure/app"
    keyword = "11/OandM/IE/NH-19/2025-2026"
    print(asyncio.run(scrape_dynamic_page(url, search_keyword=keyword, max_depth=1)))
