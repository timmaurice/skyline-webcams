"""Entity names, devices, and that existing entity ids survive both.

Turning has_entity_name on, and giving an entry's camera a device whose name it
shows instead of its own, changes how Home Assistant builds the name of a new
entity. An existing one keeps its entity id, because the registry holds it
under the unique id - which every camera of this integration has, from the
config flow and from YAML alike. These tests set a camera up the way Home
Assistant does and check both halves.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.skylinewebcams.const import CONF_URL, DOMAIN
from custom_components.skylinewebcams.helpers import unique_id_for_url

from .conftest import CAMERA_URL, make_entry

OTHER_CAMERA_URL = (
    "https://www.skylinewebcams.com/en/webcam/italia/veneto/venezia/"
    "piazza-san-marco.html"
)


async def test_a_new_camera_is_named_after_its_entry(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    registry = er.async_get(hass)
    [entity] = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert entity.entity_id == "camera.neuschwanstein"
    assert entity.has_entity_name is True
    assert entity.translation_key == "webcam"
    # The main feature of its device: no name of its own, the device's shows.
    assert entity.original_name is None
    assert hass.states.get("camera.neuschwanstein").name == "Neuschwanstein"


async def test_an_entry_gets_one_service_device(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.identifiers == {(DOMAIN, entry.entry_id)}
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.name == "Neuschwanstein"
    assert device.manufacturer == "SkylineWebcams"
    assert device.configuration_url == CAMERA_URL
    [entity] = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert entity.device_id == device.id


async def test_renaming_the_device_renames_the_camera_not_its_id(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)
    devices = dr.async_get(hass)
    [device] = dr.async_entries_for_config_entry(devices, entry.entry_id)

    devices.async_update_device(device.id, name_by_user="Castle")
    await hass.async_block_till_done()

    assert hass.states.get("camera.neuschwanstein").name == "Castle"


async def test_an_existing_camera_keeps_its_entity_id_and_name(hass, setup_entry):
    """The registry entry of a camera set up before has_entity_name.

    It was registered without has_entity_name and under an entity id that no
    longer follows from the entry title - the user renamed the entry since, or
    the id was changed by hand. Neither may move.
    """
    entry = make_entry(hass, title="Neuschwanstein Castle")
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "camera",
        DOMAIN,
        entry.unique_id,
        config_entry=entry,
        suggested_object_id="my_castle",
        original_name="Neuschwanstein",
        has_entity_name=False,
    )
    assert legacy.entity_id == "camera.my_castle"

    await setup_entry(entry)

    [entity] = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert entity.entity_id == "camera.my_castle"
    assert entity.has_entity_name is True
    # Now attached to the new device, and still called by the entry title: the
    # camera always took the title as its name, and the device takes it now.
    assert entity.device_id is not None
    assert hass.states.get("camera.my_castle").name == "Neuschwanstein Castle"


async def test_a_name_the_user_gave_the_entity_still_wins(hass, setup_entry):
    entry = make_entry(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "camera", DOMAIN, entry.unique_id, config_entry=entry
    )
    registry.async_update_entity(legacy.entity_id, name="Castle")

    await setup_entry(entry)

    assert hass.states.get(legacy.entity_id).name == "Castle"


async def test_a_yaml_camera_keeps_its_entity_id_and_name(hass, setup_yaml):
    """YAML cameras have no device, so the entity name is the whole name."""
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "camera",
        DOMAIN,
        unique_id_for_url(CAMERA_URL),
        suggested_object_id="castle",
        original_name="Schwangau - Neuschwanstein Castle",
        has_entity_name=False,
    )

    await setup_yaml(
        {"platform": DOMAIN, CONF_URL: CAMERA_URL, "name": "Schwangau - Castle"},
        {"platform": DOMAIN, CONF_URL: OTHER_CAMERA_URL, "name": "Venice"},
    )

    assert registry.async_get(legacy.entity_id).has_entity_name is True
    assert hass.states.get("camera.castle").name == "Schwangau - Castle"
    # And a new one is named the way it was before has_entity_name.
    venice = registry.async_get_entity_id(
        "camera", DOMAIN, unique_id_for_url(OTHER_CAMERA_URL)
    )
    assert venice == "camera.venice"
    assert hass.states.get("camera.venice").name == "Venice"
    assert registry.async_get(venice).device_id is None
