"""Small operator menu for the modular MCMA agent."""

from __future__ import annotations

import glob
import os
import subprocess
import sys


def _dossiers() -> list[str]:
    return sorted(glob.glob(os.path.join("input_dossier", "*.json")))


def _choose_dossier() -> str:
    dossiers = _dossiers()
    if not dossiers:
        print("No JSON dossier found in input_dossier/.")
        return ""
    for index, path in enumerate(dossiers, 1):
        print(f"  {index}. {path}")
    answer = input("Select dossier number: ").strip()
    try:
        return dossiers[int(answer) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return ""


def _run(*arguments: str) -> None:
    subprocess.run([sys.executable, *arguments], check=False)


def main_menu() -> None:
    while True:
        print("\nMCMA ASSISTED DOSSIER FILLER")
        print("GED and all final validation actions are disabled.")
        print("1. Preview plan only")
        print("2. Fill form in browser (rubrique writes blocked)")
        print("3. Fill form + draft rubriques")
        print("4. Create/refresh MCMA login session")
        print("5. Run offline tests")
        print("0. Exit")
        choice = input("Choice: ").strip()
        if choice == "0":
            return
        if choice in {"1", "2", "3"}:
            dossier = _choose_dossier()
            if not dossier:
                continue
            command = ["run_dossier.py", "--json", dossier]
            if choice == "1":
                command.append("--plan-only")
            elif choice == "3":
                command.extend(["--rubric-mode", "draft", "--confirm-draft-writes"])
            _run(*command)
        elif choice == "4":
            _run("auth_setup.py")
        elif choice == "5":
            _run("-m", "unittest", "discover", "-v")
        else:
            print("Unknown option.")


if __name__ == "__main__":
    main_menu()
