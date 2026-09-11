"""Zone parameter calculations for DxHyve Smart Irrigation.

Computes all soil/water parameters from zone configuration.
All values in inches unless otherwise noted.
"""
import math

from ..const import (
    ASA_TABLE,
    KMC_TABLE,
    MAD_SAFETY_CEILING,
    MAX_SOAK_TIME,
    MIN_SOAK_TIME,
    SOIL_PARAMS,
    SPRINKLER_PARAMS,
    VEGETATION_PARAMS,
)


def compute_zone_params(config: dict) -> dict:
    """Compute all soil/water parameters from zone configuration.

    Args:
        config: Zone configuration dict from config_entry.options

    Returns:
        Dict of computed parameters. All values in inches unless noted.
    """
    soil = SOIL_PARAMS[config["soil_type"]]
    veg = VEGETATION_PARAMS[config["vegetation_type"]]
    spr = SPRINKLER_PARAMS[config["sprinkler_type"]]

    # Allow per-zone overrides of lookup table values
    fc = config.get("fc_override", soil["fc"])
    pwp = config.get("pwp_override", soil["pwp"])
    rz = config.get("rz_override", veg["rz"])
    ar = config.get("ar_override", spr["ar"])
    e = config.get("e_override", spr["efficiency"]) / 100
    bir = soil["bir"]
    kp = config.get("kp_override", veg["kp"])
    kmc = KMC_TABLE[config["sunlight"]]
    kmc = config.get("kmc_override", kmc)
    mad = min(
        config.get("mad", 0.50),
        MAD_SAFETY_CEILING[config["vegetation_type"]]["user_max"],
    )

    # Soil water parameters (all in inches)
    aw = fc - pwp          # available water (in/in)
    fcd = fc * rz          # field capacity depth
    pwpd = pwp * rz        # permanent wilting point depth
    paw = aw * rz          # plant available water
    raw = mad * paw        # readily available water
    rp = fcd - raw         # refill point

    # Standard runtime to refill from RAW deficit (minutes)
    stdrt = (raw / (ar * e)) * 60

    # Cycle-soak calculation
    slope_cat = config.get("slope", "flat")
    soil_key = config["soil_type"]
    asa = ASA_TABLE.get((soil_key, slope_cat), 0.25)

    if ar > bir:
        # Runoff risk — need cycle-soak
        maxrt = 60 * asa / (ar - bir)            # max runtime per cycle (minutes)
        cycles = math.ceil(stdrt / maxrt)
        rt_per_cycle = stdrt / cycles
        da = rt_per_cycle * ar / 60 * e          # net water applied per cycle (inches)
        soak_time = max(MIN_SOAK_TIME, math.ceil(da / bir * 60))
        soak_time = min(MAX_SOAK_TIME, soak_time)
    else:
        # Drip or low-rate — no runoff risk, single continuous cycle
        maxrt = None
        cycles = 1
        rt_per_cycle = stdrt
        soak_time = None

    kl = kp * kmc

    return {
        "aw": round(aw, 3),
        "fcd": round(fcd, 3),
        "pwpd": round(pwpd, 3),
        "paw": round(paw, 3),
        "raw": round(raw, 3),
        "rp": round(rp, 3),
        "stdrt": round(stdrt, 1),
        "maxrt": round(maxrt, 1) if maxrt is not None else None,
        "cycles": cycles,
        "rt_per_cycle": round(rt_per_cycle, 1),
        "soak_time": soak_time,
        "kl": round(kl, 3),
        "kp": kp,
        "kmc": kmc,
        "mad": mad,
        "hard_safety_mad": MAD_SAFETY_CEILING[config["vegetation_type"]]["hard_max"],
        "ar": ar,
        "efficiency": e,
        "bir": bir,
    }
