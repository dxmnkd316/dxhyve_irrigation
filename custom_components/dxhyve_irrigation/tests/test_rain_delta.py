"""Regression tests for IrrigationCoordinator._get_rain_delta().

Reproduces the reported bug: a seasonal/lifetime rain gauge total (~11 in)
got misattributed as a single day's rainfall after a bad reading landed
exactly on the midnight baseline-capture cycle.
"""
from custom_components.dxhyve_irrigation.coordinator import IrrigationCoordinator
from custom_components.dxhyve_irrigation.core.state_store import IrrigationStateStore


class FakeState:
    def __init__(self, value, unit="in"):
        self.state = str(value)
        self.attributes = {"unit_of_measurement": unit}


class FakeStates:
    def __init__(self):
        self._states = {}

    def set(self, entity_id, value, unit="in"):
        self._states[entity_id] = FakeState(value, unit)

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeHass:
    def __init__(self):
        self.states = FakeStates()


def make_coordinator():
    """Build a coordinator instance without running __init__/HA setup."""
    coordinator = object.__new__(IrrigationCoordinator)
    coordinator.hass = FakeHass()
    coordinator._store = IrrigationStateStore(coordinator.hass)
    coordinator._store._data = {"zones": {}, "integration": {}}
    return coordinator


CFG = {"rain_gauge_entity": "sensor.rain_gauge"}


def set_rain(coordinator, value):
    coordinator.hass.states.set("sensor.rain_gauge", value)


def test_normal_single_rain_event_is_reported_correctly():
    """9/1 -> 9/2 baseline: legit small rain event during the day."""
    c = make_coordinator()

    # 9/1: new-day baseline capture, no rain
    set_rain(c, 10.86)
    assert c._get_rain_delta(CFG, "2025-09-01", is_new_day=True) == 0.0

    # 9/2 ~2 AM: new day rolls over cleanly, then rain arrives mid-day
    set_rain(c, 10.86)
    assert c._get_rain_delta(CFG, "2025-09-02", is_new_day=True) == 0.0

    set_rain(c, 10.88)
    assert round(c._get_rain_delta(CFG, "2025-09-02", is_new_day=False), 4) == 0.02


def test_glitched_low_midnight_reading_does_not_leak_seasonal_total():
    """Reproduces the exact reported incident.

    A bad/glitched reading (reads ~0) lands precisely on the midnight
    baseline-capture cycle. Fifteen minutes later the sensor recovers and
    reports its real seasonal total (~10.92 in). The old code reported the
    full 10.92 in as "today's rain". The fix must not do that.
    """
    c = make_coordinator()

    # Prior day ended with the gauge sitting at 10.88 in (no bug here).
    set_rain(c, 10.88)
    c._get_rain_delta(CFG, "2025-09-02", is_new_day=True)

    # 9/3 12:04:45 AM — midnight rollover cycle, sensor glitches to ~0.
    set_rain(c, 0.0)
    assert c._get_rain_delta(CFG, "2025-09-03", is_new_day=True) == 0.0

    # 9/3 12:19:45 AM — sensor recovers to its real seasonal total.
    set_rain(c, 10.92)
    reported = c._get_rain_delta(CFG, "2025-09-03", is_new_day=False)
    assert reported <= 6.0, f"leaked seasonal total as daily rain: {reported}"
    assert reported == 0.0

    # 9/3 2:34 PM — a real, small rain event on top of the re-anchored baseline.
    set_rain(c, 11.03)
    reported = round(c._get_rain_delta(CFG, "2025-09-03", is_new_day=False), 4)
    assert reported == 0.11

    # 9/4 12:04:45 AM — clean rollover, no more rain.
    set_rain(c, 11.03)
    assert c._get_rain_delta(CFG, "2025-09-04", is_new_day=True) == 0.0

    set_rain(c, 11.03)
    assert c._get_rain_delta(CFG, "2025-09-04", is_new_day=False) == 0.0


def test_glitched_high_baseline_does_not_report_negative_as_full_total():
    """Same failure mode, other direction: the midnight reading itself is the
    glitch (spuriously high) and the very next reading looks like a "drop"
    that isn't a real battery/season reset.
    """
    c = make_coordinator()

    set_rain(c, 10.88)
    c._get_rain_delta(CFG, "2025-09-02", is_new_day=True)

    # Midnight rollover captures a spuriously high baseline.
    set_rain(c, 15.0)
    assert c._get_rain_delta(CFG, "2025-09-03", is_new_day=True) == 0.0

    # Real reading returns — looks like a drop, but 10.92 in is not a
    # plausible "post battery-reset" value, so it must not be reported as
    # 10.92 in of rain.
    set_rain(c, 10.92)
    reported = c._get_rain_delta(CFG, "2025-09-03", is_new_day=False)
    assert reported == 0.0

    # Baseline should have re-anchored to 10.92 so a real rain event now
    # computes a sane delta.
    set_rain(c, 11.00)
    reported = round(c._get_rain_delta(CFG, "2025-09-03", is_new_day=False), 4)
    assert reported == 0.08


def test_genuine_small_reset_is_still_reported():
    """A real battery/season-counter reset lands near zero and should still
    be trusted and reported as today's rain since the reset.
    """
    c = make_coordinator()

    set_rain(c, 10.90)
    c._get_rain_delta(CFG, "2025-09-05", is_new_day=True)

    # Battery replaced mid-day: counter genuinely resets to a small value.
    set_rain(c, 0.05)
    reported = c._get_rain_delta(CFG, "2025-09-05", is_new_day=False)
    assert reported == 0.05
