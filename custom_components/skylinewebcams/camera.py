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
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

from .const import CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Throttle the page scraping to avoid blocking or getting banned
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)


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
    _attr_frontend_stream_type = "hls"
    _attr_icon = "mdi:webcam"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._url = entry.data[CONF_URL]
        self._attr_name = entry.title
        self._attr_unique_id = entry.unique_id
        self._stream_url = None
        self._last_update = 0
        self._additional_attributes = {"source": self._url}
        self._session: aiohttp.ClientSession | None = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        # Create an isolated session for this specific camera instance
        # to prevent cookie/session bleeding between different webcams.
        self._session = aiohttp.ClientSession()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._session:
            await self._session.close()
            self._session = None

    async def async_update(self) -> None:
        """Update the camera stream URL."""
        await self._async_get_stream_url()

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
        """Return a still image response from the camera."""
        stream_url = await self.stream_source()
        if not stream_url:
            return None

        return await async_get_image(
            self.hass,
            stream_url,
            extra_cmd=self.ffmpeg_arguments,
            width=width,
            height=height,
        )

    async def stream_source(self) -> str | None:
        """Return the source of the stream."""
        _LOGGER.debug("[%s] Requesting stream source", self._attr_name)
        await self._async_get_stream_url()
        return self._stream_url

    async def _async_get_stream_url(self) -> None:
        """Update the stream URL with per-instance throttling."""
        now = asyncio.get_event_loop().time()
        if (
            now - self._last_update < MIN_TIME_BETWEEN_UPDATES.total_seconds()
            and self._stream_url
        ):
            _LOGGER.debug("[%s] Using cached stream URL (throttled)", self._attr_name)
            return

        await self._fetch_stream_url()
        self._last_update = now

    async def _fetch_stream_url(self) -> str | None:
        """Fetch the actual stream URL from the webcam page."""
        _LOGGER.debug("[%s] Fetching page content from %s", self._attr_name, self._url)

        if not self._session:
            self._session = aiohttp.ClientSession()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.skylinewebcams.com/",
        }

        try:
            async with async_timeout.timeout(15):
                async with self._session.get(self._url, headers=headers) as response:
                    if response.status != 200:
                        _LOGGER.error(
                            "[%s] Failed to fetch page: %s",
                            self._attr_name,
                            response.status,
                        )
                        return None

                    text = await response.text()
                    soup = BeautifulSoup(text, "html.parser")

                    # Extract Description
                    h2 = soup.find("h2")
                    if h2:
                        self._additional_attributes["description"] = h2.get_text(
                            strip=True
                        )

                    # Extract Location
                    breadcrumb = soup.find("ol", class_="breadcrumb")
                    if breadcrumb:
                        items = breadcrumb.find_all("li")
                        try:
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
                        except (IndexError, AttributeError):
                            pass

                    # Find stream source
                    patterns = [
                        r"source\s*:\s*['\"]([^'\"]*\.m3u8\?a=[^'\"]+)['\"]",
                        r"['\"]([^'\"]*live[^'\"]*\.m3u8\?a=[^'\"]+)['\"]",
                        r"(live[^'\"]*\.m3u8\?a=[^\s&\"']+)",
                    ]

                    stream_path = None
                    for pattern in patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            stream_path = match.group(1)
                            break

                    if not stream_path:
                        _LOGGER.error(
                            "[%s] Could not find stream source in page", self._attr_name
                        )
                        return None

                    # Correct 'livee' to 'live' if necessary
                    if "livee.m3u8" in stream_path:
                        stream_path = stream_path.replace("livee.m3u8", "live.m3u8")

                    full_stream_url = (
                        f"https://hd-auth.skylinewebcams.com/{stream_path}"
                    )

                    self._stream_url = full_stream_url
                    _LOGGER.debug(
                        "[%s] Updated stream URL: %s", self._attr_name, self._stream_url
                    )
                    return self._stream_url

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("[%s] Error fetching stream URL: %s", self._attr_name, err)
            return None
