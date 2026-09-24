"""Tests for the URL the camera hands to Home Assistant's stream worker.

The worker fetches the proxy playlist from inside Home Assistant. The URL comes
from core's own get_url() when the instance knows one; only when it does not
does the camera fall back to the local HTTP server. That fallback must follow
the server's active config: since 2026.8 new HAOS installs listen on port 80,
and the port can be changed, so a hard-coded 8123 points the worker at nothing.

These run against a real hass from pytest-homeassistant-custom-component, so
whether the fallback is reached is decided by core's get_url(), not by a mock.
"""

import pytest

from homeassistant.components.http import ApiConfig
from homeassistant.helpers.network import NoURLAvailableError, get_url

from custom_components.skylinewebcams.camera import SkylineWebcamsCamera

PROXY_PATH = "/api/skylinewebcams_proxy/cam1.m3u8"


def make_camera(hass):
    return SkylineWebcamsCamera(
        hass=hass,
        url="https://www.skylinewebcams.com/en/webcam/test.html",
        name="Test Cam",
        unique_id="test",
        entry_id="cam1",
    )


def serve_on(hass, port, use_ssl=False):
    """Configure hass so that get_url() finds no URL at all.

    With no internal or external URL, no cloud and a loopback local IP, core
    has nothing to offer and raises - the situation the fallback exists for.
    """
    hass.config.internal_url = None
    hass.config.external_url = None
    hass.config.api = ApiConfig("127.0.0.1", "127.0.0.1", port, use_ssl)
    with pytest.raises(NoURLAvailableError):
        get_url(hass, prefer_external=False)


@pytest.mark.parametrize(
    ("port", "use_ssl", "expected_base"),
    [
        # A new HAOS install since 2026.8: Supervisor default port 80.
        (80, False, "http://127.0.0.1"),
        # The classic default, still used outside Supervisor.
        (8123, False, "http://127.0.0.1:8123"),
        # A port changed by the user.
        (8124, False, "http://127.0.0.1:8124"),
        # A server with a certificate does not answer plain HTTP.
        (8443, True, "https://127.0.0.1:8443"),
    ],
)
async def test_fallback_follows_the_running_http_server(
    hass, port, use_ssl, expected_base
):
    serve_on(hass, port, use_ssl)

    assert await make_camera(hass).stream_source() == expected_base + PROXY_PATH


async def test_no_http_server_config_yields_no_stream_instead_of_a_guess(hass):
    hass.config.internal_url = None
    hass.config.external_url = None
    hass.config.api = None

    assert await make_camera(hass).stream_source() is None


async def test_a_known_internal_url_is_used_as_is(hass):
    hass.config.api = ApiConfig("127.0.0.1", "127.0.0.1", 80, False)
    hass.config.internal_url = "http://homeassistant.local:8125"

    assert (
        await make_camera(hass).stream_source()
        == "http://homeassistant.local:8125" + PROXY_PATH
    )
