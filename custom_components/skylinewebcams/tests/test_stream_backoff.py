"""Tests for the backoff around fetching a fresh stream URL.

A camera whose page has gone away used to be re-scraped on every request the
proxy served, which hammered skylinewebcams.com for a result that was not going
to change. These pin the pause down.

The async cases drive the event loop themselves, so the file runs with a plain
pytest and does not depend on an asyncio plugin being present.
"""

import asyncio

import pytest

from custom_components.skylinewebcams.camera import (
    FETCH_BACKOFF_BASE_SECONDS,
    FETCH_BACKOFF_MAX_SECONDS,
    MAX_BACKOFF_FAILURES,
    SkylineWebcamsCamera,
)

STREAM_URL = "https://hd-auth.skylinewebcams.com/live.m3u8?a=token123"


def make_camera():
    return SkylineWebcamsCamera(
        hass=None,
        url="https://www.skylinewebcams.com/en/webcam/test.html",
        name="Test Cam",
        unique_id="test",
        entry_id="cam1",
    )


def count_fetches(camera, result):
    """Replace the scrape with a counter, returning the counter list."""
    calls = []

    async def _fetch():
        calls.append(1)
        return result

    camera._fetch_stream_url = _fetch
    return calls


def test_failed_fetch_is_not_retried_immediately():
    asyncio.run(_test_failed_fetch_is_not_retried_immediately())


async def _test_failed_fetch_is_not_retried_immediately():
    """The second request inside the window must not reach the site again."""
    camera = make_camera()
    calls = count_fetches(camera, None)

    await camera.get_fresh_stream_url()
    await camera.get_fresh_stream_url()

    assert len(calls) == 1
    assert camera._retry_not_before > 0


def test_backoff_grows_and_stops_at_the_cap():
    asyncio.run(_test_backoff_grows_and_stops_at_the_cap())


async def _test_backoff_grows_and_stops_at_the_cap():
    """Each failure waits longer, and the wait never exceeds the cap."""
    camera = make_camera()
    count_fetches(camera, None)
    delays = []

    for _ in range(12):
        camera._retry_not_before = 0.0
        before = asyncio.get_event_loop().time()
        await camera.get_fresh_stream_url()
        delays.append(camera._retry_not_before - before)

    assert delays[0] == pytest.approx(FETCH_BACKOFF_BASE_SECONDS, abs=1)
    assert delays[1] > delays[0]
    assert max(delays) <= FETCH_BACKOFF_MAX_SECONDS + 1
    assert delays[-1] == pytest.approx(FETCH_BACKOFF_MAX_SECONDS, abs=1)


def test_backing_off_still_serves_the_cached_url():
    asyncio.run(_test_backing_off_still_serves_the_cached_url())


async def _test_backing_off_still_serves_the_cached_url():
    """A stale URL beats no URL, and matches what a failed fetch returns."""
    camera = make_camera()
    camera._stream_url = STREAM_URL
    camera._last_update = -10000  # force the cache to look expired
    count_fetches(camera, None)

    assert await camera.get_fresh_stream_url() == STREAM_URL  # the failure
    assert await camera.get_fresh_stream_url() == STREAM_URL  # inside the window


def test_success_clears_the_backoff():
    asyncio.run(_test_success_clears_the_backoff())


async def _test_success_clears_the_backoff():
    """A camera that recovers must not keep waiting out an old penalty."""
    camera = make_camera()
    count_fetches(camera, None)
    await camera.get_fresh_stream_url()
    assert camera._fetch_failures == 1

    camera._retry_not_before = 0.0
    count_fetches(camera, STREAM_URL)
    assert await camera.get_fresh_stream_url() == STREAM_URL

    assert camera._fetch_failures == 0
    assert camera._retry_not_before == 0.0


def test_failure_count_stops_at_the_cap():
    asyncio.run(_test_failure_count_stops_at_the_cap())


async def _test_failure_count_stops_at_the_cap():
    """Counting past the cap only feeds a bigger power to a clamped value."""
    camera = make_camera()
    count_fetches(camera, None)

    for _ in range(20):
        camera._retry_not_before = 0.0
        await camera.get_fresh_stream_url()

    assert camera._fetch_failures == MAX_BACKOFF_FAILURES


def test_forced_refresh_ignores_the_backoff():
    asyncio.run(_test_forced_refresh_ignores_the_backoff())


async def _test_forced_refresh_ignores_the_backoff():
    """The proxy forces a refresh when it knows the cached URL is dead.

    Handing that URL back because a backoff window happens to be open would
    cost another doomed upstream fetch and turn a clean 502 into a playlist
    without any segments.
    """
    camera = make_camera()
    camera._stream_url = STREAM_URL
    calls = count_fetches(camera, None)

    await camera.get_fresh_stream_url()  # fails, opens the window
    assert await camera.get_fresh_stream_url() == STREAM_URL
    assert len(calls) == 1  # the window held

    count_fetches(camera, STREAM_URL + "&fresh=1")
    assert await camera.get_fresh_stream_url(force=True) == STREAM_URL + "&fresh=1"
