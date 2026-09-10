"""Tests around fetching the stream URL: one request at a time, quiet logs.

Startup used to ask three times per camera in the same millisecond, and every
failure was logged at ERROR, which produced 61 error lines in three minutes for
six cameras during the QA run.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

import asyncio
import logging

import aiohttp
import pytest

from custom_components.skylinewebcams.camera import SkylineWebcamsCamera

PAGE = """
<html><body>
  <h2>A nice view</h2>
  <script>source: 'livee.m3u8?a=token123'</script>
</body></html>
"""


class FakeHass:
    """Records the jobs the camera hands to the executor."""

    def __init__(self):
        self.executor_jobs = []

    async def async_add_executor_job(self, func, *args):
        self.executor_jobs.append(func)
        return func(*args)


class FakeResponse:
    def __init__(self, status=200, text=PAGE, error=None):
        self.status = status
        self._text = text
        self._error = error

    async def text(self):
        # Yield, the way a real read does: without a hand-off point the tasks
        # would run one after the other and never overlap.
        await asyncio.sleep(0)
        if self._error:
            raise self._error
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Counts requests and answers with whatever it was handed."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = 0

    def get(self, url, headers=None):
        self.requests += 1
        response = self._responses[min(self.requests - 1, len(self._responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response


def make_camera(session, hass=None):
    camera = SkylineWebcamsCamera(
        hass=hass or FakeHass(),
        url="https://www.skylinewebcams.com/en/webcam/test.html",
        name="Test Cam",
        unique_id="test",
        entry_id="cam1",
    )
    camera.get_session = lambda: session
    return camera


async def test_concurrent_callers_share_a_single_scrape():
    """Startup asks from three directions; the site must see one request."""
    session = FakeSession([FakeResponse()])
    camera = make_camera(session)

    urls = await asyncio.gather(
        camera.get_fresh_stream_url(),
        camera.get_fresh_stream_url(),
        camera.get_fresh_stream_url(),
    )

    assert session.requests == 1
    assert (
        urls
        == [
            "https://hd-auth.skylinewebcams.com/live.m3u8?a=token123",
        ]
        * 3
    )


async def test_page_is_parsed_off_the_event_loop():
    """BeautifulSoup on a few hundred kB stalls the loop, so it goes to a thread."""
    hass = FakeHass()
    camera = make_camera(FakeSession([FakeResponse()]), hass=hass)

    await camera.get_fresh_stream_url()

    assert [job.__name__ for job in hass.executor_jobs] == ["BeautifulSoup"]


async def test_repeated_failures_are_logged_once_at_error(caplog):
    """One ERROR per outage, not one per attempt."""
    error = aiohttp.ClientError("boom")
    camera = make_camera(FakeSession([error]))

    with caplog.at_level(logging.DEBUG):
        await camera.get_fresh_stream_url()
        # force, so the backoff does not swallow the second attempt
        await camera.get_fresh_stream_url(force=True)
        await camera.get_fresh_stream_url(force=True)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    debugs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "Network error" in r.getMessage()
    ]
    assert len(errors) == 1
    assert len(debugs) == 2


async def test_recovery_is_logged_once_at_info(caplog):
    """And the log says when the camera came back."""
    session = FakeSession([aiohttp.ClientError("boom"), FakeResponse()])
    camera = make_camera(session)

    with caplog.at_level(logging.DEBUG):
        await camera.get_fresh_stream_url()
        await camera.get_fresh_stream_url(force=True)

    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("reachable again" in message for message in infos)
    assert camera._failure_logged is False


async def test_a_non_200_page_is_logged_like_a_network_error(caplog):
    """A 404 for the page is the same outage, so it follows the same rule."""
    camera = make_camera(FakeSession([FakeResponse(status=404)]))

    with caplog.at_level(logging.DEBUG):
        await camera.get_fresh_stream_url()
        await camera.get_fresh_stream_url(force=True)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "answered 404" in errors[0].getMessage()


@pytest.mark.parametrize("force", [False, True])
async def test_cached_url_is_served_without_a_request(force):
    """The cache still short-circuits, and force still goes past it."""
    session = FakeSession([FakeResponse()])
    camera = make_camera(session)

    await camera.get_fresh_stream_url()
    await camera.get_fresh_stream_url(force=force)

    assert session.requests == (2 if force else 1)


async def test_concurrent_forced_callers_share_a_single_scrape():
    """A token expiring under six viewers must cost one request, not six.

    The proxy forces a refresh per playlist request, so every viewer of one
    camera arrives here at the same moment. Serialising them behind the lock
    made the last one wait for six scrapes.
    """
    session = FakeSession([FakeResponse()])
    camera = make_camera(session)

    await camera.get_fresh_stream_url()  # the URL the viewers are holding
    assert session.requests == 1

    urls = await asyncio.gather(
        *[camera.get_fresh_stream_url(force=True) for _ in range(6)]
    )

    assert session.requests == 2
    assert set(urls) == {"https://hd-auth.skylinewebcams.com/live.m3u8?a=token123"}


async def test_concurrent_forced_callers_share_a_failed_scrape_too():
    """An attempt that came back empty answers the callers behind it as well."""
    session = FakeSession(
        [FakeResponse(), FakeResponse(error=aiohttp.ClientError("boom"))]
    )
    camera = make_camera(session)

    await camera.get_fresh_stream_url()
    await asyncio.gather(*[camera.get_fresh_stream_url(force=True) for _ in range(6)])

    assert session.requests == 2


async def test_a_forced_caller_is_never_served_the_entry_it_asked_about():
    """force still means a scrape when nothing has happened in the meantime."""
    session = FakeSession([FakeResponse()])
    camera = make_camera(session)

    await camera.get_fresh_stream_url()
    await camera.get_fresh_stream_url(force=True)
    await camera.get_fresh_stream_url(force=True)

    assert session.requests == 3


async def test_an_unexpected_error_arms_the_backoff_and_is_logged_once(caplog):
    """A failure that is not a ClientError is still an outage.

    It used to escape the handler: the lock released cleanly but no backoff was
    armed, so the next proxy request scraped again straight away and Home
    Assistant logged the traceback at ERROR every cycle.
    """
    camera = make_camera(FakeSession([RuntimeError("bs4 blew up")]))

    with caplog.at_level(logging.DEBUG):
        assert await camera.get_fresh_stream_url() is None
        assert camera._retry_not_before > 0
        assert camera._attr_available is False
        assert camera._fetch_lock.locked() is False

        assert await camera.get_fresh_stream_url(force=True) is None

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    debugs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and "Unexpected error" in r.getMessage()
    ]
    assert len(errors) == 1
    assert "bs4 blew up" in errors[0].getMessage()
    assert len(debugs) == 1


async def test_a_non_200_page_writes_the_unavailability_out(caplog):
    """Marking the entity unavailable without writing it changes nothing."""
    camera = make_camera(FakeSession([FakeResponse(status=404)]))
    camera.entity_id = "camera.test_cam"
    writes = []
    camera.async_write_ha_state = lambda: writes.append(1)

    with caplog.at_level(logging.DEBUG):
        assert await camera.get_fresh_stream_url() is None

    assert camera._attr_available is False
    assert writes == [1]
