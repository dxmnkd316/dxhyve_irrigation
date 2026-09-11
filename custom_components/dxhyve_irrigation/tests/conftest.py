"""Minimal Home Assistant stubs so coordinator.py can be imported and unit
tested without the real `homeassistant` package installed.

Only the small surface actually touched by coordinator.py / state_store.py
is stubbed — this is not a HA test harness, just enough to exercise the
rain-gauge delta logic in isolation.
"""
import sys
import types


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # noqa: D101
        pass

    def callback(func):  # noqa: D103
        return func

    core.HomeAssistant = HomeAssistant
    core.callback = callback

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:  # noqa: D101
        pass

    config_entries.ConfigEntry = ConfigEntry

    helpers = types.ModuleType("homeassistant.helpers")

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:  # noqa: D101
        def __init__(self, hass, logger, name=None, update_interval=None):
            self.hass = hass
            self.logger = logger
            self.name = name
            self.update_interval = update_interval

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator

    storage = types.ModuleType("homeassistant.helpers.storage")

    class Store:  # noqa: D101
        def __init__(self, hass, version, key):
            self._hass = hass
            self._version = version
            self._key = key

        async def async_load(self):
            return None

        async def async_save(self, data):
            return None

    storage.Store = Store

    util = types.ModuleType("homeassistant.util")
    dt_util = types.ModuleType("homeassistant.util.dt")

    import datetime as _datetime

    def now():
        return _datetime.datetime.now()

    dt_util.now = now
    util.dt = dt_util

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.helpers.storage"] = storage
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt_util


_install_ha_stubs()
