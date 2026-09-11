"""Config flow for DxHyve Smart Irrigation.

Step 1 (user): Integration-level settings — weather entities, location.
Step 2 (zone): First zone settings — soil, vegetation, sprinkler, slope, sunlight.
OptionsFlow: Add zones, and view/edit existing zones, after initial setup.
Reconfigure: Edit integration-level settings.

Zone configuration is stored in config_entry.options keyed by zone_id.
Integration-level settings (weather entities, latitude) are stored in config_entry.data.
"""
import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    KMC_TABLE,
    SOIL_PARAMS,
    SPRINKLER_PARAMS,
    VEGETATION_PARAMS,
)

_LOGGER = logging.getLogger(__name__)

# ── Human-readable labels for select options ──────────────────────────────────

_SOIL_OPTIONS = [
    {"value": "sand",       "label": "Sand"},
    {"value": "sandy_loam", "label": "Sandy Loam"},
    {"value": "loam",       "label": "Loam"},
    {"value": "clay_loam",  "label": "Clay Loam"},
    {"value": "clay",       "label": "Clay"},
]

_VEGETATION_OPTIONS = [
    {"value": "cool_turf",         "label": "Cool Season Turf"},
    {"value": "warm_turf",         "label": "Warm Season Turf"},
    {"value": "annuals",           "label": "Annuals / Vegetables"},
    {"value": "shrubs_perennials", "label": "Shrubs & Perennials"},
    {"value": "trees",             "label": "Trees"},
]

_SPRINKLER_OPTIONS = [
    {"value": "spray",      "label": "Spray Head"},
    {"value": "rotor",      "label": "Rotor"},
    {"value": "rotary",     "label": "Rotary Nozzle"},
    {"value": "impact",     "label": "Impact / Impulse"},
    {"value": "oscillator", "label": "Oscillating"},
    {"value": "drip",       "label": "Drip / Soaker"},
]

_SUNLIGHT_OPTIONS = [
    {"value": "lt_2hrs",  "label": "< 2 hours/day (deep shade)"},
    {"value": "2_4hrs",   "label": "2–4 hours/day (part shade)"},
    {"value": "4_6hrs",   "label": "4–6 hours/day (part sun)"},
    {"value": "6_8hrs",   "label": "6–8 hours/day (full sun)"},
    {"value": "8_10hrs",  "label": "8–10 hours/day (intense sun)"},
    {"value": "gt_10hrs", "label": "> 10 hours/day (very intense)"},
]

_SLOPE_OPTIONS = [
    {"value": "flat",     "label": "Flat (< 3%)"},
    {"value": "gentle",   "label": "Gentle (3–8%)"},
    {"value": "moderate", "label": "Moderate (8–12%)"},
    {"value": "steep",    "label": "Steep (> 12%)"},
]

_ODD_EVEN_OPTIONS = [
    {"value": "none", "label": "No restriction"},
    {"value": "odd",  "label": "Odd days only"},
    {"value": "even", "label": "Even days only"},
]

_WATERING_MODE_OPTIONS = [
    {"value": "blended",    "label": "Blended (ET + rain forecast)"},
    {"value": "efficiency", "label": "Efficiency (ET only)"},
    {"value": "seeded",     "label": "Seeded lawn mode"},
]


# ── Schema builders ───────────────────────────────────────────────────────────

def _integration_schema(default_latitude: float) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("weather_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Optional("rain_gauge_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="precipitation"
                )
            ),
            vol.Optional("temperature_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="temperature"
                )
            ),
            vol.Optional("humidity_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="humidity"
                )
            ),
            vol.Optional("wind_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="wind_speed"
                )
            ),
            vol.Optional("solar_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class="irradiance"
                )
            ),
            vol.Required("latitude", default=default_latitude): vol.Coerce(float),
        }
    )


