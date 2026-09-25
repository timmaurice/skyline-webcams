"""Fixtures for tests that set a config entry up the way Home Assistant does.

Most of the suite drives single functions. The entity naming, the device, the
entry's runtime data and the diagnostics are only what they are once Home
Assistant has run the setup, the platform and the entity registry over an
entry, so these tests go through the real thing - with two stand-ins:

- `http` and `stream` are marked as loaded instead of being set up. `stream`
  needs PyAV, which the test requirements do not pull in, and nothing here
  plays video. `hass.http` is a mock, so the card's static path and the proxy
  view register against nothing.
- The scrape is patched out. The suite runs offline, and what these tests look
  at does not depend on the page.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.skylinewebcams.const import CONF_URL, DOMAIN

CAMERA_URL = (
    "https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/"
    "schloss-neuschwanstein.html"
)
STREAM_URL = "https://hd-auth.skylinewebcams.com/live.m3u8?a=secret-token"


def make_entry(
    hass: HomeAssistant,
    *,
    title: str = "Neuschwanstein",
    url: str = CAMERA_URL,
    unique_id: str = "skylinewebcams.com/webcam/neuschwanstein",
) -> MockConfigEntry:
    """A config entry as the current config flow writes it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={CONF_URL: url},
        unique_id=unique_id,
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def setup_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> Callable[[MockConfigEntry], Awaitable[None]]:
    """Return a coroutine that sets an entry up through Home Assistant."""
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config.components.update({"http", "stream", "ffmpeg"})

    async def _setup(entry: MockConfigEntry) -> None:
        with patch(
            "custom_components.skylinewebcams.camera.SkylineWebcamsCamera"
            "._fetch_stream_url",
            AsyncMock(return_value=STREAM_URL),
        ):
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()

    return _setup
