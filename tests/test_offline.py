"""A webcam that is offline on the site, and the Online sensor that says so.

An offline webcam's page still answers 200, so the camera used to stay
available and the card showed the page's poster - which has LIVE printed on it.
Nothing said the webcam was off; it looked like the integration was broken.
These tests serve trimmed copies of the two kinds of page and check what the
camera, its Online binary sensor and the backoff make of them.

The pages keep only what the scraper reads: the og:image, the breadcrumb, the
heading, and either the player's stream source or the OFFLINE block that takes
its place. Trimmed from the Rome - Pantheon (offline) and Venice - St Mark's
Square (online) pages as served on 2026-10-04.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import asyncio
import logging
import types
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.skylinewebcams import SkylineRuntimeData
from custom_components.skylinewebcams.binary_sensor import SkylineWebcamsOnlineSensor
from custom_components.skylinewebcams.camera import SkylineWebcamsCamera
from custom_components.skylinewebcams.const import (
    CONF_URL,
    DOMAIN,
    OFFLINE_RETRY_SECONDS,
)
from custom_components.skylinewebcams.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import CAMERA_URL, make_entry

CAMERA = "camera.neuschwanstein"
SENSOR = "binary_sensor.neuschwanstein_online"

HEAD = """
<head>
  <meta property="og:image" content="https://cdn.skylinewebcams.com/social165.jpg">
</head>
"""

BREADCRUMB = """
<ol class="breadcrumb">
  <li><meta itemprop="name" content="Live Cams"></li>
  <li><a href="/en/webcam/italia.html"><span>Italy</span></a></li>
  <li><a href="/en/webcam/italia/lazio.html"><span>Lazio</span></a></li>
  <li><a href="/en/webcam/italia/lazio/roma.html"><span>Rome</span></a></li>
</ol>
<h1>Rome - Pantheon Live cam</h1>
<h2>Rome, view of the Pantheon, Piazza della Rotonda</h2>
"""

OFFLINE_BLOCK = """
<div class="request off"><div style="position:relative">
  <img src="https://cdn.skylinewebcams.com/165.jpg" style="opacity:0.7"
       class="img-responsive" alt="Live Cam">
  <p style="position:absolute;top:40%"><strong>OFFLINE</strong></p>
</div></div>
"""

PLAYER = """
<script>
  var player = new Clappr.Player({
    poster: 'https://cdn.skylinewebcams.com/live165.jpg',
    source: 'livee.m3u8?a=token123',
  });
