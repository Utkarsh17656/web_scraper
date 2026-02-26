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

# Junk patterns found in etenders.gov.in navigation, footer, and chatbot widgets.
# Used to reject garbage from detail extraction.
_DETAIL_JUNK = [
    'screen reader', 'skip to main', 'nic chat', 'site compatibility',
    'visitor no', 'mis reports', 'tenders by location', 'tenders by organisation',
    'tenders by classification', 'tenders in archive', 'tenders status',
    'cancelled/retendered', 'debarment list', 'announcements', 'awards',
    'help for contractors', 'information about dsc', 'guidelines', 'bidders manual',
    'eprocurement system', 'portal policies', 'national informatics centre',
    'designed, developed', 'all rights reserved', 'site best viewed',
    'nicci', 'digital assistant', 'help desk', 'chat interface',
    'special characters', 'online bidder enrollment', 'forgot password',
    'nodal officer', 'latest tenders', 'latest corrigendum', 'certifying agency',
    'javascript has been disabled', 'corrigendum title', 'welcome to eprocurement',
    'rate us', 'save chat', 'exit chat', 'clear chat', 'hindi voice',
]

def _is_detail_junk(text: str) -> bool:
    """Check if text contains known junk patterns."""
    t = text.lower()
    return any(j in t for j in _DETAIL_JUNK)

def _is_valid_detail_pair(field: str, value: str) -> bool:
    """Validate that a field-value pair is clean tender data, not page junk."""
    if not field or not value:
        return False
    # Field (label) should be short and readable
    if len(field) < 3 or len(field) > 120:
        return False
    # Value shouldn't be absurdly long (sign of concatenated page content)
    if len(value) > 500:
        return False
    # Reject if either side contains known junk
    if _is_detail_junk(field) or _is_detail_junk(value):
        return False
    # Reject if field looks like concatenated text (too many words)
    if field.count(' ') > 15:
        return False
    # Reject pure-number fields (row indices like "120", "1826")
    if field.strip().isdigit():
        return False
    return True


async def _fetch_tender_page_details(context, url: str) -> Dict[str, str]:
    """
    Visit a tender detail page in the SAME browser context (preserving the active session)
    and extract clean key-value pairs from structured tables only.
    Aggressively filters out navigation, footer, and chatbot junk.
    """
    details: Dict[str, str] = {}
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=45000)
        content = await page.content()

        # Check for session timeout
        if "session has timed out" in content.lower() or "session expired" in content.lower():
            return {"_error": "Session expired before details could be fetched"}

        # Check if we landed on the home/search page instead of the detail page
        if "welcome to eprocurement" in content.lower() and "tender details" not in content.lower():
            return {"_error": "Landed on home page instead of tender detail page"}

        # Wait for JS rendering
        try:
            await page.wait_for_selector("table", timeout=5000)
        except Exception:
            pass
        await page.evaluate("() => new Promise(r => setTimeout(r, 3000))")

        # Re-grab content after JS render
        content = await page.content()
        soup = BeautifulSoup(content, 'html.parser')

        # ONLY extract from tables — this is the reliable structured data on etenders.gov.in.
        # The detail page uses 2-cell rows: <td>Label</td><td>Value</td>
        for table in soup.find_all('table')[:15]:
            # Skip tables whose text is mostly junk (nav menus, footer)
            table_text_sample = table.get_text()[:300].lower()
            if _is_detail_junk(table_text_sample):
                continue

            for row in table.find_all('tr'):
                cells = row.find_all(['td', 'th'])

                if len(cells) == 2:
                    # Standard label-value row
                    field = " ".join(cells[0].get_text(strip=True).split())
                    value = " ".join(cells[1].get_text(strip=True).split())
                    if _is_valid_detail_pair(field, value) and field not in details:
                        details[field] = value

                elif len(cells) == 4:
                    # Some detail tables pack two pairs per row:
                    # <td>Label1</td><td>Value1</td><td>Label2</td><td>Value2</td>
                    for i in range(0, 4, 2):
                        field = " ".join(cells[i].get_text(strip=True).split())
                        value = " ".join(cells[i + 1].get_text(strip=True).split())
                        if _is_valid_detail_pair(field, value) and field not in details:
                            details[field] = value

        logger.info(f"Pre-fetched {len(details)} clean detail fields from {url}")
        return details
    except Exception as e:
        logger.warning(f"Failed to pre-fetch tender details from {url}: {e}")
        return {"_error": str(e)}
    finally:
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass


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

                            # PRE-FETCH: Visit each matching tender's detail page
                            # while the session is still alive (limit to 5 tenders)
                            for row_data in table_rows[:5]:
                                if '_links' not in row_data:
                                    continue
                                for col_name, link_info in row_data['_links'].items():
                                    if link_info and 'url' in link_info:
                                        tender_url = link_info['url']
                                        logger.info(f"Pre-fetching details for: {tender_url}")
                                        fetched = await _fetch_tender_page_details(context, tender_url)
                                        if fetched and '_error' not in fetched:
                                            row_data['_details'] = fetched
                                        break  # Only visit first link per row

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

