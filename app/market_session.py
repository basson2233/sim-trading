"""US equity market session clock (America/New_York).

Sessions (half-open intervals in Eastern Time):
  PRE    04:00–09:30
  RTH    09:30–16:00  (regular trading hours)
  AFTER  16:00–20:00
  CLOSED otherwise, including weekends

Overnight / 24h futures-style trading is NOT supported.
US holidays are treated as CLOSED only when they fall on weekdays outside
the hours above; a full holiday calendar is intentionally omitted for now
(weekends are enforced).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

SESSION_PRE = "PRE"
SESSION_RTH = "RTH"
SESSION_AFTER = "AFTER"
SESSION_CLOSED = "CLOSED"
SESSIONS = (SESSION_PRE, SESSION_RTH, SESSION_AFTER, SESSION_CLOSED)

# Half-open [start, end)
_PRE_START = time(4, 0)
_RTH_START = time(9, 30)
_AFTER_START = time(16, 0)
_AFTER_END = time(20, 0)


@dataclass(frozen=True)
class MarketSessionInfo:
    session: str
    exchange_tz: str
    server_time_et: str
    extended_hours_supported: bool
    overnight_supported: bool

    def to_dict(self) -> dict:
        return {
            "session": self.session,
            "exchange_tz": self.exchange_tz,
            "server_time_et": self.server_time_et,
            "extended_hours_supported": self.extended_hours_supported,
            "overnight_supported": self.overnight_supported,
        }


def now_et(when: Optional[datetime] = None) -> datetime:
    """Return `when` (or wall clock) as timezone-aware America/New_York."""
    if when is None:
        return datetime.now(ET)
    if when.tzinfo is None:
        return when.replace(tzinfo=ET)
    return when.astimezone(ET)


def session_at(when: Optional[datetime] = None) -> str:
    """Classify US equity session for a given moment (default: now).

    If ``SIM_FORCE_SESSION`` is set to PRE|RTH|AFTER|CLOSED and ``when`` is
    omitted, return that value (used by unit tests so MARKET orders are stable).
    """
    if when is None:
        forced = (os.environ.get("SIM_FORCE_SESSION") or "").strip().upper()
        if forced in SESSIONS:
            return forced
    dt = now_et(when)
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return SESSION_CLOSED
    # Compare as naive local time-of-day in ET
    tod = time(dt.hour, dt.minute, dt.second, dt.microsecond)
    if _PRE_START <= tod < _RTH_START:
        return SESSION_PRE
    if _RTH_START <= tod < _AFTER_START:
        return SESSION_RTH
    if _AFTER_START <= tod < _AFTER_END:
        return SESSION_AFTER
    return SESSION_CLOSED


def is_extended(session: Optional[str] = None, when: Optional[datetime] = None) -> bool:
    s = session or session_at(when)
    return s in (SESSION_PRE, SESSION_AFTER)


def is_open_for_matching(session: Optional[str] = None, when: Optional[datetime] = None) -> bool:
    """True when resting limits may be matched (PRE / RTH / AFTER)."""
    s = session or session_at(when)
    return s in (SESSION_PRE, SESSION_RTH, SESSION_AFTER)


def market_session_info(when: Optional[datetime] = None) -> MarketSessionInfo:
    dt = now_et(when)
    return MarketSessionInfo(
        session=session_at(dt),
        exchange_tz="America/New_York",
        server_time_et=dt.isoformat(timespec="seconds"),
        extended_hours_supported=True,
        overnight_supported=False,
    )


def allow_market_orders(session: Optional[str] = None, when: Optional[datetime] = None,
                        force_extended: bool = False) -> bool:
    """Market orders only during regular hours, and never when client asks for extended."""
    if force_extended:
        return False
    s = session or session_at(when)
    return s == SESSION_RTH
