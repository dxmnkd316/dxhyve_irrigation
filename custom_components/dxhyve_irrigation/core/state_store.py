"""Persistent state storage for DxHyve Smart Irrigation.

Uses HA's .storage mechanism (not the recorder database).

Storage layout per zone:
  dc_start   — Dc at the beginning of today (set at midnight rollover)
  dc_current — Last computed live Dc (updated every 15 min, used to seed dc_start on restart)

Zone params are NOT stored — they are recomputed from config on every update.
"""
import logging

from homeassistant.helpers.storage import Store

from ..const import STORAGE_KEY, STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)


class IrrigationStateStore:
    """Manages persistent state for the irrigation integration."""

    def __init__(self, hass) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict = {}

    async def async_load(self) -> None:
        """Load state from .storage. Call once on coordinator startup."""
        data = await self._store.async_load()
        if data is None:
            _LOGGER.debug("No existing state found — starting fresh")
            self._data = {"zones": {}, "integration": {}}
        else:
            _LOGGER.debug("Loaded state from storage")
            self._data = data
            # Migrate legacy dc_current-only storage (no dc_start key)
            for zone_id, zone in self._data.get("zones", {}).items():
                if "dc_current" in zone and "dc_start" not in zone:
                    zone["dc_start"] = zone["dc_current"]
                    _LOGGER.debug("Migrated zone %s: dc_current → dc_start", zone_id)

    async def async_save(self) -> None:
        """Persist current state to .storage."""
        await self._store.async_save(self._data)

    # ── Zone: day-start Dc (baseline for live computation) ──────────────────

    def get_zone_dc_start(self, zone_id: str, paw: float) -> float:
        """Return the Dc baseline at the start of today (inches).

        On first run, defaults to 50% of PAW (moderately dry starting condition).
        """
        zone = self._data["zones"].get(zone_id, {})
        return zone.get("dc_start", paw * 0.50)

    def set_zone_dc_start(self, zone_id: str, dc: float) -> None:
        """Store the Dc baseline at the start of today."""
        self._ensure_zone(zone_id)
        self._data["zones"][zone_id]["dc_start"] = round(dc, 4)

    # ── Zone: live Dc (written every 15 min for restart recovery) ───────────

    def get_zone_dc_current(self, zone_id: str, paw: float) -> float:
        """Return the last persisted live Dc value (inches).

        Falls back to dc_start, then 50% PAW.
        """
        zone = self._data["zones"].get(zone_id, {})
        if "dc_current" in zone:
            return zone["dc_current"]
        return zone.get("dc_start", paw * 0.50)

    def set_zone_dc_current(self, zone_id: str, dc: float) -> None:
        """Store the current live Dc value."""
        self._ensure_zone(zone_id)
        self._data["zones"][zone_id]["dc_current"] = round(dc, 4)

    def rollover_zone_dc(self, zone_id: str, paw: float) -> None:
        """Midnight rollover: promote dc_current → dc_start for the new day."""
        dc = self.get_zone_dc_current(zone_id, paw)
        self._ensure_zone(zone_id)
        self._data["zones"][zone_id]["dc_start"] = round(dc, 4)
        _LOGGER.debug("Zone %s rollover: dc_start = %.4f", zone_id, dc)

    # ── Zone: last irrigation tracking ──────────────────────────────────────

    def get_zone_last_irrigated(self, zone_id: str):
        """Return ISO date string of last irrigation, or None."""
        return self._data["zones"].get(zone_id, {}).get("last_irrigated")

    def set_zone_last_irrigated(self, zone_id: str, date_str: str) -> None:
        """Store ISO date string of last irrigation."""
        self._ensure_zone(zone_id)
        self._data["zones"][zone_id]["last_irrigated"] = date_str

    # ── Integration-level: daily rollover tracking ───────────────────────────

    def get_last_dc_rollover_date(self) -> str | None:
        """Return ISO date string of last midnight Dc rollover, or None."""
        return self._data["integration"].get("last_dc_rollover_date")

    def set_last_dc_rollover_date(self, date_str: str) -> None:
        """Store ISO date string of last midnight Dc rollover."""
        self._data["integration"]["last_dc_rollover_date"] = date_str

    # ── Integration-level: rain gauge delta tracking ─────────────────────────

    def get_rain_gauge_day_start(self) -> tuple[float | None, str | None]:
        """Return (raw_value_at_day_start, iso_date_string) for rain delta tracking."""
        ig = self._data["integration"]
        return ig.get("rain_gauge_day_start"), ig.get("rain_gauge_day_start_date")

    def set_rain_gauge_day_start(self, value: float, date_str: str) -> None:
        """Capture today's opening rain gauge reading for delta calculation."""
        self._data["integration"]["rain_gauge_day_start"] = round(value, 4)
        self._data["integration"]["rain_gauge_day_start_date"] = date_str

    # ── Internal ─────────────────────────────────────────────────────────────

    def _ensure_zone(self, zone_id: str) -> None:
        if zone_id not in self._data["zones"]:
            self._data["zones"][zone_id] = {}
