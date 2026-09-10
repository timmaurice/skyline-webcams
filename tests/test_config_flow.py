"""Tests for the config flow: URL validation, ids, and error recovery.

The manual step used to fetch whatever host was typed and only afterwards run a
substring check on it, it had no timeout, and it keyed entries on the raw URL,
so two spellings of the same camera became two entries. The browse path aborted
the whole flow on any fetch failure.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

import asyncio

import aiohttp
import pytest

from custom_components.skylinewebcams import config_flow
from custom_components.skylinewebcams.config_flow import (
    ConfigFlow,
    is_webcam_url,
    unique_id_for_url,
    validate_input,
)
from custom_components.skylinewebcams.const import CONF_URL

CAMERA_URL = (
    "https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/"
    "schloss-neuschwanstein.html"
)


class FakeHass:
    """Just enough hass for the flow: an executor that runs inline."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)


class FakeResponse:
    def __init__(
        self, status=200, text="<html><h1>Venice <span>live</span></h1></html>"
    ):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records every URL it is asked for."""

    def __init__(self, response=None, error=None):
        self.requested = []
        self._response = response or FakeResponse()
        self._error = error

    def get(self, url, headers=None):
        self.requested.append(url)
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def session(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: fake)
    return fake


@pytest.mark.parametrize(
    "url",
    [
        CAMERA_URL,
        "http://skylinewebcams.com/en/webcam/x.html",
        "https://hd-auth.skylinewebcams.com/live.m3u8",
    ],
)
def test_accepts_the_upstream_site(url):
    assert is_webcam_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://192.168.1.1/",
        # The old substring check let this one through - after fetching it.
        "https://evil.example/?x=skylinewebcams.com",
        "https://skylinewebcams.com.evil.example/webcam.html",
        "file:///etc/passwd",
        "ftp://www.skylinewebcams.com/x",
    ],
)
def test_rejects_anything_else(url):
    assert is_webcam_url(url) is False


async def test_a_foreign_url_is_never_fetched(session):
    """The host check has to run before the request, not after it."""
    with pytest.raises(ValueError, match="invalid_url"):
        await validate_input(FakeHass(), {CONF_URL: "http://192.168.1.1/"})

    assert session.requested == []


async def test_the_title_comes_from_a_heading_with_child_tags(session):
    """h1.string is None as soon as the heading has a child tag."""
    info = await validate_input(FakeHass(), {CONF_URL: CAMERA_URL})

    assert info == {"title": "Venice live"}
    assert session.requested == [CAMERA_URL]


async def test_a_hanging_request_gives_up(monkeypatch):
    """Without a timeout the flow sat there for as long as the host wanted."""

    class HangingSession:
        def get(self, url, headers=None):
            class Hang:
                async def __aenter__(self):
                    await asyncio.sleep(3600)

                async def __aexit__(self, *exc):
                    return False

            return Hang()

    monkeypatch.setattr(
        config_flow, "async_get_clientsession", lambda hass: HangingSession()
    )
    monkeypatch.setattr(config_flow, "VALIDATE_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(ValueError, match="cannot_connect"):
        await validate_input(FakeHass(), {CONF_URL: CAMERA_URL})


async def test_a_network_error_is_reported_as_cannot_connect(monkeypatch):
    monkeypatch.setattr(
        config_flow,
        "async_get_clientsession",
        lambda hass: FakeSession(error=aiohttp.ClientError("boom")),
    )

    with pytest.raises(ValueError, match="cannot_connect"):
        await validate_input(FakeHass(), {CONF_URL: CAMERA_URL})


@pytest.mark.parametrize(
    "variant",
    [
        CAMERA_URL,
        CAMERA_URL.replace("/en/", "/de/"),
        CAMERA_URL + "?",
        CAMERA_URL.replace("https://www.", "http://"),
        CAMERA_URL.upper().replace("HTTPS://WWW.", "https://www."),
    ],
)
def test_one_id_per_camera_however_it_is_spelled(variant):
    assert unique_id_for_url(variant) == unique_id_for_url(CAMERA_URL)


def test_different_cameras_keep_different_ids():
    other = CAMERA_URL.replace("schloss-neuschwanstein", "hohenschwangau")
    assert unique_id_for_url(other) != unique_id_for_url(CAMERA_URL)


def make_flow():
    flow = ConfigFlow()
    flow.hass = FakeHass()
    return flow


class FailingScraper:
    def __init__(self, *args, **kwargs):
        pass

    async def get_structure(self):
        raise aiohttp.ClientError("boom")

    async def get_locations_or_cameras(self, url):
        raise aiohttp.ClientError("boom")


async def test_a_broken_directory_shows_the_language_form_again(monkeypatch, session):
    """It used to abort, so the user had to restart the flow from scratch."""
    monkeypatch.setattr(config_flow, "SkylineWebcamsScraper", FailingScraper)
    flow = make_flow()

    result = await flow.async_step_continent()

    assert result["type"] == "form"
    assert result["step_id"] == "language"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_a_broken_page_keeps_the_list_the_user_came_from(monkeypatch, session):
    monkeypatch.setattr(config_flow, "SkylineWebcamsScraper", FailingScraper)
    flow = make_flow()
    flow._last_browse_options = {CAMERA_URL: "Neuschwanstein"}

    result = await flow.async_step_browse(
        url="https://www.skylinewebcams.com/en/x.html"
    )

    assert result["type"] == "form"
    assert result["step_id"] == "browse"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_a_page_without_items_is_an_error_not_an_abort(monkeypatch, session):
    class EmptyScraper(FailingScraper):
        async def get_locations_or_cameras(self, url):
            return {"type": "list", "items": []}

    monkeypatch.setattr(config_flow, "SkylineWebcamsScraper", EmptyScraper)
    flow = make_flow()
    flow._last_browse_options = {CAMERA_URL: "Neuschwanstein"}

    result = await flow.async_step_browse(
        url="https://www.skylinewebcams.com/en/x.html"
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_items_found"}


async def test_a_browse_list_is_remembered_for_the_next_error(monkeypatch, session):
    class ListScraper(FailingScraper):
        async def get_locations_or_cameras(self, url):
            return {
                "type": "list",
                "items": [{"url": CAMERA_URL, "name": "Neuschwanstein"}],
            }

    monkeypatch.setattr(config_flow, "SkylineWebcamsScraper", ListScraper)
    flow = make_flow()

    result = await flow.async_step_browse(
        url="https://www.skylinewebcams.com/en/x.html"
    )

    assert result["step_id"] == "browse"
    assert flow._last_browse_options == {CAMERA_URL: "Neuschwanstein"}
