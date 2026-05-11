import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        print("Navigating to Naukrigulf...")
        response = await page.goto("https://www.naukrigulf.com/jobs-in-uae", wait_until="networkidle", timeout=60000)
        print(f"Status: {response.status}")
        content = await page.content()
        print(f"Content length: {len(content)}")
        with open("naukri_debug.html", "w", encoding="utf-8") as f:
            f.write(content)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