</script>
"""

OFFLINE_PAGE = f"<html>{HEAD}<body>{BREADCRUMB}{OFFLINE_BLOCK}</body></html>"
ONLINE_PAGE = f"<html>{HEAD}<body>{BREADCRUMB}{PLAYER}</body></html>"
# The page answers and has neither: what a change to the site's markup looks
# like from here.
NO_STREAM_PAGE = f"<html>{HEAD}<body>{BREADCRUMB}</body></html>"

STREAM_URL = "https://hd-auth.skylinewebcams.com/live.m3u8?a=token123"


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSite:
    """Serves whatever page it currently holds, and counts the requests."""

    def __init__(self, page: str, status: int = 200) -> None:
        self.page = page
        self.status = status
        self.requests = 0

    def get(self, url, headers=None):
        self.requests += 1
        return FakeResponse(self.status, self.page)


@pytest.fixture
def site():
    site = FakeSite(OFFLINE_PAGE)
    with patch(
        "custom_components.skylinewebcams.camera.async_create_clientsession",
        return_value=site,
    ):
        yield site


@pytest.fixture
async def entry(hass, stand_ins, site):
    """An entry set up the real way, against the fake site."""
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def look_again(hass, entry) -> str | None:
    """What a proxy request that proves the old URL dead would do."""
    url = await entry.runtime_data.camera.get_fresh_stream_url(force=True)
    await hass.async_block_till_done()
    return url


@pytest.mark.parametrize(
    "block",
    [
        OFFLINE_BLOCK,
        # Either half of the marker is enough on its own.
        '<div class="request off"><img src="https://cdn.skylinewebcams.com/165.jpg">'
        "</div>",
        '<div class="player-off"><p><strong> Offline </strong></p></div>',
    ],
    ids=["as-served", "div-only", "strong-only"],
)
async def test_an_offline_page_makes_an_offline_camera(hass, entry, site, block):
    site.page = f"<html>{HEAD}<body>{BREADCRUMB}{block}</body></html>"
    assert await look_again(hass, entry) is None

    camera = entry.runtime_data.camera
    assert camera.offline is True
    assert camera.is_streaming is False
    assert camera.available is True

    state = hass.states.get(CAMERA)
    # Idle, not streaming - and not unavailable: the page answered.
    assert state.state == "idle"
    assert state.attributes["offline"] is True
    # The rest of the page is still read: the card shows it around the poster.
    assert state.attributes["poster"] == "https://cdn.skylinewebcams.com/social165.jpg"
    assert state.attributes["place"] == "Rome"
    assert hass.states.get(SENSOR).state == STATE_OFF


async def test_setup_on_an_offline_page(hass, entry):
    """The very first look already says offline, nothing has to happen first."""
    assert hass.states.get(CAMERA).attributes["offline"] is True
    assert hass.states.get(CAMERA).state == "idle"
    assert hass.states.get(SENSOR).state == STATE_OFF


async def test_an_online_page_makes_an_online_camera(hass, entry, site):
    site.page = ONLINE_PAGE
    assert await look_again(hass, entry) == STREAM_URL

    state = hass.states.get(CAMERA)
    assert state.state == "streaming"
    assert state.attributes["offline"] is False
    assert hass.states.get(SENSOR).state == STATE_ON


async def test_coming_back_online_updates_camera_and_sensor(hass, entry, site, caplog):
    assert hass.states.get(SENSOR).state == STATE_OFF

    site.page = ONLINE_PAGE
    with caplog.at_level(logging.INFO, logger="custom_components.skylinewebcams"):
        assert await look_again(hass, entry) == STREAM_URL
        # And a second look at the same page has nothing new to say.
        await look_again(hass, entry)

    assert hass.states.get(CAMERA).attributes["offline"] is False
    assert hass.states.get(CAMERA).state == "streaming"
    assert hass.states.get(SENSOR).state == STATE_ON
    assert caplog.text.count("broadcasting again") == 1

    # And off again, the other way round.
    site.page = OFFLINE_PAGE
    assert await look_again(hass, entry) is None
    assert hass.states.get(CAMERA).attributes["offline"] is True
    assert hass.states.get(SENSOR).state == STATE_OFF


async def test_going_offline_drops_the_stream_url(hass, entry, site):
    """The URL from before points at a stream that has ended."""
    site.page = ONLINE_PAGE
    assert await look_again(hass, entry) == STREAM_URL

    site.page = OFFLINE_PAGE
    assert await look_again(hass, entry) is None

    camera = entry.runtime_data.camera
    assert camera._stream_url is None
    # And the cache does not hand it back either.
    assert await camera.get_fresh_stream_url() is None


async def test_a_page_error_is_still_unavailable(hass, entry, site):
    """Not offline: the page itself failed, and that is an outage."""
    site.page = ONLINE_PAGE
    await look_again(hass, entry)

    site.status = 503
    await look_again(hass, entry)

    assert hass.states.get(CAMERA).state == STATE_UNAVAILABLE
    # Nothing to say about the webcam when its page cannot be read.
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE

    site.status = 200
    await look_again(hass, entry)
    assert hass.states.get(CAMERA).state == "streaming"
    assert hass.states.get(SENSOR).state == STATE_ON


async def test_no_stream_and_no_marker_is_not_offline_and_logged_once(
    hass, entry, site, caplog
):
    site.page = ONLINE_PAGE
    await look_again(hass, entry)

    site.page = NO_STREAM_PAGE
    with caplog.at_level(logging.DEBUG, logger="custom_components.skylinewebcams"):
        await look_again(hass, entry)
        await look_again(hass, entry)
        await look_again(hass, entry)

    camera = entry.runtime_data.camera
    assert camera.offline is False
    assert camera.available is True
    assert hass.states.get(CAMERA).attributes["offline"] is False
    assert hass.states.get(SENSOR).state == STATE_ON
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "Found no stream" in r.getMessage()
    ]
    assert len(warnings) == 1


async def test_an_offline_webcam_is_looked_at_again_after_the_long_delay(
    hass, entry, site
):
    camera = entry.runtime_data.camera
    now = asyncio.get_running_loop().time()
    # Not the few seconds of the outage backoff.
    assert camera._retry_not_before - now == pytest.approx(OFFLINE_RETRY_SECONDS, abs=5)
    assert camera._fetch_failures == 0
    requests = site.requests

    # Inside the window, asking does not reach the site.
    assert await camera.get_fresh_stream_url() is None
    assert site.requests == requests

    # Nobody plays an offline webcam, so the camera looks again by itself.
    site.page = ONLINE_PAGE
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=OFFLINE_RETRY_SECONDS + 1)
    )
    await hass.async_block_till_done()

    assert site.requests == requests + 1
    assert hass.states.get(SENSOR).state == STATE_ON
    assert hass.states.get(CAMERA).attributes["offline"] is False
    assert camera._retry_not_before == 0.0
    assert camera._cancel_offline_recheck is None


def test_the_sensor_is_unknown_until_the_page_has_been_read():
    """Before the first look nobody knows, and the sensor must not guess."""
    runtime_data = SkylineRuntimeData()
    sensor = SkylineWebcamsOnlineSensor(
        types.SimpleNamespace(
            runtime_data=runtime_data,
            unique_id="skylinewebcams.com/webcam/test",
            entry_id="entry1",
            title="Test Cam",
            data={CONF_URL: CAMERA_URL},
        )
    )
    assert sensor.unique_id == "skylinewebcams.com/webcam/test_online"

    # The platforms are set up side by side: no camera yet.
    assert sensor.available is False
    assert sensor.is_on is None

    camera = SkylineWebcamsCamera(
        hass=None, url=CAMERA_URL, name="Test Cam", unique_id="t", entry_id="entry1"
    )
    runtime_data.camera = camera
    # A camera, but its page has not been read yet.
    assert sensor.available is True
    assert sensor.is_on is None

    camera._offline = True
    assert sensor.is_on is False
    camera._offline = False
    assert sensor.is_on is True
    camera._attr_available = False
    assert sensor.available is False


async def test_the_sensor_belongs_to_the_webcams_device(hass, entry):
    registry = er.async_get(hass)
    camera = registry.async_get(CAMERA)
    sensor = registry.async_get(SENSOR)

    assert sensor.unique_id == f"{camera.unique_id}_online"
    assert sensor.device_id == camera.device_id
    assert sensor.has_entity_name is True
    assert sensor.translation_key == "online"
    assert sensor.original_device_class == "connectivity"
    assert hass.states.get(SENSOR).name == "Neuschwanstein Online"


async def test_unloading_the_entry_takes_the_sensor_along(hass, entry):
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE


async def test_unloading_cancels_the_scheduled_look(hass, entry, site):
    camera = entry.runtime_data.camera
    assert camera._cancel_offline_recheck is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert camera._cancel_offline_recheck is None

    requests = site.requests
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=OFFLINE_RETRY_SECONDS + 1)
    )
    await hass.async_block_till_done()
    assert site.requests == requests


async def test_diagnostics_report_the_offline_flag(hass, entry):
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["camera"]["offline"] is True
    assert diagnostics["camera"]["attributes"]["offline"] is True
    assert diagnostics["camera"]["available"] is True


async def test_a_yaml_camera_says_offline_too_but_gets_no_sensor(hass, stand_ins, site):
    """YAML cameras have no entry and no device, so no sensor - only the flag."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(
        hass,
        "camera",
        {"camera": [{"platform": DOMAIN, CONF_URL: CAMERA_URL, "name": "Castle"}]},
    )
    await hass.async_block_till_done()

    state = hass.states.get("camera.castle")
    assert state.attributes["offline"] is True
    assert state.state == "idle"
    assert hass.states.async_entity_ids("binary_sensor") == []

    # It looks again by itself as well; taking it out cancels that.
    [camera] = hass.data[DOMAIN].values()
    assert camera._cancel_offline_recheck is not None
    await camera.async_remove()
    assert camera._cancel_offline_recheck is None
