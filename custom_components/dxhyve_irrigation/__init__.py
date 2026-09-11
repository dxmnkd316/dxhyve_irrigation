"""DxHyve Smart Irrigation — Home Assistant custom integration.

Controls BHyve hose timer valves using evapotranspiration-based scheduling.
Computes soil moisture balance per zone using the SWAT/WaterSense water
balance method with Hargreaves-Samani ETo as the primary calculation fallback.

Phase 1: ET calculations, moisture balance sensors.
Phase 2 (future): Valve control, scheduling, rain forecast, calendar.
Phase 3 (future): Seeded mode, services, HACS metadata.
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import IrrigationCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DxHyve Smart Irrigation from a config entry."""
    coordinator = IrrigationCoordinator(hass, entry)
    await coordinator.async_setup()

    # Initial data fetch — blocks setup until we have data or fail gracefully
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-run coordinator when options (zone config) change
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info("DxHyve Smart Irrigation set up successfully")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("DxHyve Smart Irrigation unloaded")
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options (zone config) are updated."""
    _LOGGER.debug("Options updated — reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)