async def fetch_tender_details_dict(url: str) -> Dict[str, Any]:
    """
    Visits a tender details page and extracts all data including dynamically loaded content.
    Returns a dictionary of all extracted fields.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--no-sandbox']
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()

        try:
            logger.info(f"Fetching tender details from: {url}")
            await page.goto(url, wait_until="networkidle", timeout=120000)
            
            # Check for session timeout error
            page_content = await page.content()
            if "session has timed out" in page_content.lower() or "session expired" in page_content.lower():
                logger.warning("Session timeout detected!")
                return {"_error": "Session timeout", "_message": "The session has expired. Please navigate through the search page to refresh your session."}
            
            logger.info("Waiting for dynamic content to load...")
            
            # Wait for multiple possible selectors where tender data might be
            content_selectors = [
                "div[class*='tender']",
                "div[class*='detail']",
                "span[class*='label']",
                "p",
                "body"
            ]
            
            for selector in content_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=10000)
                    logger.info(f"Found: {selector}")
                    break
                except Exception:
                    continue
            
            # Aggressive scrolling to trigger all dynamic loads
            logger.info("Scrolling page multiple times...")
            await page.evaluate("""
                async () => {
                    for (let i = 0; i < 10; i++) {
                        window.scrollBy(0, 500);
                        await new Promise(r => setTimeout(r, 500));
                    }
                    window.scrollTo(0, 0);
                }
            """)
            
            # Wait for all dynamic content
            await page.evaluate("() => new Promise(r => setTimeout(r, 8000))")
            
            # Try to click any expand/details buttons that might exist
            logger.info("Looking for expandable details...")
            try:
                await page.evaluate("""
                    () => {
                        const buttons = document.querySelectorAll('[class*="expand"], [class*="more"], [class*="detail"], button, a');
                        buttons.forEach((btn, idx) => {
                            if (idx < 5 && btn.textContent.toLowerCase().includes(('view|more|detail|expand|show').split('|'))) {
                                btn.click();
                            }
                        });
                    }
                """)
                await page.evaluate("() => new Promise(r => setTimeout(r, 3000))")
            except Exception as e:
                logger.debug(f"Could not expand details: {e}")
            
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')

            logger.info(f"Page loaded, extracting content...")
            all_data = {}

            # ========== STRATEGY 1: Extract from visible tables ==========
            logger.info("Looking for tables...")
            tables = soup.find_all('table')
            
            if tables:
                for table_idx, table in enumerate(tables):
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 2:
                            # Extract each pair of cells
                            for i in range(0, len(cells) - 1, 2):
                                field = " ".join(cells[i].get_text(strip=True).split())
                                value = " ".join(cells[i + 1].get_text(strip=True).split())
                                if field and value and len(field) > 2:
                                    if field not in all_data:
                                        all_data[field] = value

            # ========== STRATEGY 2: Extract from divs with label-value patterns ==========
            logger.info("Looking for label-value patterns in divs...")
            
            # Find all divs and spans with text content
            for div in soup.find_all(['div', 'span', 'p', 'li']):
                text = div.get_text(strip=True)
                
                # Look for patterns like "Label: Value"
                if ':' in text and 10 < len(text) < 500:
                    parts = text.split(':', 1)
                    if len(parts) == 2:
                        label = parts[0].strip()
                        value = parts[1].strip()
                        
                        # Filter out too-short labels
                        if len(label) > 3 and len(value) > 1 and label not in all_data:
                            # Skip if label is just "Label" or clearly not a field name
                            if not (label.lower() in ['label', 'value', 'item', 'no', 'id', 'name'] and len(label) < 10):
                                all_data[label] = value[:1000]

            # ========== STRATEGY 3: Extract heading + next content pattern ==========
            logger.info("Looking for heading + content patterns...")
            
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'b']):
                heading_text = heading.get_text(strip=True)
                
                if 3 < len(heading_text) < 150:
                    # Find next sibling that might be the value
                    next_elem = heading.find_next(['p', 'div', 'span', 'td'])
                    if next_elem:
                        value = next_elem.get_text(strip=True)
                        if len(value) > 2 and heading_text not in all_data:
                            all_data[heading_text] = value[:1000]

            # ========== STRATEGY 4: Extract from data attributes ==========
            logger.info("Looking for data in attributes...")
            
            for elem in soup.find_all(True):  # All elements
                # Check for common data attributes
                for attr in ['data-value', 'data-label', 'title', 'aria-label']:
                    if elem.has_attr(attr):
                        value = elem.get(attr, '').strip()
                        if value and len(value) > 3:
                            # Use element text as key if available
                            key = elem.get_text(strip=True)[:50]
                            if not key:
                                key = f"Data_{attr}"
                            if key not in all_data and len(key) > 2:
                                all_data[key] = value[:1000]

            # ========== STRATEGY 5: Fallback - extract all text in blocks ==========
            if len(all_data) < 5:
                logger.warning(f"Only {len(all_data)} data points found, using aggressive fallback...")
                
                body = soup.find('body')
                if body:
                    all_text = body.get_text()
                    lines = [l.strip() for l in all_text.split('\n') if l.strip()]
                    
                    # Group consecutive lines
                    for i in range(0, len(lines) - 1, 2):
                        line1 = lines[i][:100]
                        line2 = lines[i + 1][:500] if i + 1 < len(lines) else ""
                        
                        if line1 and line2 and len(line1) > 5 and len(line2) > 5:
                            if line1 not in all_data and not any(c.isdigit() for c in line1[:3]):
                                all_data[line1] = line2

            return all_data

        except Exception as e:
            logger.error(f"Error extracting tender details: {e}", exc_info=True)
            return {"_error": str(e)}
        finally:
            await browser.close()


async def export_tender_details_csv(url: str) -> str:
    """
    Visits a tender details page and extracts all data including dynamically loaded content.
    Returns CSV content as string.
    """
    import csv
    import io

    csv_output = io.StringIO()
    writer = csv.writer(csv_output)
    
    all_data = await fetch_tender_details_dict(url)
    
    writer.writerow(["Field / Property", "Value"])
    
    if "_error" in all_data:
        writer.writerow(["Error", all_data.get("_error")])
        if "_message" in all_data:
            writer.writerow(["Message", all_data.get("_message")])
        writer.writerow(["URL", url])
        return csv_output.getvalue()

    if all_data:
        logger.info(f"Formatting {len(all_data)} data fields to CSV")
        for field, value in all_data.items():
            # Clean up field name
            field = str(field).replace('\n', ' ').replace('\r', ' ')
            value = str(value).replace('\n', ' | ').replace('\r', ' | ')
            
            # Ensure length limits for CSV
            if len(value) > 10000:
                value = value[:10000] + "..."
            
            writer.writerow([field, value])
        
        writer.writerow([""])
        writer.writerow(["Extraction Status", "Successfully extracted tender details"])
        writer.writerow(["Source URL", url])
    else:
        logger.warning("No data extracted from page")
        writer.writerow(["Status", "Page loaded but extraction found minimal data"])
        writer.writerow(["URL", url])
        
    return csv_output.getvalue()


async def export_all_tenders_with_details_csv(tender_data_list: List[Dict[str, Any]]) -> str:
    """
    Exports all tenders from search results with enriched details fetched from each tender URL.
    
    Args:
        tender_data_list: List of tender dictionaries with keys: title, ref, closing, opening, link, url
    
    Returns:
        CSV string with tender data enriched with details
    """
    import csv
    import io
    
    csv_output = io.StringIO()
    writer = csv.writer(csv_output)
    
    # Define columns: basic info + detailed fields
    headers = ['#', 'Tender Title', 'Ref / Tender ID', 'Closing Date', 'Opening Date', 'Link', 'Details Summary']
    writer.writerow(headers)
    
    logger.info(f"Starting bulk export with details for {len(tender_data_list)} tenders...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--disable-dev-shm-usage', '--no-sandbox']
        )
        context = await browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080}
        )
        
        for idx, tender in enumerate(tender_data_list, 1):
            try:
                tender_url = tender.get('url') or tender.get('link')
                if not tender_url:
                    logger.warning(f"Tender {idx} has no URL, skipping details fetch")
                    writer.writerow([
                        idx,
                        tender.get('title', ''),
                        tender.get('ref', ''),
                        tender.get('closing', ''),
                        tender.get('opening', ''),
                        tender.get('link', ''),
                        "No URL available"
                    ])
                    continue
                
                logger.info(f"Fetching details for tender {idx}/{len(tender_data_list)}: {tender_url}")
                
                page = await context.new_page()
                details_summary = ""
                
                try:
                    # Navigate to tender details
                    await page.goto(tender_url, wait_until="networkidle", timeout=45000)
                    
                    # Check for session timeout early
                    content = await page.content()
                    if "session has timed out" in content.lower() or "session expired" in content.lower():
                        logger.warning(f"Session timeout for tender {idx}: {tender_url}")
                        details_summary = "Session Expired - Refresh needed"
                    else:
                        # Wait for content to load
                        try:
                            await page.wait_for_selector("table, [class*='detail'], [class*='info']", timeout=5000)
                        except Exception:
                            pass
                        
                        # Additional wait for JS rendering
                        await page.evaluate("() => new Promise(r => setTimeout(r, 2000))")
                        
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # Extract key details
                        key_fields = {
                            'Organisation': '(Organisation|Procuring Entity|Ministry|Department)',
                            'Tender Type': '(Tender Type|Type of Tender|Category)',
                            'Estimated Value': '(Estimated Value|Estimated Cost|Budget)',
                            'Bid Submission': '(Bid Submission|Submit.*[Bb]id)',
                            'Status': '(Status|Tender Status)',
                        }
                        
                        details_parts = []
                        
                        # Extract from tables
                        tables = soup.find_all('table')[:10]  # Limit to first 10 tables
                        for table in tables:
                            rows = table.find_all('tr')
                            for row in rows:
                                cols = row.find_all(['th', 'td'])
                                if len(cols) >= 2:
                                    key_text = cols[0].get_text(strip=True).lower()
                                    val_text = " ".join(cols[1].get_text(strip=True).split())[:150]  # Limit length
                                    
                                    for field, pattern in key_fields.items():
                                        import re
                                        if re.search(pattern, key_text, re.IGNORECASE) and val_text and field not in str(details_parts):
                                            details_parts.append(f"{field}: {val_text}")
                                            break
                        
                        # Extract from structured text if no tables
                        if not details_parts:
                            text_content = soup.get_text()
                            for line in text_content.split('\n')[:50]:  # Check first 50 lines
                                line = line.strip()
                                if ':' in line and len(line) < 300:
                                    for field, pattern in key_fields.items():
                                        import re
                                        if re.search(pattern, line, re.IGNORECASE):
                                            details_parts.append(line[:200])
                                            break
                        
                        details_summary = " | ".join(details_parts[:3]) if details_parts else "Details extracted"
                        if not details_summary:
                            details_summary = "Available online"
                    
                except Exception as detail_error:
                    logger.warning(f"Error fetching details for tender {idx}: {detail_error}")
                    details_summary = "Details fetch error - see link"
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass
                
                # Write row with details
                writer.writerow([
                    idx,
                    tender.get('title', ''),
                    tender.get('ref', ''),
                    tender.get('closing', ''),
                    tender.get('opening', ''),
                    tender.get('link', ''),
                    details_summary
                ])
                
            except Exception as e:
                logger.error(f"Error processing tender {idx}: {e}")
                writer.writerow([
                    idx,
                    tender.get('title', ''),
                    tender.get('ref', ''),
                    tender.get('closing', ''),
                    tender.get('opening', ''),
                    tender.get('link', ''),
                    f"Error: {str(e)[:100]}"
                ])
        
        await browser.close()
    
    logger.info(f"Bulk export with details completed for {len(tender_data_list)} tenders")
    return csv_output.getvalue()


if __name__ == "__main__":
    url = "https://etenders.gov.in/eprocure/app"
    keyword = "11/OandM/IE/NH-19/2025-2026"
    print(asyncio.run(scrape_dynamic_page(url, search_keyword=keyword, max_depth=1)))
