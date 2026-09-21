"""Persisted state for Log Doctor: last scan time and which signatures have
already been reported.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_VERSION


@dataclass
class SeenSignature:
    """Bookkeeping for a signature we've already reported before."""

    first_reported: datetime
    last_seen: datetime
    times_reported: int = 1


@dataclass
class LogDoctorData:
    """In-memory representation of the persisted store."""

    last_scan: datetime | None = None
    seen_signatures: dict[str, SeenSignature] = field(default_factory=dict)
    auto_investigate: bool = True


class LogDoctorStore:
    """Wrapper around a Home Assistant Store for Log Doctor's persisted state."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, f"log_doctor.{entry_id}")
        self.data = LogDoctorData()

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not raw:
            return

        last_scan = raw.get("last_scan")
        self.data.last_scan = datetime.fromisoformat(last_scan) if last_scan else None

        self.data.seen_signatures = {
            sig: SeenSignature(
                first_reported=datetime.fromisoformat(v["first_reported"]),
                last_seen=datetime.fromisoformat(v["last_seen"]),
                times_reported=v.get("times_reported", 1),
            )
            for sig, v in raw.get("seen_signatures", {}).items()
        }
        self.data.auto_investigate = raw.get("auto_investigate", True)

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "last_scan": self.data.last_scan.isoformat() if self.data.last_scan else None,
                "seen_signatures": {
                    sig: {
                        "first_reported": s.first_reported.isoformat(),
                        "last_seen": s.last_seen.isoformat(),
                        "times_reported": s.times_reported,
                    }
                    for sig, s in self.data.seen_signatures.items()
                },
                "auto_investigate": self.data.auto_investigate,
            }
        )

    async def async_clear_history(self) -> None:
        # Preserve the auto-investigate switch across a history clear - it's
        # a user preference, not scan/signature bookkeeping.
        self.data = LogDoctorData(auto_investigate=self.data.auto_investigate)
        await self.async_save()

    def mark_signature_seen(self, signature: str, when: datetime) -> bool:
        """Record a signature as seen; return True if this is the first time ever."""
        existing = self.data.seen_signatures.get(signature)
        if existing is None:
            self.data.seen_signatures[signature] = SeenSignature(
                first_reported=when, last_seen=when
            )
            return True
        existing.last_seen = when
        existing.times_reported += 1
        return False

    def prune(self, max_age: timedelta) -> None:
        """Drop signatures not seen in a long time, to bound storage size.

        Log entry timestamps (and therefore `last_seen`) are naive,
        local-time values as written by Home Assistant's log formatter, so
        "now" here is deliberately naive too rather than UTC-aware.
        """
        now = datetime.now()
        self.data.seen_signatures = {
            sig: s
            for sig, s in self.data.seen_signatures.items()
            if now - s.last_seen < max_age
        }
