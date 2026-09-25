"""Where the cameras live: the entry's runtime data, or hass.data for YAML.

An entry's camera used to sit in `hass.data[DOMAIN]` beside the YAML ones,
under its entry id. It now lives on the entry itself, which Home Assistant
clears when the entry unloads. The YAML cameras have no entry, so they stay
where they were, and the proxy has to find both.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import types

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.skylinewebcams.camera import (
    SkylineWebcamsHlsProxyView,
    async_setup_platform,
)
from custom_components.skylinewebcams.const import CONF_URL, DOMAIN
from custom_components.skylinewebcams.helpers import (
    async_camera_for_key,
    async_running_cameras,
)

from .conftest import CAMERA_URL, make_entry


async def test_an_entry_keeps_its_camera_in_runtime_data(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    camera = entry.runtime_data.camera
    assert camera is not None
    assert camera.entity_id == "camera.neuschwanstein"
    # Not in the domain-wide dict any more: that one is for YAML cameras only.
    assert entry.entry_id not in hass.data[DOMAIN]
    assert async_camera_for_key(hass, entry.entry_id) is camera
    assert (entry.entry_id, camera) in list(async_running_cameras(hass))


async def test_an_unloaded_entry_is_not_proxied_any_more(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert async_camera_for_key(hass, entry.entry_id) is None
    view = SkylineWebcamsHlsProxyView(hass)
    response = await view.get(
        types.SimpleNamespace(path="/", query={}), f"{entry.entry_id}.m3u8"
    )
    assert response.status == 404


async def test_a_yaml_camera_is_still_found_by_its_url_hash(hass):
    # As in test_unique_id_migration: the view is not registered here.
    hass.data[DOMAIN] = {}
    added: list = []
    await async_setup_platform(
        hass,
        {CONF_URL: CAMERA_URL, "name": "Neuschwanstein"},
        lambda entities, update_before_add=False: added.extend(entities),
    )

    [camera] = added
    assert async_camera_for_key(hass, camera._entry_id) is camera
    assert (camera._entry_id, camera) in list(async_running_cameras(hass))


async def test_a_key_that_is_nobodys_finds_nothing(hass):
    assert async_camera_for_key(hass, "0" * 32) is None
    # Right shape, but the entry of another integration.
    other = MockConfigEntry(domain="somebody_else")
    other.add_to_hass(hass)
    assert async_camera_for_key(hass, other.entry_id) is None
