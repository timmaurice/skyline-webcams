"""Camera platform for SkylineWebcams."""

from __future__ import annotations

import logging
import asyncio
import re
import aiohttp
import async_timeout
from datetime import timedelta
from bs4 import BeautifulSoup

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

from .const import CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Throttle the page scraping to avoid blocking or getting banned
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=5)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SkylineWebcams camera from a config entry."""
    async_add_entities([SkylineWebcamsCamera(hass, entry)], True)


class SkylineWebcamsCamera(Camera):
    """Define a SkylineWebcams camera."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._url = entry.data[CONF_URL]
        self._attr_name = entry.title
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}"
        self._stream_url = None
        self._additional_attributes = {"source": self._url}
        self._session = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        self._session = aiohttp.ClientSession()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._session:
            await self._session.close()

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._additional_attributes

    @property
    def is_streaming(self) -> bool:
        """Return true if the camera is streaming."""
        return True

    @property
    def ffmpeg_arguments(self) -> str:
        """Return the arguments to be used for FFmpeg."""
        return '-user_agent "Mozilla/5.0" ' '-referer "https://www.skylinewebcams.com/"'

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image."""
        # Return None to indicate no snapshot is available
        return None

    async def stream_source(self) -> str | None:
        """Return the source of the stream."""
        _LOGGER.debug("Getting stream source for %s", self._attr_name)
        return await self._async_get_stream_url()

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    async def _async_get_stream_url(self) -> str | None:
        """Get the stream URL by scraping the page."""
        # NOTE: Using a separate method without Throttle for now to ensure freshness on connect
        return await self._fetch_stream_url()

    async def _fetch_stream_url(self) -> str | None:
        """Fetch the actual stream URL."""
        _LOGGER.debug("Fetching page content from %s", self._url)
        # Use isolated session to avoid cookie/session sharing
        if not self._session:
            self._session = aiohttp.ClientSession()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            async with async_timeout.timeout(10):
                async with self._session.get(self._url, headers=headers) as response:
                    text = await response.text()
                    _LOGGER.debug(
                        "Page fetch status: %s, Content length: %s",
                        response.status,
                        len(text),
                    )

                    if response.status != 200:
                        _LOGGER.error("Failed to fetch page: %s", response.status)
                        return None

                    soup = BeautifulSoup(text, "html.parser")

                    # Extract Description (h2)
                    h2 = soup.find("h2")
                    if h2:
                        self._additional_attributes["description"] = h2.get_text(
                            strip=True
                        )

                    # Extract Location info from breadcrumb
                    # Breadcrumb structure: [Empty/Home, Country, Region, Place]
                    # Example: [, Greece, Ionian Islands, Corfu]
                    # Example: [, Argentina, Tierra del Fuego, Ushuaia]
                    breadcrumb = soup.find("ol", class_="breadcrumb")
                    if breadcrumb:
                        items = breadcrumb.find_all("li")

                        try:
                            # Extract text from breadcrumb items
                            if len(items) > 1:
                                self._additional_attributes["country"] = items[
                                    1
                                ].get_text(strip=True)
                            if len(items) > 2:
                                self._additional_attributes["region"] = items[
                                    2
                                ].get_text(strip=True)
                            if len(items) > 3:
                                self._additional_attributes["place"] = items[
                                    3
                                ].get_text(strip=True)
                        except IndexError:
                            pass

                    # Try multiple regex patterns to find the stream source
                    # Pattern 1: source:'live.m3u8?a=...' or source: 'live.m3u8?a=...'
                    patterns = [
                        r"source\s*:\s*['\"]([^'\"]*\.m3u8\?a=[^'\"]+)['\"]",  # Most common
                        r"['\"]([^'\"]*live[^'\"]*\.m3u8\?a=[^'\"]+)['\"]",  # Any live*.m3u8 with quotes
                        r"(live[^'\"]*\.m3u8\?a=[^\s&\"']+)",  # Without quotes
                    ]

                    stream_path = None
                    for pattern in patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            stream_path = match.group(1)
                            _LOGGER.debug("Found stream path with pattern: %s", pattern)
                            break

                    if stream_path:
                        # The source code may contain 'livee.m3u8' but the actual stream is often 'live.m3u8'
                        # We force the correction here based on user feedback.
                        stream_path = stream_path.replace("livee", "live")

                        # Construct full URL
                        # Based on research, stream is at https://hd-auth.skylinewebcams.com/
                        full_stream_url = (
                            f"https://hd-auth.skylinewebcams.com/{stream_path}"
                        )
                        self._stream_url = full_stream_url
                        _LOGGER.debug("Found stream URL: %s", full_stream_url)
                        return full_stream_url

                    _LOGGER.error(
                        "Could not find stream source in page content. Status: %s. Length: %d",
                        response.status,
                        len(text),
                    )
                    # Log more context to help diagnose the issue
                    _LOGGER.debug("Content snippet: %s", text[:1000])
                    # Try to find any .m3u8 references for debugging
                    m3u8_refs = re.findall(r"['\"]?([^'\"]*\.m3u8[^'\"]*)['\"]?", text)
                    if m3u8_refs:
                        _LOGGER.debug(
                            "Found .m3u8 references in page: %s", m3u8_refs[:5]
                        )
                    return None

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error fetching stream URL: %s", err)
            return None
