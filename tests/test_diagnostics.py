"""Diagnostics: what they report, and that the stream's token is not in it.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import json

from homeassistant.components.diagnostics import REDACTED

from custom_components.skylinewebcams.camera import SkylineWebcamsCamera
from custom_components.skylinewebcams.diagnostics import (
    async_get_config_entry_diagnostics,
    redact_url_query,
)

from .conftest import CAMERA_URL, STREAM_URL, make_entry


async def test_diagnostics_describe_the_camera(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"] == {
        "title": "Neuschwanstein",
        "version": 2,
        "unique_id": entry.unique_id,
        "data": {"url": CAMERA_URL},
    }
    camera = diagnostics["camera"]
    assert camera["entity_id"] == "camera.neuschwanstein"
    assert camera["available"] is True
    assert camera["attributes"]["source"] == CAMERA_URL
    assert (
        camera["stream_url"]
        == f"https://hd-auth.skylinewebcams.com/live.m3u8?{REDACTED}"
    )
    assert camera["stream_url_age_seconds"] is not None
    assert camera["fetch_failures"] == 0
    assert camera["backoff_remaining_seconds"] == 0
    # The file is serialised as JSON; everything in it has to survive that.
    json.dumps(diagnostics)


async def test_diagnostics_leave_out_what_opens_the_stream(hass, setup_entry):
    """The signed stream URL, and the entry id the unauthenticated proxy keys on."""
    entry = make_entry(hass)
    await setup_entry(entry)
    assert entry.runtime_data.camera._stream_url == STREAM_URL

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    dumped = json.dumps(diagnostics)

    assert "secret-token" not in dumped
    assert entry.entry_id not in dumped
    assert diagnostics["camera"]["attributes"]["entry_id"] == REDACTED


async def test_diagnostics_of_an_unloaded_entry(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)
    assert await hass.config_entries.async_unload(entry.entry_id)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["camera"] is None
    assert diagnostics["entry"]["title"] == "Neuschwanstein"


async def test_a_camera_that_never_got_a_stream_url():
    """Nothing to redact and no age to report, and nothing to fail on either."""
    camera = SkylineWebcamsCamera(
        hass=None, url=CAMERA_URL, name="Test Cam", unique_id="test", entry_id="cam1"
    )

    state = camera.as_diagnostics()

    assert state["stream_url"] is None
    assert state["stream_url_age_seconds"] is None
    assert redact_url_query(state["stream_url"]) is None
    assert redact_url_query("") == ""


def test_only_the_query_is_redacted():
    assert (
        redact_url_query("https://hd-auth.skylinewebcams.com/live.m3u8?a=abc&b=1")
        == f"https://hd-auth.skylinewebcams.com/live.m3u8?{REDACTED}"
    )
    assert redact_url_query(CAMERA_URL) == CAMERA_URL
