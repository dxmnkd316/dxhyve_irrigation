"""Constants for the DxHyve Smart Irrigation integration."""

DOMAIN = "dxhyve_irrigation"
STORAGE_KEY = "dxhyve_irrigation_state"
STORAGE_VERSION = 1

SCHEDULER_TIME = (23, 0, 0)   # 11:00 PM
WEATHER_UPDATE_INTERVAL = 900  # 15 minutes in seconds

MIN_CYCLE_RUNTIME = 3          # minutes — per WaterSense spec
MIN_SOAK_TIME = 15             # minutes minimum between cycles
MAX_SOAK_TIME = 60             # minutes — flag if exceeded
ZONE_GAP_DEFAULT = 5           # minutes between zones

FREEZE_THRESHOLD_DEFAULT = 40  # °F
WIND_THRESHOLD_SPRAY = 15      # mph
WIND_THRESHOLD_ROTOR = 25      # mph
MIN_POP_THRESHOLD = 25         # % — ignore rain forecast below this
MIN_QPF_THRESHOLD = 0.10       # inches — ignore rain forecast below this

# A single day's rain gauge delta above this is treated as a bad reading
# (e.g. a glitched baseline capture) rather than real rainfall — seasonal/
# lifetime rain gauge totals can run into double digits, so any "reset" or
# jump this large is almost certainly a data glitch, not weather.
MAX_PLAUSIBLE_DAILY_RAIN_IN = 6.0
DEFER_THRESHOLD_RATIO = 0.75   # EER must cover 75% of need to defer

SOIL_PARAMS = {
    "sand":        {"fc": 0.10, "pwp": 0.04, "aw": 0.06, "bir": 0.60},
    "sandy_loam":  {"fc": 0.18, "pwp": 0.08, "aw": 0.10, "bir": 0.40},
    "loam":        {"fc": 0.26, "pwp": 0.12, "aw": 0.14, "bir": 0.35},
    "clay_loam":   {"fc": 0.31, "pwp": 0.15, "aw": 0.16, "bir": 0.20},
    "clay":        {"fc": 0.40, "pwp": 0.20, "aw": 0.20, "bir": 0.15},
}

VEGETATION_PARAMS = {
    "cool_turf":         {"rz": 6,  "kp": 0.80},
    "warm_turf":         {"rz": 6,  "kp": 0.60},
    "annuals":           {"rz": 4,  "kp": 0.75},
    "shrubs_perennials": {"rz": 6,  "kp": 0.50},
    "trees":             {"rz": 12, "kp": 0.50},
}

SPRINKLER_PARAMS = {
    "spray":      {"ar": 1.75, "efficiency": 75},
    "rotor":      {"ar": 0.75, "efficiency": 80},
    "rotary":     {"ar": 1.75, "efficiency": 75},
    "impact":     {"ar": 1.75, "efficiency": 75},
    "oscillator": {"ar": 1.00, "efficiency": 75},
    "drip":       {"ar": 1.00, "efficiency": 90},
}

ASA_TABLE = {
    # (soil_type, slope_category): asa_inches
    ("loam",       "flat"):     0.30,
    ("loam",       "gentle"):   0.25,
    ("loam",       "moderate"): 0.21,
    ("loam",       "steep"):    0.17,
    ("sandy_loam", "flat"):     0.33,
    ("sandy_loam", "gentle"):   0.29,
    ("sandy_loam", "moderate"): 0.24,
    ("sandy_loam", "steep"):    0.20,
    ("clay_loam",  "flat"):     0.26,
    ("clay_loam",  "gentle"):   0.22,
    ("clay_loam",  "moderate"): 0.18,
    ("clay_loam",  "steep"):    0.15,
    ("clay",       "flat"):     0.20,
    ("clay",       "gentle"):   0.15,
    ("clay",       "moderate"): 0.10,
    ("clay",       "steep"):    0.10,
    ("sand",       "flat"):     0.40,
    ("sand",       "gentle"):   0.35,
    ("sand",       "moderate"): 0.30,
    ("sand",       "steep"):    0.25,
}

KMC_TABLE = {
    "lt_2hrs":  0.50,
    "2_4hrs":   0.70,
    "4_6hrs":   0.85,
    "6_8hrs":   1.00,
    "8_10hrs":  1.20,
    "gt_10hrs": 1.40,
}

HISTORICAL_ETO_TABLE = {
    # Monthly reference ETo (in/day) by latitude band lower bound (°N).
    # Approximate regional averages; accuracy ±30–50%. Last-resort fallback only.
    # Source: FAO-56 climate data adapted for North American latitudes.
    # Index: [Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec]
    25: [0.12, 0.14, 0.18, 0.22, 0.25, 0.27, 0.28, 0.27, 0.24, 0.19, 0.15, 0.12],
    30: [0.09, 0.12, 0.16, 0.21, 0.25, 0.28, 0.30, 0.28, 0.23, 0.17, 0.12, 0.09],
    35: [0.07, 0.10, 0.14, 0.19, 0.23, 0.27, 0.29, 0.27, 0.21, 0.15, 0.09, 0.07],
    40: [0.05, 0.08, 0.12, 0.17, 0.21, 0.25, 0.27, 0.25, 0.18, 0.12, 0.07, 0.05],
    45: [0.04, 0.06, 0.10, 0.15, 0.19, 0.23, 0.24, 0.22, 0.16, 0.10, 0.05, 0.03],
    50: [0.02, 0.04, 0.09, 0.14, 0.18, 0.22, 0.23, 0.20, 0.14, 0.08, 0.03, 0.02],
}

MAD_SAFETY_CEILING = {
    "cool_turf":         {"user_max": 0.60, "hard_max": 0.75},
    "warm_turf":         {"user_max": 0.65, "hard_max": 0.80},
    "annuals":           {"user_max": 0.50, "hard_max": 0.65},
    "shrubs_perennials": {"user_max": 0.60, "hard_max": 0.75},
    "trees":             {"user_max": 0.65, "hard_max": 0.80},
    "seeded":            {"user_max": 0.20, "hard_max": 0.30},
}
