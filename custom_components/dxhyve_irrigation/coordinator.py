"""DataUpdateCoordinator for DxHyve Smart Irrigation.

Responsibilities:
- Poll weather entities every 15 minutes
- Compute ETo via the best available method (priority chain below)
- Recompute zone parameters from config on every update
- Compute live dc_current = dc_day_start + etl_today - rain_today on every cycle
- Midnight rollover: promote dc_current → dc_start, reset rain baseline
- Persist state on every update (HA Store debounces writes automatically)

ETo priority chain:
  1. Penman-Monteith (FAO-56) — used whenever temperatures are available.
     Humidity falls back to 60% RH and wind to 2 m/s per spec §13.3 if the
     dedicated entities or weather attributes are absent.
  2. Hargreaves-Samani — fallback only if PM raises an unexpected exception.
  3. Historical monthly average — when temperature data is completely absent.

Design: dc_current is computed live every 15 min so rain and ETo are always
reflected in real time. dc_start (the Dc at the beginning of today) is the
stable anchor; it is only changed at midnight rollover.
"""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAX_PLAUSIBLE_DAILY_RAIN_IN, WEATHER_UPDATE_INTERVAL
from .core.et_engine import (
    calculate_etl,
    calculate_eto_hargreaves,
    calculate_eto_historical,
    calculate_eto_penman_monteith,
    f_to_c,
)
from .core.state_store import IrrigationStateStore
from .core.zone import compute_zone_params

_LOGGER = logging.getLogger(__name__)


