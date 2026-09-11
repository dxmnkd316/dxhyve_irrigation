"""Tests for the zone edit gap: OptionsFlow could only add zones, never view
or change an existing zone's settings (e.g. percent_of_rain) after creation.
"""
import pytest

from custom_components.dxhyve_irrigation.config_flow import (
    DxHyveIrrigationOptionsFlow,
)


class FakeConfigEntry:
    def __init__(self, options):
        self.options = options


def make_flow(options):
    flow = DxHyveIrrigationOptionsFlow()
    flow.config_entry = FakeConfigEntry(options)
    return flow


FRONT_YARD = {
    "zone_name": "Front Yard",
    "zone_short_name": "FRONT",
    "valve_entity": "switch.front_valve",
    "soil_type": "loam",
    "vegetation_type": "cool_turf",
    "sprinkler_type": "spray",
    "sunlight": "6_8hrs",
    "slope": "flat",
    "percent_of_rain": 80,
    "odd_even": "none",
    "watering_mode": "blended",
    "mad": 0.50,
    "zone_priority": 1,
}

BACK_YARD = {**FRONT_YARD, "zone_name": "Back Yard", "zone_short_name": "BACK"}


@pytest.mark.asyncio
async def test_init_hides_edit_option_when_no_zones_exist():
    flow = make_flow({})
    result = await flow.async_step_init()
    action_options = result["data_schema"].schema["action"].config["options"]
    values = [o["value"] for o in action_options]
    assert values == ["add_zone"]


@pytest.mark.asyncio
async def test_init_offers_edit_option_when_zones_exist():
    flow = make_flow({"zone_front01": FRONT_YARD})
    result = await flow.async_step_init()
    action_options = result["data_schema"].schema["action"].config["options"]
    values = [o["value"] for o in action_options]
    assert "edit_zone" in values


@pytest.mark.asyncio
async def test_select_zone_lists_zones_by_name():
    flow = make_flow({"zone_front01": FRONT_YARD, "zone_back01": BACK_YARD})
    result = await flow.async_step_select_zone()
    assert result["step_id"] == "select_zone"
    zone_options = result["data_schema"].schema["zone_id"].config["options"]
    labels = {o["value"]: o["label"] for o in zone_options}
    assert labels == {"zone_front01": "Front Yard", "zone_back01": "Back Yard"}


@pytest.mark.asyncio
async def test_edit_zone_shows_current_values_for_selected_zone():
    flow = make_flow({"zone_front01": FRONT_YARD, "zone_back01": BACK_YARD})
    await flow.async_step_select_zone({"zone_id": "zone_front01"})
    result = await flow.async_step_edit_zone()
    assert result["step_id"] == "edit_zone"
    assert result["description_placeholders"]["zone_name"] == "Front Yard"


@pytest.mark.asyncio
async def test_edit_zone_submission_updates_only_the_selected_zone():
    """This is the exact scenario the user hit: change percent_of_rain on one
    zone and confirm it's the only thing that changes.
    """
    flow = make_flow({"zone_front01": FRONT_YARD, "zone_back01": BACK_YARD})
    await flow.async_step_select_zone({"zone_id": "zone_front01"})

    updated_front_yard = {**FRONT_YARD, "percent_of_rain": 60}
    result = await flow.async_step_edit_zone(updated_front_yard)

    assert result["type"] == "create_entry"
    assert result["data"]["zone_front01"]["percent_of_rain"] == 60
    assert result["data"]["zone_back01"] == BACK_YARD


@pytest.mark.asyncio
async def test_init_routes_edit_zone_action_to_select_zone_step():
    flow = make_flow({"zone_front01": FRONT_YARD})
    result = await flow.async_step_init({"action": "edit_zone"})
    assert result["step_id"] == "select_zone"
