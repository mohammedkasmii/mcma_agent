"""
core/logger.py — Structured JSON Diagnostic Logger
===================================================
Produces timestamped JSON execution logs (logs/*.json) and captures screenshots
at critical checkpoints with safe console output for Windows terminals.
"""

import os
import sys
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from core.config import LOGS_DIR, SCREENSHOTS_DIR

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class StructuredLogger:
    """
    Unified structured JSON logger for MCMA workflows (Normal and Conventionné).
    Logs every action with timestamps, elapsed time, status, details, and optional extra data.
    """

    def __init__(self, prefix: str = "workflow", log_dir: str = LOGS_DIR):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(self.log_dir, f"{prefix}_{ts}.json")
        self.entries: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self._write()

    def log(self, step: str, status: str, detail: str, extra: Optional[Dict[str, Any]] = None):
        """Add a log entry and flush to disk."""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "elapsed_s": round(time.time() - self.start_time, 2),
            "step": step,
            "status": status,
            "detail": detail,
        }
        if extra:
            entry["extra"] = extra
        self.entries.append(entry)
        self._write()

        # Safe ASCII indicators for Windows console
        icon = {"OK": "+", "ERROR": "x", "WARN": "!", "INFO": "i"}.get(status, ".")
        try:
            print(f"    [{icon}] [{step}] {detail}")
        except Exception:
            pass

    def _write(self):
        """Persist log to disk immediately."""
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(self.entries, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def summary(self) -> Dict[str, Any]:
        """Return a summary dictionary of execution stats."""
        ok = sum(1 for e in self.entries if e["status"] == "OK")
        err = sum(1 for e in self.entries if e["status"] == "ERROR")
        warn = sum(1 for e in self.entries if e["status"] == "WARN")
        return {
            "log_file": self.log_path,
            "total_steps": len(self.entries),
            "ok": ok,
            "errors": err,
            "warnings": warn,
        }


async def capture_screenshot(page, logger: StructuredLogger, label: str) -> Optional[str]:
    """Capture a screenshot and log its creation."""
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%H%M%S")
        path = os.path.join(SCREENSHOTS_DIR, f"{label}_{ts}.png")
        await page.screenshot(path=path, full_page=False)
        logger.log("SCREENSHOT", "INFO", f"Saved screenshot: {path}")
        return path
    except Exception as e:
        logger.log("SCREENSHOT", "WARN", f"Could not save screenshot: {e}")
        return None
