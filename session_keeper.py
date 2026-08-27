"""
session_keeper.py — MCMA Active Session Keep-Alive Daemon
==========================================================
Maintains an active MCMA session 24/7 by periodically pinging the dashboard
in the background using the saved storage state (mcma_auth_state.json).

Features:
  - Periodically refreshes server session idle timers to prevent OTP expiration.
  - Automatically captures and saves updated session cookies back to mcma_auth_state.json.
  - One-shot health-check mode (--check) for instant status validation before running workflows.
  - Configurable ping interval (--interval <minutes>, default: 10 mins).
  - Clean status reporting with timestamps and user details.

Usage:
  Continuous Keep-Alive Daemon (Run in a separate terminal or background process):
      python session_keeper.py

  Custom Interval (e.g. every 8 minutes):
      python session_keeper.py --interval 8

  Quick One-Shot Session Check:
      python session_keeper.py --check
"""

import os
import sys
import json
import time
import asyncio
import argparse
from datetime import datetime
from playwright.async_api import async_playwright

AUTH_STATE_FILE = "mcma_auth_state.json"
DASHBOARD_URL = "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/FrontExpert/"
DEFAULT_INTERVAL_MINUTES = 10

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def check_session_health(auth_file: str = AUTH_STATE_FILE, headless: bool = True) -> dict:
    """
    Performs a single health check against the MCMA platform.
    Returns:
        dict: {
            "valid": bool,
            "status_code": int or None,
            "user_name": str or None,
            "url": str,
            "message": str,
            "timestamp": str
        }
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not os.path.exists(auth_file):
        return {
            "valid": False,
            "status_code": None,
            "user_name": None,
            "url": "",
            "message": f"Auth file '{auth_file}' not found. Run 'python auth_setup.py' first.",
            "timestamp": ts,
        }

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context(storage_state=auth_file)
            page = await context.new_page()

            response = await page.goto(DASHBOARD_URL, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)

            current_url = page.url.lower()
            page_content = await page.content()

            # 1. Check for login page indicators
            is_login_page = (
                "login" in current_url
                or "expert_.phtml" in page_content
                or await page.locator("input[name='login'], #login, #password").count() > 0
            )

            if is_login_page:
                await browser.close()
                return {
                    "valid": False,
                    "status_code": response.status if response else None,
                    "user_name": None,
                    "url": page.url,
                    "message": "Session EXPIRED. Page redirected to Login. Run 'python auth_setup.py' to renew.",
                    "timestamp": ts,
                }

            # 2. Check for dashboard presence
            has_dashboard = (
                await page.locator("#formRecherche, #ReferenceCie, #Matricule, a[href*='logout'], a[href*='Login/logout']").count() > 0
                or "/expertise/" in current_url
                or "/frontexpert" in current_url
            )

            if not has_dashboard:
                await browser.close()
                return {
                    "valid": False,
                    "status_code": response.status if response else None,
                    "user_name": None,
                    "url": page.url,
                    "message": "Dashboard not reachable or unauthenticated. Run 'python auth_setup.py' to renew.",
                    "timestamp": ts,
                }

            # Extract active user name if present
            user_name = None
            try:
                user_el = page.locator("span.user-name, div.user-profile, a.dropdown-toggle:has(.fa-user), .username").first
                if await user_el.count() > 0:
                    user_name = (await user_el.inner_text()).strip()
            except Exception:
                pass

            # Save refreshed cookies/storage state back to file
            await context.storage_state(path=auth_file)
            await browser.close()

            return {
                "valid": True,
                "status_code": response.status if response else 200,
                "user_name": user_name,
                "url": page.url,
                "message": "Session ACTIVE and successfully refreshed.",
                "timestamp": ts,
            }

    except Exception as e:
        return {
            "valid": False,
            "status_code": None,
            "user_name": None,
            "url": "",
            "message": f"Connection error: {str(e)}",
            "timestamp": ts,
        }


async def run_daemon(interval_minutes: int = DEFAULT_INTERVAL_MINUTES, auth_file: str = AUTH_STATE_FILE):
    """
    Runs continuous keep-alive loop.
    """
    print("\n" + "=" * 70)
    print("  🛡️  MCMA SESSION KEEP-ALIVE DAEMON")
    print(f"  ⏱️  Ping Interval   : Every {interval_minutes} minutes")
    print(f"  🔑  Auth State File : {auth_file}")
    print(f"  🌐  Target URL      : {DASHBOARD_URL}")
    print("  👉  Press Ctrl+C to stop the daemon at any time.")
    print("=" * 70 + "\n")

    iteration = 1
    while True:
        now_str = datetime.now().strftime("%H:%M:%S")
        print(f"[{now_str}] [Heartbeat #{iteration}] Pinging MCMA dashboard to keep session alive...")

        health = await check_session_health(auth_file=auth_file, headless=True)

        if health["valid"]:
            user_info = f" (User: {health['user_name']})" if health["user_name"] else ""
            print(f"    [+] [{health['timestamp']}] MCMA Session OK{user_info} — Cookies refreshed & saved.")
        else:
            print(f"    [x] [{health['timestamp']}] WARNING: {health['message']}")
            print(f"    [!] Please run: python auth_setup.py to re-authenticate.")

        iteration += 1
        wait_seconds = interval_minutes * 60
        print(f"    [i] Next heartbeat in {interval_minutes} minutes... (Sleeping)\n")
        await asyncio.sleep(wait_seconds)


def main():
    parser = argparse.ArgumentParser(description="MCMA Session Keep-Alive Daemon & Health Checker")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Perform a quick one-shot session check and exit (exit code 0 if valid, 1 if expired).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_MINUTES,
        help=f"Heartbeat interval in minutes (default: {DEFAULT_INTERVAL_MINUTES}).",
    )
    parser.add_argument(
        "--auth-file",
        default=AUTH_STATE_FILE,
        help=f"Path to auth state file (default: {AUTH_STATE_FILE}).",
    )

    args = parser.parse_args()

    if args.check:
        print(f"[*] Checking MCMA session status in '{args.auth_file}'...")
        health = asyncio.run(check_session_health(auth_file=args.auth_file, headless=True))
        print("\n" + "=" * 60)
        print(f"  Timestamp   : {health['timestamp']}")
        print(f"  Valid       : {'YES [✓]' if health['valid'] else 'NO [X]'}")
        print(f"  Status Code : {health.get('status_code')}")
        print(f"  User        : {health.get('user_name') or 'N/A'}")
        print(f"  Message     : {health['message']}")
        print("=" * 60 + "\n")
        sys.exit(0 if health["valid"] else 1)

    try:
        asyncio.run(run_daemon(interval_minutes=args.interval, auth_file=args.auth_file))
    except KeyboardInterrupt:
        print("\n[!] Keep-Alive Daemon stopped by user.")


if __name__ == "__main__":
    main()
