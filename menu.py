"""
menu.py — Interactive MCMA Agent Dashboard Menu
=================================================
Simple visual terminal menu to guide you through setting up,
logging in, and running the MCMA Dossier Automation Agent.

Usage:
    python menu.py
"""

import os
import sys
import glob
import subprocess

_INC00_CONTAINMENT_MSG = (
    "Baseline live-write capability was permanently removed at INC-00; "
    "the only live-write path is the post-G5 VerifiedMissionWriter."
)

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def check_status():
    auth_ok = os.path.exists("mcma_auth_state.json")
    
    jsons = glob.glob("input_dossier/*.json") + glob.glob("input_dossier/*.md")
    json_count = len(jsons)
    
    pdfs = glob.glob("input_documents/*.pdf")
    pdf_count = len(pdfs)
    
    return auth_ok, json_count, pdf_count

def print_header():
    auth_ok, json_count, pdf_count = check_status()
    
    print("=" * 65)
    print("      🚗  MCMA / MAMDA DOSSIER AUTOMATION AGENT  🚗")
    print("=" * 65)
    
    auth_badge = "[✓ CONNECTED / READY]" if auth_ok else "[X NOT LOGGED IN - Run Option 2]"
    print(f"  • Auth Status  : {auth_badge}")
    print(f"  • Input JSON   : {json_count} file(s) in 'input_dossier/'")
    print(f"  • Input PDFs   : {pdf_count} file(s) in 'input_documents/'")
    print("=" * 65)

def main_menu():
    while True:
        clear()
        print_header()
        print("\n  [MENU OPTIONS]:\n")
        print("  1. ⛔ Remplissage de dossier DESACTIVE (confinement permanent INC-00)")
        print("  2. 🔑 One-Time Login (Setup session & save SMS/OTP code)")
        print("  3. 🔍 Test JSON Mapping (Preview mapped fields without opening browser)")
        print("  4. 📁 View Files in Input Folders (JSON & PDFs)")
        print("  5. 🌐 Start FastAPI Web Server (For remote API integration)")
        print("  6. 📦 Install Dependencies (Run setup on new PC)")
        print("  0. ❌ Exit")
        print("\n" + "-" * 65)
        
        choice = input("  Select an option [0-6]: ").strip()
        
        if choice == "1":
            clear()
            print("  [X] Option definitivement desactivee (confinement INC-00) :")
            print("  " + _INC00_CONTAINMENT_MSG)
            input("\nPress Enter to return to menu...")
            
        elif choice == "2":
            clear()
            print("[*] Launching MCMA Login Window...\n")
            subprocess.run([sys.executable, "auth_setup.py"])
            input("\nPress Enter to return to menu...")
            
        elif choice == "3":
            clear()
            jsons = glob.glob("input_dossier/*.json") + glob.glob("input_dossier/*.md")
            if not jsons:
                print("[!] No JSON dossier found in 'input_dossier/'.")
            else:
                target_json = jsons[0]
                print(f"[*] Previewing mapped fields for: {target_json}\n")
                subprocess.run([sys.executable, "mapper.py", target_json])
            input("\nPress Enter to return to menu...")
            
        elif choice == "4":
            clear()
            print("=" * 55)
            print("  📂 FILES IN INPUT FOLDERS")
            print("=" * 55)
            print("\n[input_dossier/]:")
            for f in glob.glob("input_dossier/*"):
                print(f"  • {os.path.basename(f)} ({os.path.getsize(f)/1024:.1f} KB)")
                
            print("\n[input_documents/]:")
            for f in glob.glob("input_documents/*"):
                print(f"  • {os.path.basename(f)} ({os.path.getsize(f)/1024:.1f} KB)")
            print("=" * 55)
            input("\nPress Enter to return to menu...")
            
        elif choice == "5":
            clear()
            print("[*] Starting FastAPI Server on http://127.0.0.1:8000 ...\n")
            print("Press Ctrl+C to stop the server and return to menu.\n")
            try:
                subprocess.run([sys.executable, "main.py"])
            except KeyboardInterrupt:
                pass
            input("\nPress Enter to return to menu...")
            
        elif choice == "6":
            clear()
            print("[*] Installing all dependencies and Playwright Chromium...\n")
            subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
            input("\nInstallation complete. Press Enter to return to menu...")
            
        elif choice == "0":
            print("\nExiting. Goodbye!\n")
            sys.exit(0)
        else:
            input("\nInvalid option. Press Enter to try again...")

if __name__ == "__main__":
    main_menu()
