"""Sensor platform for DxHyve Smart Irrigation.

Exposes per-zone and integration-level sensors. All entities inherit from
CoordinatorEntity so they update automatically when the coordinator pushes new data.
"""
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IrrigationCoordinator

_LOGGER = logging.getLogger(__name__)

# Unit constants not in homeassistant.const for older versions
UNIT_INCHES = "in"
UNIT_INCHES_PER_DAY = "in/day"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DxHyve irrigation sensors from a config entry."""
    coordinator: IrrigationCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list = [
        IrrigationEtoSensor(coordinator),
        IrrigationRainTodaySensor(coordinator),
    ]

    # One set of per-zone sensors for each configured zone
    zone_configs = {
        k: v
        for k, v in config_entry.options.items()
        if isinstance(v, dict) and "soil_type" in v
    }
    for zone_id, zone_cfg in zone_configs.items():
        zone_name = zone_cfg.get("zone_name", zone_id)
        entities.extend(
            [
                IrrigationZoneMoistureSensor(coordinator, zone_id, zone_name),
                IrrigationZoneDeficitSensor(coordinator, zone_id, zone_name),
                IrrigationZoneEtlSensor(coordinator, zone_id, zone_name),
                IrrigationZonePawSensor(coordinator, zone_id, zone_name),
                IrrigationZoneRawSensor(coordinator, zone_id, zone_name),
                IrrigationZoneStatusSensor(coordinator, zone_id, zone_name),
            ]
        )

    async_add_entities(entities)


# ── Integration-level sensors ──────────────────────────────────────────────────


class IrrigationEtoSensor(CoordinatorEntity, SensorEntity):
    """Today's reference evapotranspiration (Penman-Monteith preferred)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES_PER_DAY
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Irrigation Reference ETo"
        self._attr_unique_id = "dxhyve_irrigation_eto_today"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("eto_today")

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        return {
            "method": self.coordinator.data.get("eto_method"),
            "tmax_c": self.coordinator.data.get("tmax_c"),
            "tmin_c": self.coordinator.data.get("tmin_c"),
            "humidity_pct": self.coordinator.data.get("humidity_pct"),
            "wind_ms": self.coordinator.data.get("wind_ms"),
            "last_update": self.coordinator.data.get("last_update"),
        }


class IrrigationRainTodaySensor(CoordinatorEntity, SensorEntity):
    """Today's accumulated rain gauge reading."""

    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_name = "Irrigation Rain Today"
        self._attr_unique_id = "dxhyve_irrigation_rain_today"

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("rain_today")


# ── Per-zone sensors ────────────────────────────────────────────────────────────


class _ZoneBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class for zone sensors."""

    def __init__(
        self,
        coordinator: IrrigationCoordinator,
        zone_id: str,
        zone_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name

    def _zone_data(self) -> dict:
        if self.coordinator.data is None:
            return {}
        return self.coordinator.data.get("zones", {}).get(self._zone_id, {})


class IrrigationZoneMoistureSensor(_ZoneBaseSensor):
    """Soil moisture as % of PAW — 100% = field capacity, 0% = wilting point.

    Inverted from Dc so higher numbers are "wetter" (more intuitive for users).
    """

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} Soil Moisture"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_moisture"

    @property
    def native_value(self) -> float | None:
        data = self._zone_data()
        if not data:
            return None
        dc = data.get("dc_current", 0)
        paw = data.get("paw", 0)
        if paw <= 0:
            return None
        # Dc=0 → 100% full; Dc=PAW → 0% full
        return round((1 - dc / paw) * 100, 1)

    @property
    def extra_state_attributes(self) -> dict:
        return {}


class IrrigationZoneDeficitSensor(_ZoneBaseSensor):
    """Current soil water deficit (Dc) in inches.

    0 = field capacity (full), PAW = permanent wilting point (empty).
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:water-minus"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} Soil Deficit"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_deficit"

    @property
    def native_value(self) -> float | None:
        data = self._zone_data()
        if not data:
            return None
        return data.get("dc_current")

    @property
    def extra_state_attributes(self) -> dict:
        data = self._zone_data()
        return {
            "paw": data.get("paw"),
            "raw": data.get("raw"),
            "mad": data.get("mad"),
        }


class IrrigationZoneEtlSensor(_ZoneBaseSensor):
    """Today's landscape evapotranspiration (ETL) for this zone."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES_PER_DAY
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} ETL Today"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_etl_today"

    @property
    def native_value(self) -> float | None:
        data = self._zone_data()
        if not data:
            return None
        return data.get("etl_today")

    @property
    def extra_state_attributes(self) -> dict:
        data = self._zone_data()
        return {
            "kl": data.get("kl"),
            "kp": data.get("kp"),
            "kmc": data.get("kmc"),
        }


class IrrigationZonePawSensor(_ZoneBaseSensor):
    """Plant Available Water capacity for this zone (inches)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} PAW"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_paw"

    @property
    def native_value(self) -> float | None:
        data = self._zone_data()
        if not data:
            return None
        return data.get("paw")

    @property
    def extra_state_attributes(self) -> dict:
        data = self._zone_data()
        return {
            "fcd": data.get("fcd"),
            "pwpd": data.get("pwpd"),
            "aw": data.get("aw"),
            "stdrt_minutes": data.get("stdrt"),
            "cycles": data.get("cycles"),
            "rt_per_cycle_minutes": data.get("rt_per_cycle"),
            "soak_time_minutes": data.get("soak_time"),
            "maxrt_minutes": data.get("maxrt"),
        }


class IrrigationZoneRawSensor(_ZoneBaseSensor):
    """Readily Available Water threshold for this zone (inches).

    When Dc > RAW, irrigation is needed.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UNIT_INCHES
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} RAW Threshold"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_raw"

    @property
    def native_value(self) -> float | None:
        data = self._zone_data()
        if not data:
            return None
        return data.get("raw")


class IrrigationZoneStatusSensor(_ZoneBaseSensor):
    """Plain-language irrigation status for the zone.

    Normal     — Dc ≤ RAW (within readily available water)
    Needs Water — Dc > RAW (below the management allowable depletion threshold)
    At Capacity — Dc ≤ 5% of PAW (nearly at field capacity)
    """

    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator, zone_id: str, zone_name: str) -> None:
        super().__init__(coordinator, zone_id, zone_name)
        self._attr_name = f"{zone_name} Status"
        self._attr_unique_id = f"dxhyve_irrigation_{zone_id}_status"

    @property
    def native_value(self) -> str | None:
        data = self._zone_data()
        if not data:
            return None
        dc = data.get("dc_current", 0)
        paw = data.get("paw", 0)
        raw = data.get("raw", 0)
        if paw <= 0:
            return None
        if dc <= paw * 0.05:
            return "At Capacity"
        if dc > raw:
            return "Needs Water"
        return "Normal"
