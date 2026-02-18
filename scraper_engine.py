import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def scrape_dynamic_page(url: str, search_keyword: str = None, max_depth: int = 1):
    """
    Scrapes a dynamic web page using Playwright with optional keyword search and depth crawling.
    """
    results = []
    visited_urls = set()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Create a new context to emulate a real user
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )

        async def _crawl(current_url, current_depth):
            if current_depth > max_depth or current_url in visited_urls:
                return
            
            visited_urls.add(current_url)
            print(f"Crawling: {current_url} (Depth: {current_depth})")
            
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
                        keyword_context = "..." + text_content[start:end] + "..."
                
                # Extract basic metadata
                meta_description = soup.find("meta", attrs={"name": "description"})
                description = meta_description["content"] if meta_description else "No description found"

                # Extract links for next depth
                links = [a['href'] for a in soup.find_all('a', href=True)]
                
                # Improve link resolution
                resolved_links = []
                for link in links:
                    if link.startswith('http'):
                        resolved_links.append(link)
                    elif link.startswith('/'):
                        from urllib.parse import urljoin
                        resolved_links.append(urljoin(current_url, link))

                page_data = {
                    "url": current_url,
                    "depth": current_depth,
                    "title": title,
                    "description": description,
                    "keyword_found": keyword_found,
                    "keyword_context": keyword_context,
                    "content_length": len(text_content),
                    "links_found": len(resolved_links),
                    "text_snippet": text_content[:500] + "...",
                }
                
                # Only add to results if we aren't searching, OR if we are searching and found the keyword
                # defaulting to always adding page data for context, but marking if keyword was found
                results.append(page_data)

                # Recursive call for next depth
                if current_depth < max_depth:
                    # Limit number of links to follow to avoid explosion, e.g., first 5 links
                    for link in resolved_links[:5]: 
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
