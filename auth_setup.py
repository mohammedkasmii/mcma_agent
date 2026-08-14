import asyncio
from playwright.async_api import async_playwright

async def manual_login():
    async with async_playwright() as p:
        # Launch a visible browser window
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("[*] Navigating to MCMA login page...")
        await page.goto("https://sinauto.mamda-mcma.ma/")

        print("\n" + "="*50)
        print(" [!] ACTION REQUIRED: Log in and enter your OTP code.")
        print(" [!] Waiting up to 5 minutes for the dashboard to load...")
        print("="*50 + "\n")

        # Waits until the dashboard element (#menu-toggler) appears after a successful login
        await page.wait_for_selector("#menu-toggler", timeout=300000)

        print("[*] Login detected! Saving session state...")
        await context.storage_state(path="mcma_auth_state.json")
        print("[*] Success! Session saved to 'mcma_auth_state.json'. You can close this window.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(manual_login())