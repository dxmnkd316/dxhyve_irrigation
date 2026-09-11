"""Evapotranspiration calculation engine for DxHyve Smart Irrigation.

All ET math is performed in metric internally (°C, mm, MJ/m²).
Results are converted to imperial (inches) before returning.

ETo priority chain:
  1. Penman-Monteith (FAO-56) — runs whenever temperatures are available;
     humidity and wind fall back to spec defaults (60% RH, 2 m/s) if missing.
  2. Hargreaves-Samani — temperature-only fallback if PM raises unexpectedly.
  3. Historical monthly average — when temperature data is completely absent.
"""
import math

from ..const import HISTORICAL_ETO_TABLE


def calculate_eto_penman_monteith(
    tmax_c: float,
    tmin_c: float,
    latitude_deg: float,
    day_of_year: int,
    humidity_pct: float,
    wind_ms: float,
    solar_mj: float | None = None,
) -> float:
    """FAO-56 Penman-Monteith reference ETo.

    When solar_mj is None, net solar radiation is estimated from the daily
    temperature range (FAO-56 Eq. 50, krs=0.17). This retains the humidity
    and wind terms that make PM climate-agnostic, and is significantly more
    accurate than plain Hargreaves-Samani in humid or maritime climates.

    Args:
        tmax_c: Daily maximum air temperature (°C)
        tmin_c: Daily minimum air temperature (°C)
        latitude_deg: Site latitude in decimal degrees (North)
        day_of_year: Day of year (1–365)
        humidity_pct: Mean relative humidity (%)
        wind_ms: Wind speed at 10 m height (m/s); converted to 2 m internally
        solar_mj: Measured incoming solar radiation (MJ/m²/day), or None to estimate

    Returns:
        ETo in inches/day (≥ 0.0)
    """
    lat_rad = math.radians(latitude_deg)

    # Extraterrestrial radiation (MJ/m²/day) — same formula as Hargreaves
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * day_of_year)
    delta = 0.409 * math.sin(2 * math.pi / 365 * day_of_year - 1.39)
    ws = math.acos(-math.tan(lat_rad) * math.tan(delta))
    Ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat_rad) * math.sin(delta)
        + math.cos(lat_rad) * math.cos(delta) * math.sin(ws)
    )

    # Solar radiation
    if solar_mj is not None:
        Rs = max(0.0, solar_mj)
    else:
        # FAO-56 Eq. 50: temperature-range estimate (krs=0.17, mid-range between
        # interior 0.16 and coastal 0.19)
        tdiff = max(0.0, tmax_c - tmin_c)
        Rs = 0.17 * math.sqrt(tdiff) * Ra

    Rns = (1 - 0.23) * Rs  # net shortwave, α=0.23 for short reference grass

    # Clear-sky radiation for cloudiness ratio (FAO-56 Eq. 37, sea-level approx)
    Rs0 = 0.75 * Ra
    cloudiness = min(1.0, Rs / Rs0) if Rs0 > 0 else 1.0

    # Vapor pressures (kPa)
    tmean = (tmax_c + tmin_c) / 2
    es_tmax = 0.6108 * math.exp(17.27 * tmax_c / (tmax_c + 237.3))
    es_tmin = 0.6108 * math.exp(17.27 * tmin_c / (tmin_c + 237.3))
    es = (es_tmax + es_tmin) / 2
    ea = (humidity_pct / 100.0) * es
    vpd = max(0.0, es - ea)

    # Net longwave radiation (FAO-56 Eq. 39)
    # σ = 4.903e-9 MJ/m²/K⁴/day
    sigma = 4.903e-9
    tmax_k = tmax_c + 273.16
    tmin_k = tmin_c + 273.16
    Rnl = (
        sigma
        * (tmax_k**4 + tmin_k**4) / 2
        * (0.34 - 0.14 * math.sqrt(max(0.0, ea)))
        * (1.35 * cloudiness - 0.35)
    )
    Rnl = max(0.0, Rnl)

    Rn = Rns - Rnl

    # Slope of saturation vapor pressure curve at tmean (kPa/°C)
    delta_svp = (
        4098 * (0.6108 * math.exp(17.27 * tmean / (tmean + 237.3)))
        / (tmean + 237.3) ** 2
    )

    # Psychrometric constant (kPa/°C) at sea-level pressure (101.3 kPa)
    gamma = 0.067

    # Wind speed at 2 m height (FAO-56 Eq. 47, assumes 10 m measurement)
    u2 = wind_ms * (4.87 / math.log(67.8 * 10 - 5.42))
    u2 = max(0.5, u2)  # WMO minimum

    # FAO-56 Penman-Monteith (Eq. 6)
    numerator = 0.408 * delta_svp * Rn + gamma * (900 / (tmean + 273)) * u2 * vpd
    denominator = delta_svp + gamma * (1 + 0.34 * u2)

    eto_mm = numerator / denominator if denominator > 0 else 0.0
    return max(0.0, eto_mm / 25.4)


def calculate_eto_hargreaves(tmax_c: float, tmin_c: float, latitude_deg: float, day_of_year: int) -> float:
    """Compute reference ETo using Hargreaves-Samani method.

    Temperature-only fallback. Overestimates in humid/maritime climates because
    it uses theoretical clear-sky Ra and has no humidity term. Use only when
    Penman-Monteith is unavailable.

    Args:
        tmax_c: Daily maximum air temperature (°C)
        tmin_c: Daily minimum air temperature (°C)
        latitude_deg: Site latitude in decimal degrees
        day_of_year: Day of year (1–365)

    Returns:
        ETo in inches/day (≥ 0.0)
    """
    lat_rad = math.radians(latitude_deg)

    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * day_of_year)
    delta = 0.409 * math.sin(2 * math.pi / 365 * day_of_year - 1.39)
    ws = math.acos(-math.tan(lat_rad) * math.tan(delta))
    Ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat_rad) * math.sin(delta)
        + math.cos(lat_rad) * math.cos(delta) * math.sin(ws)
    )

    tmean = (tmax_c + tmin_c) / 2
    tdiff = tmax_c - tmin_c

    if tdiff < 0:
        return 0.0

    eto_mm = 0.0023 * (tmean + 17.8) * math.sqrt(tdiff) * Ra
    return max(0.0, eto_mm / 25.4)


def calculate_eto_historical(latitude_deg: float, month: int) -> float:
    """Return historical average reference ETo for a given latitude and month.

    Last-resort fallback when temperature data is completely unavailable.
    Accuracy is ±30–50%; should trigger a persistent HA notification.

    Args:
        latitude_deg: Site latitude in decimal degrees (North)
        month: Month number (1=Jan … 12=Dec)

    Returns:
        ETo in inches/day
    """
    bands = sorted(HISTORICAL_ETO_TABLE.keys())
    lat = max(bands[0], min(bands[-1], latitude_deg))
    band = max(b for b in bands if b <= lat)
    return HISTORICAL_ETO_TABLE[band][month - 1]


def calculate_etl(eto_inches: float, kp: float, kmc: float) -> float:
    """Compute landscape evapotranspiration (ETL) from reference ETo.

    ETL = KL × ETo, where KL = KP × KMC

    Args:
        eto_inches: Reference ETo (inches/day)
        kp: Plant/species factor (dimensionless)
        kmc: Microclimate factor from KMC_TABLE (dimensionless)

    Returns:
        ETL in inches/day
    """
    return eto_inches * kp * kmc


def f_to_c(f: float) -> float:
    """Convert Fahrenheit to Celsius."""
    return (f - 32) * 5 / 9


def c_to_f(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return c * 9 / 5 + 32
