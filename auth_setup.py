"""Create a reusable MCMA Playwright session through manual login and OTP."""

import asyncio
import os

from playwright.async_api import async_playwright


async def manual_login() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("[*] Navigating to MCMA login page...")
        await page.goto("https://sinauto.mamda-mcma.ma/SinAuto_MCMA/")
        print("\n" + "=" * 65)
        print("ACTION REQUIRED IN THE BROWSER")
        print("1. Enter the MCMA username and password.")
        print("2. Enter the SMS/OTP verification code.")
        print("3. Wait for the MCMA dashboard to load.")
        print("=" * 65 + "\n")

        login_detected = False
        max_wait_seconds = 300
        for second in range(max_wait_seconds):
            await asyncio.sleep(1)
            current_url = page.url.lower()
            if any(token in current_url for token in ("/expertise/", "/frontexpert", "/gestionexpert")):
                login_detected = True
                print("[OK] MCMA dashboard URL detected.")
                break
            try:
                dashboard = page.locator(
                    "#formRecherche, #ReferenceCie, a[href*='logout'], a[href*='Login/logout']"
                )
                if await dashboard.count() and "login" not in current_url and "otp" not in current_url:
                    login_detected = True
                    print("[OK] MCMA dashboard elements detected.")
                    break
            except Exception:
                # Navigation can briefly destroy the page execution context.
                pass
            if second and second % 15 == 0:
                print(f"[*] Waiting for login and OTP ({second}/{max_wait_seconds}s)...")

        if not login_detected:
            print("[X] Login was not confirmed before timeout. No session file was written.")
            await browser.close()
            return

        await asyncio.sleep(2)
        auth_file = "mcma_auth_state.json"
        await context.storage_state(path=auth_file)
        if os.path.exists(auth_file) and os.path.getsize(auth_file) > 10:
            print(f"[OK] Session saved to {auth_file}")
        else:
            print("[X] The MCMA session file could not be created.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(manual_login())
