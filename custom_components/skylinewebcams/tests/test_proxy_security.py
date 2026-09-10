"""Tests for the HLS proxy view: host allow-list and segment tokens.

The proxy is served without authentication so the browser can play the stream,
so it must never fetch a URL that a caller supplies. These tests pin that
behaviour down.

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


def make_view(camera):
    hass = types.SimpleNamespace(data={DOMAIN: {"cam1": camera}})
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

    result = await view.get(
        make_request("/api/skylinewebcams_proxy/cam1.m3u8"), "cam1.m3u8"
    )
    body = result.body.decode()

    assert result.status == 200
    assert "?url=" not in body
    assert "skylinewebcams.com" not in body
    assert "evil.example" not in body
    assert body.count("?seg=") == 1
    assert body.count("#EXTINF") == 1

    token = body.split("?seg=")[1].strip()
    assert camera.resolve_segment_url(token) == SEGMENT_URL


async def test_caller_supplied_url_is_never_fetched():
    camera, session = make_camera(FakeResponse(headers={"Content-Type": "video/mp2t"}))
    view = make_view(camera)

    await view.get(
        make_request(
            "/api/skylinewebcams_proxy/cam1.ts", {"url": "http://127.0.0.1:8123/api/"}
        ),
        "cam1.ts",
    )

    assert "http://127.0.0.1:8123/api/" not in session.requested


async def test_unknown_segment_token_is_refused():
    camera, session = make_camera(FakeResponse(headers={"Content-Type": "video/mp2t"}))
    view = make_view(camera)

    result = await view.get(
        make_request("/api/skylinewebcams_proxy/cam1.ts", {"seg": "f" * 32}), "cam1.ts"
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

    result = await view.get(
        make_request("/api/skylinewebcams_proxy/cam1.ts", {"seg": token}), "cam1.ts"
    )

    assert result.status == 200
    assert result.body == b"TSDATA"
    assert session.requested == [SEGMENT_URL]
