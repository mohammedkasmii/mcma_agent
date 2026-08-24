import asyncio
import os
import sys
from playwright.async_api import async_playwright

async def manual_login():
    async with async_playwright() as p:
        # Launch a visible browser window
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("[*] Navigating to MCMA login page...")
        await page.goto("https://sinauto.mamda-mcma.ma/SinAuto_MCMA/")

        print("\n" + "=" * 65)
        print("  🔑 ACTION REQUIRED IN BROWSER:")
        print("  1. Enter your Username & Password.")
        print("  2. Enter your SMS / OTP verification code.")
        print("  3. Wait for the MCMA dashboard to load.")
        print("=" * 65 + "\n")

        login_detected = False
        max_wait_seconds = 300  # 5 minutes timeout

        for second in range(max_wait_seconds):
            await asyncio.sleep(1)
            current_url = page.url.lower()

            # Condition 1: URL redirected to the dashboard (expertise / frontExpert)
            if "/expertise/" in current_url or "/frontexpert" in current_url or "/gestionexpert" in current_url:
                login_detected = True
                print(f"[✓] Dashboard URL detected: {page.url}")
                break

            # Condition 2: Dashboard form or logout link is present
            try:
                has_search_form = await page.locator("#formRecherche, #ReferenceCie, a[href*='logout'], a[href*='Login/logout']").count() > 0
                if has_search_form and "login" not in current_url and "otp" not in current_url:
                    login_detected = True
                    print(f"[✓] Dashboard elements detected on page!")
                    break
            except Exception:
                pass

            # Print a progress indicator every 15 seconds
            if second > 0 and second % 15 == 0:
                print(f"[*] Still waiting for login & OTP... ({second}s / {max_wait_seconds}s)")

        if not login_detected:
            print("\n[!] Auto-detection timed out. Checking if cookies exist...")

        # Small grace period to ensure all session cookies are set
        await asyncio.sleep(2)

        # Save session storage state (cookies, local storage)
        auth_file = "mcma_auth_state.json"
        await context.storage_state(path=auth_file)
        
        if os.path.exists(auth_file) and os.path.getsize(auth_file) > 10:
            print("\n" + "=" * 65)
            print(f"  [✓] SUCCESS! Session saved to '{auth_file}'")
            print("  You can now run 'python run_dossier.py' to automate dossiers.")
            print("=" * 65 + "\n")
        else:
            print(f"[X] Error: Could not save session state to {auth_file}.")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(manual_login())