class IrrigationCoordinator(DataUpdateCoordinator):
    """Coordinator that drives all ET calculations and moisture balance updates."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=WEATHER_UPDATE_INTERVAL),
        )
        self._config_entry = config_entry
        self._store = IrrigationStateStore(hass)

    async def async_setup(self) -> None:
        """Load persisted state. Call once from async_setup_entry."""
        await self._store.async_load()

    # ── Core update ──────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict:
        """Fetch weather, recompute ET, and update live moisture balance.

        Returns coordinator data dict consumed by sensor entities.
        """
        cfg = self._config_entry.data
        options = self._config_entry.options
        latitude = cfg.get("latitude", self.hass.config.latitude)

        # ── Step 1: Weather inputs and ETo ──────────────────────────────────
        tmax_c, tmin_c = await self._get_daily_temps(cfg)

        today = dt_util.now().date()
        day_of_year = today.timetuple().tm_yday
        today_str = today.isoformat()

        humidity_pct, rh_default = self._get_humidity(cfg)
        wind_ms, wind_default = self._get_wind_speed_ms(cfg)

        eto_inches = 0.0
        eto_method = "none"

        if tmax_c is not None and tmin_c is not None:
            try:
                eto_inches = calculate_eto_penman_monteith(
                    tmax_c, tmin_c, latitude, day_of_year, humidity_pct, wind_ms
                )
                parts = ["PM"]
                if rh_default:
                    parts.append("RH=default(60%)")
                if wind_default:
                    parts.append("wind=default(2m/s)")
                eto_method = "+".join(parts)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Penman-Monteith failed (%s) — falling back to Hargreaves-Samani", err)
                eto_inches = calculate_eto_hargreaves(tmax_c, tmin_c, latitude, day_of_year)
                eto_method = "hargreaves-samani"
            _LOGGER.debug(
                "ETo (%s): tmax=%.1f°C tmin=%.1f°C RH=%.0f%% wind=%.1fm/s → %.4f in/day",
                eto_method, tmax_c, tmin_c, humidity_pct, wind_ms, eto_inches,
            )
        else:
            eto_inches = calculate_eto_historical(latitude, today.month)
            eto_method = "historical"
            _LOGGER.warning(
                "Temperature unavailable — using historical ETo: %.4f in/day (month=%d)",
                eto_inches, today.month,
            )

        # ── Step 2: Detect midnight rollover ────────────────────────────────
        is_new_day = self._store.get_last_dc_rollover_date() != today_str

        # ── Step 3: Rain gauge delta ─────────────────────────────────────────
        # Pass is_new_day so the baseline resets in sync with the Dc rollover.
        rain_today = self._get_rain_delta(cfg, today_str, is_new_day)

        # ── Step 4: Midnight rollover ────────────────────────────────────────
        zone_configs = {
            k: v for k, v in options.items() if isinstance(v, dict) and "soil_type" in v
        }

        if is_new_day:
            _LOGGER.debug("New day detected — performing Dc rollover for %s", today_str)
            for zone_id, zone_cfg in zone_configs.items():
                try:
                    params = compute_zone_params(zone_cfg)
                except (KeyError, ValueError):
                    continue
                self._store.rollover_zone_dc(zone_id, params["paw"])
            self._store.set_last_dc_rollover_date(today_str)

        # ── Step 5: Live zone data ───────────────────────────────────────────
        zones_data: dict = {}

        for zone_id, zone_cfg in zone_configs.items():
            try:
                params = compute_zone_params(zone_cfg)
            except (KeyError, ValueError) as err:
                _LOGGER.error("Zone %s param computation failed: %s", zone_id, err)
                continue

            paw = params["paw"]
            etl_today = calculate_etl(eto_inches, params["kp"], params["kmc"])

            # dc_current = dc_start + etl_today - effective_rain  (live, every 15 min)
            dc_start = self._store.get_zone_dc_start(zone_id, paw)
            por = zone_cfg.get("percent_of_rain", 80) / 100
            effective_rain = rain_today * por
            dc_current = dc_start + etl_today - effective_rain
            dc_current = max(0.0, min(dc_current, paw))  # clamp to [0, PAW]

            self._store.set_zone_dc_current(zone_id, dc_current)

            _LOGGER.debug(
                "Zone %s: dc_start=%.4f + etl=%.4f - rain=%.4f → dc=%.4f (paw=%.3f)",
                zone_id, dc_start, etl_today, effective_rain, dc_current, paw,
            )

            zones_data[zone_id] = {
                **params,
                "zone_name": zone_cfg.get("zone_name", zone_id),
                "zone_short_name": zone_cfg.get("zone_short_name", zone_id),
                "dc_current": dc_current,
                "dc_start": dc_start,
                "etl_today": round(etl_today, 4),
            }

        # ── Step 6: Persist ──────────────────────────────────────────────────
        # HA's Store debounces writes, so calling this every 15 min is fine.
        await self._store.async_save()

        return {
            "eto_today": round(eto_inches, 4),
            "eto_method": eto_method,
            "tmax_c": tmax_c,
            "tmin_c": tmin_c,
            "humidity_pct": round(humidity_pct, 1),
            "wind_ms": round(wind_ms, 2),
            "rain_today": round(rain_today, 4),
            "last_update": dt_util.now().isoformat(),
            "zones": zones_data,
        }

    # ── Weather helpers ──────────────────────────────────────────────────────

    def _get_humidity(self, cfg: dict) -> tuple[float, bool]:
        """Return (humidity_pct, is_default).

        Priority: humidity_entity → weather entity state attributes → 60% default.
        is_default is True when the spec §13.3 fallback of 60% RH is used.
        """
        humidity_entity_id = cfg.get("humidity_entity")
        if humidity_entity_id:
            state = self.hass.states.get(humidity_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    return float(state.state), False
                except ValueError:
                    pass

        weather_entity_id = cfg.get("weather_entity")
        if weather_entity_id:
            state = self.hass.states.get(weather_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                humidity = state.attributes.get("humidity")
                if humidity is not None:
                    try:
                        return float(humidity), False
                    except (TypeError, ValueError):
                        pass

        _LOGGER.debug("Humidity unavailable — using spec default 60%% RH")
        return 60.0, True

    def _get_wind_speed_ms(self, cfg: dict) -> tuple[float, bool]:
        """Return (wind_ms, is_default) with wind speed in m/s at 10 m height.

        Priority: wind_entity → weather entity state attributes → 2 m/s default.
        is_default is True when the spec §13.3 fallback of 2 m/s is used.
        Converts from the entity's reported unit to m/s automatically.
        """
        def _to_ms(value: float, unit: str) -> float:
            u = (unit or "").lower()
            if "mph" in u:
                return value * 0.44704
            if "km" in u:
                return value * 0.27778
            if "kn" in u or "knot" in u:
                return value * 0.51444
            return value  # already m/s

        wind_entity_id = cfg.get("wind_entity")
        if wind_entity_id:
            state = self.hass.states.get(wind_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                try:
                    unit = state.attributes.get("unit_of_measurement", "m/s")
                    return _to_ms(float(state.state), unit), False
                except ValueError:
                    pass

        weather_entity_id = cfg.get("weather_entity")
        if weather_entity_id:
            state = self.hass.states.get(weather_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                wind_speed = state.attributes.get("wind_speed")
                if wind_speed is not None:
                    try:
                        unit = state.attributes.get("wind_speed_unit", "m/s")
                        return _to_ms(float(wind_speed), unit), False
                    except (TypeError, ValueError):
                        pass

        _LOGGER.debug("Wind speed unavailable — using spec default 2 m/s")
        return 2.0, True

    async def _get_daily_temps(self, cfg: dict) -> tuple[float | None, float | None]:
        """Return (tmax_c, tmin_c) for today from best available source.

        Priority:
        1. weather.get_forecasts with type=daily — correct full-day high/low
        2. Scan hourly forecast entries for today — handles hourly-only entities
        3. Dedicated temperature sensor — current reading only (ETo will be ~0)
        """
        weather_entity_id = cfg.get("weather_entity")
        temp_entity_id = cfg.get("temperature_entity")

        tmax_c = None
        tmin_c = None

        if weather_entity_id:
            state = self.hass.states.get(weather_entity_id)
            if state and state.state not in ("unavailable", "unknown"):
                temp_unit = state.attributes.get("temperature_unit", "°C")

                def _convert(val: float) -> float:
                    if "F" in temp_unit or "°F" in temp_unit:
                        return f_to_c(val)
                    return float(val)

                # Try daily forecast first
                try:
                    response = await self.hass.services.async_call(
                        "weather",
                        "get_forecasts",
                        {"entity_id": weather_entity_id, "type": "daily"},
                        blocking=True,
                        return_response=True,
                    )
                    daily_fc = response.get(weather_entity_id, {}).get("forecast", [])
                    if daily_fc:
                        today_fc = daily_fc[0]
                        raw_high = today_fc.get("temperature")
                        raw_low = today_fc.get("templow")
                        if raw_high is not None and raw_low is not None:
                            tmax_c = _convert(raw_high)
                            tmin_c = _convert(raw_low)
                            _LOGGER.debug(
                                "Temps from daily forecast: tmax=%.1f°C tmin=%.1f°C",
                                tmax_c, tmin_c,
                            )
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Daily forecast service unavailable: %s", err)

                # Fall back: scan hourly forecast for today's min/max
                if tmax_c is None:
                    try:
                        response = await self.hass.services.async_call(
                            "weather",
                            "get_forecasts",
                            {"entity_id": weather_entity_id, "type": "hourly"},
                            blocking=True,
                            return_response=True,
                        )
                        hourly_fc = response.get(weather_entity_id, {}).get("forecast", [])
                        today_str_local = dt_util.now().date().isoformat()
                        temps_today = [
                            _convert(entry["temperature"])
                            for entry in hourly_fc
                            if entry.get("datetime", "").startswith(today_str_local)
                            and entry.get("temperature") is not None
                        ]
                        if temps_today:
                            tmax_c = max(temps_today)
                            tmin_c = min(temps_today)
                            _LOGGER.debug(
                                "Temps from hourly scan (%d entries): tmax=%.1f°C tmin=%.1f°C",
                                len(temps_today), tmax_c, tmin_c,
                            )
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.debug("Hourly forecast service unavailable: %s", err)

        if tmax_c is None and temp_entity_id:
            temp_state = self.hass.states.get(temp_entity_id)
            if temp_state and temp_state.state not in ("unavailable", "unknown"):
                try:
                    temp_val = float(temp_state.state)
                    unit = temp_state.attributes.get("unit_of_measurement", "°C")
                    if "F" in unit:
                        temp_val = f_to_c(temp_val)
                    tmax_c = temp_val
                    tmin_c = temp_val
                    _LOGGER.warning("Using current temperature only — ETo degraded (tmax==tmin)")
                except ValueError:
                    pass

        if tmax_c is None:
            _LOGGER.warning(
                "No temperature data from weather_entity=%s or temperature_entity=%s",
                weather_entity_id, temp_entity_id,
            )

        return tmax_c, tmin_c

    def _get_rain_delta(self, cfg: dict, today_str: str, is_new_day: bool) -> float:
        """Return today's accumulated precipitation in inches.

        Handles all sensor types via delta tracking:
        - Daily-reset sensors: baseline ≈ 0 at midnight, delta = current value
        - Seasonal accumulators: delta from today's opening reading
        - Battery-reset sensors: negative delta → reset detected → use current as delta

        Args:
            is_new_day: When True, resets the baseline to current reading (in sync
                        with the Dc rollover so both anchor at the same moment).
        """
        rain_entity_id = cfg.get("rain_gauge_entity")
        if not rain_entity_id:
            return 0.0

        state = self.hass.states.get(rain_entity_id)
        if not state or state.state in ("unavailable", "unknown"):
            return 0.0

        try:
            current = float(state.state)
        except ValueError:
            return 0.0

        unit = state.attributes.get("unit_of_measurement", "in")
        if "mm" in unit.lower():
            current = current / 25.4
        current = max(0.0, current)

        day_start_val, day_start_date = self._store.get_rain_gauge_day_start()

        # Reset baseline on new day or first run
        if is_new_day or day_start_val is None or day_start_date != today_str:
            self._store.set_rain_gauge_day_start(current, today_str)
            _LOGGER.debug("Rain baseline set: %.4f in (%s)", current, today_str)
            return 0.0

        delta = current - day_start_val

        if delta < 0:
            # Raw counter dropped below today's baseline. A genuine battery/
            # season reset restarts the counter near zero, so `current` itself
            # is a safe stand-in for today's rain. If `current` is still a
            # large number, this isn't a real reset — it's a bad reading (e.g.
            # a glitched baseline captured at the midnight rollover) — and
            # trusting it would misattribute the whole seasonal/lifetime total
            # to a single day.
            if current > MAX_PLAUSIBLE_DAILY_RAIN_IN:
                delta = None
            else:
                _LOGGER.warning(
                    "Rain gauge reset detected (%.4f → %.4f in) — "
                    "using post-reset value; updating baseline",
                    day_start_val, current,
                )
                self._store.set_rain_gauge_day_start(0.0, today_str)
                delta = current

        if delta is None or delta > MAX_PLAUSIBLE_DAILY_RAIN_IN:
            # Implausible in either direction — the baseline was almost
            # certainly captured from a bad reading rather than reflecting
            # real rainfall. Re-anchor to the current reading (instead of
            # reporting the runaway value) so later cycles compute sane
            # deltas once the sensor is reading normally again.
            _LOGGER.warning(
                "Rain delta implausible (baseline=%.4f, current=%.4f in) — "
                "re-anchoring baseline instead of reporting it as rainfall",
                day_start_val, current,
            )
            self._store.set_rain_gauge_day_start(current, today_str)
            return 0.0

        _LOGGER.debug(
            "Rain delta: current=%.4f baseline=%.4f → today=%.4f in",
            current, day_start_val, delta,
        )
        return delta

    # ── Public API for services (Phase 2) ────────────────────────────────────

    @callback
    def get_store(self) -> IrrigationStateStore:
        """Return the state store for direct access by services."""
        return self._store
