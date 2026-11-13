"""A page that fails to load now and then must not take a playing stream down.

A single failed scrape of the webcam's page used to make the camera unavailable
on the spot, although the stream URL it already held went on playing; and
nothing looked at the page again until a viewer or a manual action asked. Now a
camera with a stream URL stays available through failed scrapes until
UNAVAILABLE_AFTER_FAILURES of them in a row have failed, or until the proxy
finds the stream itself dead. Each failure schedules the next look.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import types
from datetime import timedelta
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.const import STATE_ON, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.skylinewebcams.camera import (
    FETCH_BACKOFF_MAX_SECONDS,
    UNAVAILABLE_AFTER_FAILURES,
    SkylineWebcamsHlsProxyView,
)

from .conftest import CAMERA_URL, make_entry

CAMERA = "camera.neuschwanstein"
SENSOR = "binary_sensor.neuschwanstein_online"
STREAM_URL = "https://hd-auth.skylinewebcams.com/live.m3u8?a=token123"
PAGE = """
<html><body><h1>Neuschwanstein</h1>
<script>var player = new Clappr.Player({source: 'livee.m3u8?a=token123'});</script>
</body></html>
"""


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSite:
    """The webcam's page and its stream, each failing on demand."""

    def __init__(self) -> None:
        self.page_status = 200
        self.page_error: Exception | None = None
        self.stream_status = 200
        self.page_requests = 0

    def get(self, url, headers=None):
        if url == CAMERA_URL:
            self.page_requests += 1
            if self.page_error is not None:
                raise self.page_error
            return FakeResponse(self.page_status, PAGE)
        return FakeResponse(self.stream_status, "#EXTM3U\n#EXTINF:6.0,\nseg1.ts\n")


@pytest.fixture
def site():
    site = FakeSite()
    with patch(
        "custom_components.skylinewebcams.camera.async_create_clientsession",
        return_value=site,
    ):
        yield site


@pytest.fixture
async def entry(hass, stand_ins, site):
    """An entry set up the real way, playing, against the fake site."""
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(CAMERA).state == "streaming"
    return entry


async def look_again(hass, entry) -> str | None:
    url = await entry.runtime_data.camera.get_fresh_stream_url(force=True)
    await hass.async_block_till_done()
    return url


async def fire_the_scheduled_look(hass) -> None:
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=FETCH_BACKOFF_MAX_SECONDS + 1)
    )
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "fail",
    [
        lambda site: setattr(site, "page_status", 503),
        lambda site: setattr(site, "page_error", aiohttp.ClientError("boom")),
    ],
    ids=["error-status", "network-error"],
)
async def test_one_failed_scrape_keeps_the_stream(hass, entry, site, fail):
    fail(site)

    assert await look_again(hass, entry) == STREAM_URL

    camera = entry.runtime_data.camera
    assert camera.available is True
    assert camera._stream_url == STREAM_URL
    assert hass.states.get(CAMERA).state == "streaming"
    assert hass.states.get(SENSOR).state == STATE_ON


async def test_failures_in_a_row_make_the_camera_unavailable(hass, entry, site):
    site.page_status = 503

    for _ in range(UNAVAILABLE_AFTER_FAILURES - 1):
        await look_again(hass, entry)
        assert hass.states.get(CAMERA).state == "streaming"

    await look_again(hass, entry)
    assert hass.states.get(CAMERA).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE


async def test_a_good_scrape_in_between_starts_the_count_again(hass, entry, site):
    for _ in range(3):
        site.page_status = 503
        for _ in range(UNAVAILABLE_AFTER_FAILURES - 1):
            await look_again(hass, entry)
        site.page_status = 200
        await look_again(hass, entry)

    assert hass.states.get(CAMERA).state == "streaming"


async def test_a_failed_scrape_schedules_the_next_look(hass, entry, site):
    """Nobody has to ask: the camera looks again by itself."""
    site.page_status = 503
    await look_again(hass, entry)
    camera = entry.runtime_data.camera
    assert camera._cancel_recheck is not None
    requests = site.page_requests

    site.page_status = 200
    await fire_the_scheduled_look(hass)

    assert site.page_requests == requests + 1
    assert camera.page_failing is False
    assert camera._cancel_recheck is None


async def test_an_unavailable_camera_recovers_by_itself(hass, entry, site):
    site.page_status = 503
    for _ in range(UNAVAILABLE_AFTER_FAILURES):
        await look_again(hass, entry)
    assert hass.states.get(CAMERA).state == STATE_UNAVAILABLE

    site.page_status = 200
    await fire_the_scheduled_look(hass)

    assert hass.states.get(CAMERA).state == "streaming"
    assert hass.states.get(SENSOR).state == STATE_ON
    assert entry.runtime_data.camera._fetch_failures == 0


async def test_without_a_stream_url_a_failure_is_unavailable_at_once(
    hass, stand_ins, site
):
    """Nothing to fall back on, so there is nothing to keep available."""
    site.page_status = 503
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CAMERA).state == STATE_UNAVAILABLE

    site.page_status = 200
    await fire_the_scheduled_look(hass)
    assert hass.states.get(CAMERA).state == "streaming"


async def proxy_the_playlist(hass, camera):
    view = SkylineWebcamsHlsProxyView(hass)
    request = types.SimpleNamespace(
        path=f"/api/skylinewebcams_proxy/{camera.proxy_token}.m3u8", query={}
    )
    response = await view.get(request, f"{camera.proxy_token}.m3u8")
    await hass.async_block_till_done()
    return response


async def test_a_dead_stream_while_the_page_fails_is_unavailable(hass, entry, site):
    """The cached URL kept it available; once that is dead too, nothing does."""
    site.page_status = 503
    await look_again(hass, entry)
    assert hass.states.get(CAMERA).state == "streaming"

    site.stream_status = 403
    response = await proxy_the_playlist(hass, entry.runtime_data.camera)

    assert response.status == 403
    assert hass.states.get(CAMERA).state == STATE_UNAVAILABLE
    assert entry.runtime_data.camera._stream_url is None


async def test_a_dead_stream_while_the_page_answers_changes_nothing(hass, entry, site):
    """The next scrape replaces the URL; no reason to give up on the camera."""
    site.stream_status = 403
    response = await proxy_the_playlist(hass, entry.runtime_data.camera)

    assert response.status == 403
    assert hass.states.get(CAMERA).state == "streaming"
    assert entry.runtime_data.camera._stream_url == STREAM_URL
