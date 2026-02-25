import asyncio
from playwright.async_api import async_playwright

async def test():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto("https://etenders.gov.in/eprocure/app", timeout=60000)
            
            search_links = await page.locator("a:has-text('Tender Search'), a:has-text('Search')").all()
            if search_links:
                await search_links[0].click()
                await page.wait_for_load_state("networkidle")
            
            tender_id_input = page.locator("input[id*='tenderId'], input[id*='keyword'], input[id*='SearchKeyword']")
            if await tender_id_input.count() > 0:
                await tender_id_input.first.fill("2026_NHAI_268271")
                await page.keyboard.press("Enter")
                await page.wait_for_load_state("networkidle")
                
                links = await page.locator("a[id*='DirectLink']").all()
                if links:
                    await links[0].click()
                    await page.wait_for_load_state("networkidle")
                    
                    # We are now on the Tender Details page.
                    # Save the Tender Details HTML
                    content_details = await page.content()
                    with open("debug_tender_details.html", "w", encoding="utf-8") as f:
                        f.write(content_details)
                    print("Saved debug_tender_details.html")
                    
                    # Look for "View More Details" or print icon
                    more_links = await page.locator("a:has-text('View More Details'), a img[alt*='View']").locator("..").all()
                    if more_links:
                        print("Clicking View More Details...")
                        
                        # Handle new window/tab if it opens one
                        async with page.context.expect_page() as new_page_info:
                            await more_links[0].click()
                        new_page = await new_page_info.value
                        await new_page.wait_for_load_state("networkidle")
                        
                        content_more = await new_page.content()
                        with open("debug_view_more.html", "w", encoding="utf-8") as f:
                            f.write(content_more)
                        print("Saved debug_view_more.html")
                    else:
                        print("Could not find 'View More Details' link.")
                else:
                    print("No DirectLink found in search results.")
            else:
                print("Could not find search input.")
                
            await browser.close()
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(test())