ZONE_SCHEMA = vol.Schema(
    {
        vol.Required("zone_name"): str,
        vol.Required("zone_short_name"): vol.All(str, vol.Length(max=6)),
        # Accepts both: BHyve hose timers expose as `switch`, but native HA
        # valves (and other zone hardware) use the `valve` domain. Phase 2's
        # valve-control code will need to branch on the entity's domain to
        # call switch.turn_on/off vs valve.open_valve/close_valve.
        vol.Required("valve_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["switch", "valve"])
        ),
        vol.Optional("water_sensor_entity"): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor", device_class="water"
            )
        ),
        vol.Required("soil_type", default="loam"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_SOIL_OPTIONS)
        ),
        vol.Required("vegetation_type", default="cool_turf"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_VEGETATION_OPTIONS)
        ),
        vol.Required("sprinkler_type", default="spray"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_SPRINKLER_OPTIONS)
        ),
        vol.Required("sunlight", default="6_8hrs"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_SUNLIGHT_OPTIONS)
        ),
        vol.Required("slope", default="flat"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_SLOPE_OPTIONS)
        ),
        vol.Required("percent_of_rain", default=80): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=5, mode="slider")
        ),
        vol.Required("odd_even", default="none"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_ODD_EVEN_OPTIONS)
        ),
        vol.Required("watering_mode", default="blended"): selector.SelectSelector(
            selector.SelectSelectorConfig(options=_WATERING_MODE_OPTIONS)
        ),
        # Advanced overrides — shown collapsed in UI
        vol.Optional("ar_override"): vol.Coerce(float),
        vol.Optional("e_override"): vol.All(
            vol.Coerce(float), vol.Range(min=50, max=100)
        ),
        vol.Optional("kp_override"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=1.4)
        ),
        vol.Optional("kmc_override"): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=1.4)
        ),
        vol.Optional("mad", default=0.50): vol.All(
            vol.Coerce(float), vol.Range(min=0.20, max=0.70)
        ),
        vol.Optional("rz_override"): vol.Coerce(float),
        vol.Optional("zone_area_sqft"): vol.Coerce(float),
        vol.Optional("zone_priority", default=1): vol.Coerce(int),
    }
)


# ── Config flow ───────────────────────────────────────────────────────────────

class DxHyveIrrigationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow for DxHyve Smart Irrigation."""

    VERSION = 1

    def __init__(self) -> None:
        self._integration_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 1: Integration-level settings."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            self._integration_data = user_input
            return await self.async_step_zone()

        return self.async_show_form(
            step_id="user",
            data_schema=_integration_schema(self.hass.config.latitude),
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Step 2: First zone settings."""
        if user_input is not None:
            zone_id = f"zone_{uuid.uuid4().hex[:8]}"
            return self.async_create_entry(
                title="DxHyve Smart Irrigation",
                data=self._integration_data,
                options={zone_id: user_input},
            )

        return self.async_show_form(
            step_id="zone",
            data_schema=ZONE_SCHEMA,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Allow editing integration-level settings after setup."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates=user_input,
                reason="reconfigure_successful",
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _integration_schema(
                    entry.data.get("latitude", self.hass.config.latitude)
                ),
                entry.data,
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return DxHyveIrrigationOptionsFlow()


# ── Options flow ──────────────────────────────────────────────────────────────

class DxHyveIrrigationOptionsFlow(config_entries.OptionsFlow):
    """Handle options — add and edit zones after initial setup."""

    def __init__(self) -> None:
        self._editing_zone_id: str | None = None

    def _zones(self) -> dict[str, dict]:
        return {
            zone_id: zone_cfg
            for zone_id, zone_cfg in self.config_entry.options.items()
            if isinstance(zone_cfg, dict) and "soil_type" in zone_cfg
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Options menu."""
        if user_input is not None:
            if user_input.get("action") == "add_zone":
                return await self.async_step_add_zone()
            if user_input.get("action") == "edit_zone":
                return await self.async_step_select_zone()

        actions = [{"value": "add_zone", "label": "Add a new zone"}]
        if self._zones():
            actions.append({"value": "edit_zone", "label": "Edit an existing zone"})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="add_zone"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=actions)
                    )
                }
            ),
        )

    async def async_step_add_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Add a new zone to the integration."""
        if user_input is not None:
            zone_id = f"zone_{uuid.uuid4().hex[:8]}"
            current_options = dict(self.config_entry.options)
            current_options[zone_id] = user_input
            return self.async_create_entry(title="", data=current_options)

        return self.async_show_form(
            step_id="add_zone",
            data_schema=ZONE_SCHEMA,
        )

    async def async_step_select_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Pick which existing zone to view/edit."""
        zones = self._zones()

        if user_input is not None:
            self._editing_zone_id = user_input["zone_id"]
            return await self.async_step_edit_zone()

        zone_options = [
            {"value": zone_id, "label": zone_cfg.get("zone_name", zone_id)}
            for zone_id, zone_cfg in zones.items()
        ]
        return self.async_show_form(
            step_id="select_zone",
            data_schema=vol.Schema(
                {
                    vol.Required("zone_id"): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=zone_options)
                    )
                }
            ),
        )

    async def async_step_edit_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """View and update settings for the selected zone."""
        zone_id = self._editing_zone_id
        current_options = dict(self.config_entry.options)

        if user_input is not None:
            current_options[zone_id] = user_input
            return self.async_create_entry(title="", data=current_options)

        return self.async_show_form(
            step_id="edit_zone",
            data_schema=self.add_suggested_values_to_schema(
                ZONE_SCHEMA, current_options.get(zone_id, {})
            ),
            description_placeholders={
                "zone_name": current_options.get(zone_id, {}).get("zone_name", zone_id)
            },
        )
