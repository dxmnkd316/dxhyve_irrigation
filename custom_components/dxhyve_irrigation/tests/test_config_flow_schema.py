"""Zone schema regression: valve_entity must accept both `switch` (BHyve hose
timers) and `valve` (native HA valve domain) entities.
"""
from custom_components.dxhyve_irrigation.config_flow import ZONE_SCHEMA


def test_valve_entity_accepts_switch_and_valve_domains():
    valve_selector = ZONE_SCHEMA.schema["valve_entity"]
    domains = valve_selector.config["domain"]
    assert "switch" in domains
    assert "valve" in domains
