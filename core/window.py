"""
core/window.py — Operating Window
==================================
The portal is unusable outside agency hours, and it gives no machine-readable
signal when it closes: after 18:00 it simply refuses authentication, which is
indistinguishable from a wrong password or a dead session. So the system does
not detect closure — it runs on a clock (PROJECT_ARCHITECTURE_BLUEPRINT.md §5).

Timezone is a correctness requirement, not tidiness. Morocco observes UTC+1
year-round EXCEPT during Ramadan, when it drops to UTC+0 and returns afterwards.
A window computed from naive local time silently shifts by an hour once a year,
and the shift lands in the busiest period. All arithmetic goes through a real
Africa/Casablanca zone.
"""

import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Set

TIMEZONE_NAME = "Africa/Casablanca"

# Defaults; overridable from the environment so the agency can change hours
# without a code edit (§5: "operating hours are configuration, not code").
DEFAULT_START = "07:45"
DEFAULT_END = "18:00"
DEFAULT_DAYS = "0,1,2,3,4,5"          # Mon=0 .. Sun=6; Saturday included by default
DEFAULT_POLL_INTERVAL_MINUTES = 5
DEFAULT_SESSION_WARNING = "17:00"


def _zone():
    """
    Returns the Africa/Casablanca zone, or a fixed UTC+1 fallback.

    On Windows the IANA database is not bundled; the `tzdata` package supplies
    it. If it is missing we fall back to a fixed offset and say so, rather than
    silently using naive local time.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE_NAME)
    except Exception:
        return timezone(timedelta(hours=1), "UTC+01 (fallback)")


TZ = _zone()


def using_fallback_timezone() -> bool:
    """True when the real IANA zone was unavailable (install `tzdata`)."""
    return not hasattr(TZ, "key")


def _parse_time(value: str, default: str) -> time:
    raw = (value or default).strip()
    try:
        hh, mm = raw.split(":")
        return time(int(hh), int(mm))
    except Exception:
        hh, mm = default.split(":")
        return time(int(hh), int(mm))


def _parse_days(value: str) -> Set[int]:
    try:
        return {int(x) for x in (value or DEFAULT_DAYS).split(",") if x.strip() != ""}
    except Exception:
        return {int(x) for x in DEFAULT_DAYS.split(",")}


@dataclass(frozen=True)
class OperatingWindow:
    start: time
    end: time
    days: Set[int]
    poll_interval_minutes: int
    session_warning: time

    @classmethod
    def from_env(cls) -> "OperatingWindow":
        return cls(
            start=_parse_time(os.environ.get("MCMA_WINDOW_START", ""), DEFAULT_START),
            end=_parse_time(os.environ.get("MCMA_WINDOW_END", ""), DEFAULT_END),
            days=_parse_days(os.environ.get("MCMA_WINDOW_DAYS", "")),
            poll_interval_minutes=int(
                os.environ.get("MCMA_POLL_INTERVAL_MINUTES", DEFAULT_POLL_INTERVAL_MINUTES)
            ),
            session_warning=_parse_time(
                os.environ.get("MCMA_SESSION_WARNING", ""), DEFAULT_SESSION_WARNING
            ),
        )

    def now(self) -> datetime:
        return datetime.now(TZ)

    def is_open(self, at: Optional[datetime] = None) -> bool:
        at = at or self.now()
        if at.weekday() not in self.days:
            return False
        return self.start <= at.time() < self.end

    def should_warn_sessions(self, at: Optional[datetime] = None) -> bool:
        """
        True inside the last stretch of the day, when an unhealthy session should
        be flagged while somebody with the credentials and the phone is still in
        the building. After close, the only remedy is tomorrow morning.
        """
        at = at or self.now()
        if at.weekday() not in self.days:
            return False
        return self.session_warning <= at.time() < self.end

    def next_open(self, at: Optional[datetime] = None) -> datetime:
        """The next moment the window opens. Used for the closed-state banner."""
        at = at or self.now()
        candidate = at.replace(
            hour=self.start.hour, minute=self.start.minute, second=0, microsecond=0
        )
        if candidate <= at or at.weekday() not in self.days:
            candidate = candidate + timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in self.days:
                return candidate
            candidate = candidate + timedelta(days=1)
        return candidate

    def status(self, at: Optional[datetime] = None) -> dict:
        at = at or self.now()
        is_open = self.is_open(at)
        payload = {
            "open": is_open,
            "now": at.isoformat(timespec="seconds"),
            "opens_at": self.start.strftime("%H:%M"),
            "closes_at": self.end.strftime("%H:%M"),
            "timezone": TIMEZONE_NAME,
            "timezone_fallback": using_fallback_timezone(),
            "poll_interval_minutes": self.poll_interval_minutes,
        }
        if not is_open:
            payload["next_open"] = self.next_open(at).isoformat(timespec="seconds")
            payload["message"] = (
                f"Portail MAMDA/MCMA fermé — reprise à {self.start.strftime('%H:%M')}."
            )
        return payload


WINDOW = OperatingWindow.from_env()
