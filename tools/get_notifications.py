"""
get_notifications.py — MCMA Alerts & Notifications CLI Tool
============================================================
Extracts all active alerts, categories, and their complete claim datatables
from the MCMA portal and exports them to structured JSON.

Usage:
  Basic run (visible browser):
      python get_notifications.py

  Headless run:
      python get_notifications.py --headless

  Custom JSON Output:
      python get_notifications.py --output my_alerts.json
"""

import os
import sys
import json
import asyncio
import argparse
from playwright.async_api import async_playwright
from core.config import AUTH_STATE_FILE, LOGS_DIR
from browser.notifications import fetch_all_notifications

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


async def run(output_file: str = None, headless: bool = False):
    if not os.path.exists(AUTH_STATE_FILE):
        print("\n" + "=" * 70)
        print(f"  ❌ Auth file '{AUTH_STATE_FILE}' not found.")
        print("  👉 Please run:  python auth_setup.py  first to log in.")
        print("=" * 70 + "\n")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  🔔  MCMA NOTIFICATIONS & ALERTS EXTRACTOR")
    print(f"  🔑  Auth State File : {AUTH_STATE_FILE}")
    print(f"  🌐  Browser Mode    : {'Headless' if headless else 'Visible'}")
    print("=" * 70 + "\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(storage_state=AUTH_STATE_FILE)
        page = await context.new_page()

        try:
            data = await fetch_all_notifications(page, headless=headless)

            # Determine output file
            if not output_file:
                os.makedirs(LOGS_DIR, exist_ok=True)
                output_file = os.path.join(LOGS_DIR, "mcma_notifications.json")

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print("=" * 70)
            print(f"  ✅ Extraction Complete!")
            print(f"  📊 Total Categories : {data['total_categories']}")
            print(f"  📝 Total Alerts     : {data['total_alerts']}")
            print(f"  📁 Output Saved To  : {output_file}")
            print("=" * 70 + "\n")

        finally:
            await browser.close()


def main():
    parser = argparse.ArgumentParser(description="MCMA Alerts & Notifications Extractor")
    parser.add_argument("--output", "-o", help="Path to save output JSON (default: logs/mcma_notifications.json)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default: visible)")
    args = parser.parse_args()

    asyncio.run(run(output_file=args.output, headless=args.headless))


if __name__ == "__main__":
    main()
