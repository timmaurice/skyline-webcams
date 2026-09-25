"""Tests for the HLS proxy view: host allow-list, proxy and segment tokens.

The proxy is served without authentication so the browser can play the stream,
so it must never fetch a URL that a caller supplies, and it must only answer
for a camera whose random proxy token the caller knows - not its entry id.
These tests pin that behaviour down.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

import types

import pytest

from custom_components.skylinewebcams.camera import (
    SkylineWebcamsCamera,
    SkylineWebcamsHlsProxyView,
    is_allowed_stream_url,
)
from custom_components.skylinewebcams.const import DOMAIN

STREAM_URL = "https://hd-auth.skylinewebcams.com/live.m3u8?a=token123"
SEGMENT_URL = "https://hd-auth.skylinewebcams.com/segment1.ts?a=token123"

PLAYLIST = (
    "#EXTM3U\n"
    "#EXT-X-VERSION:3\n"
    "#EXTINF:6.0,\n"
    "segment1.ts\n"
    "#EXTINF:6.0,\n"
    "https://evil.example/steal.ts\n"
)


class FakeResponse:
    """Minimal stand-in for an aiohttp response."""

    def __init__(self, status=200, headers=None, body=b"", text=""):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._text = text

    async def text(self):
        return self._text

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records every URL the proxy tries to fetch."""

    def __init__(self, response):
        self.requested = []
        self._response = response

    def get(self, url, headers=None):
        self.requested.append(url)
        return self._response


def make_camera(response):
    """Build a camera with a real token store and a faked network."""
    camera = SkylineWebcamsCamera(
        hass=None,
        url="https://www.skylinewebcams.com/en/webcam/test.html",
        name="Test Cam",
        unique_id="test",
        entry_id="cam1",
    )
    session = FakeSession(response)
    camera.get_session = lambda: session
    camera.get_fresh_stream_url = _returns(STREAM_URL)
    return camera, session


def _returns(value):
    async def _inner():
        return value

    return _inner


def make_view(*cameras):
    """A view over YAML-style cameras; no config entries in play."""
    hass = types.SimpleNamespace(
        data={DOMAIN: {camera._entry_id: camera for camera in cameras}},
        config_entries=types.SimpleNamespace(async_entries=lambda domain: []),
    )
    return SkylineWebcamsHlsProxyView(hass)


def make_request(path, query=None):
    return types.SimpleNamespace(path=path, query=query or {})


@pytest.mark.parametrize(
    "url",
    [
        "https://hd-auth.skylinewebcams.com/live.m3u8",
        "https://www.skylinewebcams.com/en/webcam/test.html",
        "https://skylinewebcams.com/a.ts",
        "http://skylinewebcams.com/a.ts",
    ],
)
def test_allows_upstream_urls(url):
    assert is_allowed_stream_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8123/api/",
        "http://192.168.178.1/",
        "http://169.254.169.254/latest/meta-data/",
        "https://evil-skylinewebcams.com/a.ts",
        "https://skylinewebcams.com.evil.test/a.ts",
        "file:///etc/passwd",
        "",
        None,
    ],
)
def test_rejects_foreign_urls(url):
    assert is_allowed_stream_url(url) is False


def test_segment_token_is_stable_and_opaque():
    camera, _ = make_camera(FakeResponse())
    token = camera.register_segment_url(SEGMENT_URL)

    assert token != SEGMENT_URL
    assert SEGMENT_URL not in token
    assert camera.register_segment_url(SEGMENT_URL) == token
    assert camera.resolve_segment_url(token) == SEGMENT_URL
    assert camera.resolve_segment_url("f" * 32) is None


def test_segment_table_is_bounded():
    camera, _ = make_camera(FakeResponse())
    camera._segment_capacity = 3
    tokens = [camera.register_segment_url(f"{SEGMENT_URL}&i={i}") for i in range(5)]

    assert camera.resolve_segment_url(tokens[0]) is None
    assert camera.resolve_segment_url(tokens[-1]) is not None


async def test_playlist_is_rewritten_to_tokens():
    response = FakeResponse(
        headers={"Content-Type": "application/vnd.apple.mpegurl"}, text=PLAYLIST
    )
    camera, _ = make_camera(response)
    view = make_view(camera)

    key = f"{camera.proxy_token}.m3u8"
    result = await view.get(make_request(f"/api/skylinewebcams_proxy/{key}"), key)
    body = result.body.decode()

    assert result.status == 200
    assert "?url=" not in body
    assert "skylinewebcams.com" not in body
    assert "evil.example" not in body
    assert body.count("?seg=") == 1
    assert body.count("#EXTINF") == 1

    token = body.split("?seg=")[1].strip()
    assert camera.resolve_segment_url(token) == SEGMENT_URL
    # The segments are reached through the same token as the playlist, never
    # through the entry id.
    assert f"/api/skylinewebcams_proxy/{camera.proxy_token}.ts?seg=" in body
    assert "cam1" not in body


async def test_caller_supplied_url_is_never_fetched():
    camera, session = make_camera(FakeResponse(headers={"Content-Type": "video/mp2t"}))
    view = make_view(camera)

    key = f"{camera.proxy_token}.ts"
    await view.get(
        make_request(
            f"/api/skylinewebcams_proxy/{key}", {"url": "http://127.0.0.1:8123/api/"}
        ),
        key,
    )

    assert "http://127.0.0.1:8123/api/" not in session.requested


async def test_unknown_segment_token_is_refused():
    camera, session = make_camera(FakeResponse(headers={"Content-Type": "video/mp2t"}))
    view = make_view(camera)

    key = f"{camera.proxy_token}.ts"
    result = await view.get(
        make_request(f"/api/skylinewebcams_proxy/{key}", {"seg": "f" * 32}), key
    )

    assert result.status == 404
    assert session.requested == []


async def test_segment_with_charset_content_type_is_served():
    response = FakeResponse(
        headers={"Content-Type": "video/mp2t; charset=utf-8"}, body=b"TSDATA"
    )
    camera, session = make_camera(response)
    view = make_view(camera)
    token = camera.register_segment_url(SEGMENT_URL)

    key = f"{camera.proxy_token}.ts"
    result = await view.get(
        make_request(f"/api/skylinewebcams_proxy/{key}", {"seg": token}), key
    )

    assert result.status == 200
    assert result.body == b"TSDATA"
    assert session.requested == [SEGMENT_URL]


def test_proxy_token_is_random_per_camera_and_not_the_entry_id():
    first, _ = make_camera(FakeResponse())
    second, _ = make_camera(FakeResponse())

    assert first.proxy_token != second.proxy_token
    assert first.proxy_token != first._entry_id
    # token_urlsafe(32): 256 bits, and nothing in it the suffix stripping or
    # the path would trip over.
    assert len(first.proxy_token) >= 43
    assert "." not in first.proxy_token
    assert "/" not in first.proxy_token


@pytest.mark.parametrize("suffix", [".m3u8", ".ts", ""])
async def test_the_entry_id_does_not_open_the_proxy(suffix):
    """The entry id names the diagnostics file; it must not be a key."""
    camera, session = make_camera(
        FakeResponse(headers={"Content-Type": "application/vnd.apple.mpegurl"})
    )
    view = make_view(camera)
    token = camera.register_segment_url(SEGMENT_URL)

    for query in ({}, {"seg": token}):
        result = await view.get(
            make_request(f"/api/skylinewebcams_proxy/cam1{suffix}", query),
            f"cam1{suffix}",
        )
        assert result.status == 404

    assert session.requested == []


@pytest.mark.parametrize(
    "guess",
    [
        "",
        "f" * 43,
        # A prefix of the right token, and one character off it.
        "PREFIX",
        "OFF_BY_ONE",
        # The path arrives percent-decoded, so this is what a caller can send.
        # compare_digest raises on a non-ASCII str; it must still be a 404.
        "\u00e4\u00f6\u00fc",
    ],
)
async def test_a_wrong_token_is_refused_without_a_fetch(guess):
    camera, session = make_camera(
        FakeResponse(headers={"Content-Type": "application/vnd.apple.mpegurl"})
    )
    view = make_view(camera)
    if guess == "PREFIX":
        guess = camera.proxy_token[:-1]
    elif guess == "OFF_BY_ONE":
        last = "A" if camera.proxy_token[-1] != "A" else "B"
        guess = camera.proxy_token[:-1] + last

    result = await view.get(
        make_request(f"/api/skylinewebcams_proxy/{guess}.m3u8"), f"{guess}.m3u8"
    )

    assert result.status == 404
    assert session.requested == []


async def test_one_cameras_token_does_not_reach_another():
    first, first_session = make_camera(
        FakeResponse(
            headers={"Content-Type": "application/vnd.apple.mpegurl"}, text=PLAYLIST
        )
    )
    second, second_session = make_camera(FakeResponse())
    second._entry_id = "cam2"
    view = make_view(first, second)

    key = f"{first.proxy_token}.m3u8"
    result = await view.get(make_request(f"/api/skylinewebcams_proxy/{key}"), key)

    assert result.status == 200
    assert first_session.requested == [STREAM_URL]
    assert second_session.requested == []
    # A segment token belongs to the camera that issued it.
    token = first.register_segment_url(SEGMENT_URL)
    key = f"{second.proxy_token}.ts"
    result = await view.get(
        make_request(f"/api/skylinewebcams_proxy/{key}", {"seg": token}), key
    )
    assert result.status == 404
