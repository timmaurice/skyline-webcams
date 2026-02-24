"""Camera platform for SkylineWebcams."""

from __future__ import annotations

import logging
import asyncio
import re
import aiohttp
import async_timeout
from bs4 import BeautifulSoup

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SkylineWebcams camera from a config entry."""
    async_add_entities([SkylineWebcamsCamera(hass, entry)], True)


class SkylineWebcamsCamera(Camera, RestoreEntity):
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
        self._additional_attributes = {"source": self._url}
        self._attr_available = True
        self._refresh_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("[%s] Entity added to Home Assistant", self._attr_name)

        # Restore previously cached attributes
        if (old_state := await self.async_get_last_state()) is not None:
            for attr in ["description", "country", "region", "place"]:
                if attr in old_state.attributes:
                    self._additional_attributes[attr] = old_state.attributes[attr]

        # Trigger an immediate update to get the stream URL
        await self._async_get_stream_url()

        # Start a background task to aggressively refresh the M3U8 token before it expires
        self._refresh_task = self.hass.loop.create_task(self._token_refresh_loop())

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._refresh_task:
            self._refresh_task.cancel()
        await super().async_will_remove_from_hass()

    async def _token_refresh_loop(self) -> None:
        """Periodically refresh the stream token to keep the stream alive."""
        while True:
            # Skyline tokens expire after ~2.5 minutes (150 seconds).
            # We refresh every 110 seconds to preemptively update the stream worker.
            await asyncio.sleep(110)

            try:
                # Only aggressively fetch new tokens if the stream is currently active in HA
                if self.stream:
                    _LOGGER.debug(
                        "[%s] Stream is active, fetching new token proactively",
                        self._attr_name,
                    )
                    new_url = await self._fetch_stream_url()

                    if new_url and new_url != self._stream_url:
                        self._stream_url = new_url
                        _LOGGER.debug(
                            "[%s] Pushing new URL token to stream worker",
                            self._attr_name,
                        )

                        # Tell the HA stream worker to seamlessly transition to the new URL
                        if hasattr(self.stream, "update_source"):
                            self.stream.update_source(self._stream_url)

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error(
                    "[%s] Error in token refresh loop: %s", self._attr_name, err
                )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._attr_available

    async def async_update(self) -> None:
        """Update the camera stream URL in the background."""
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
        """Return the arguments to be used for FFmpeg (for static images)."""
        return '-user_agent "Mozilla/5.0" -referer "https://www.skylinewebcams.com/"'

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
        """Return the source of the stream directly to the stream worker."""
        _LOGGER.debug("[%s] Stream source requested", self._attr_name)
        new_url = await self._fetch_stream_url()
        if new_url:
            self._stream_url = new_url
        return self._stream_url

    async def _async_get_stream_url(self) -> None:
        """Update the stream URL."""
        if not self._stream_url:
            await self._fetch_stream_url()

    async def _fetch_stream_url(self) -> str | None:
        """Fetch the actual stream URL from the webcam page using a temporary session."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.skylinewebcams.com/",
        }

        try:
            # Use a temporary session to avoid stale cookies invalidating new tokens
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(20):
                    async with session.get(self._url, headers=headers) as response:
                        if response.status != 200:
                            _LOGGER.error(
                                "[%s] Failed to fetch page: %s (Status: %s)",
                                self._attr_name,
                                self._url,
                                response.status,
                            )
                            if not self._stream_url:
                                self._attr_available = False
                            return None

                        self._attr_available = True
                        text = await response.text()
                        soup = BeautifulSoup(text, "html.parser")

                        # Extract metadata
                        h2 = soup.find("h2")
                        if h2:
                            self._additional_attributes["description"] = h2.get_text(
                                strip=True
                            )

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
                            _LOGGER.warning(
                                "[%s] No stream path found in page content",
                                self._attr_name,
                            )
                            return None

                        if "livee.m3u8" in stream_path:
                            stream_path = stream_path.replace("livee.m3u8", "live.m3u8")

                        full_stream_url = (
                            f"https://hd-auth.skylinewebcams.com/{stream_path}"
                        )
                        return full_stream_url

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error(
                "[%s] Network error while fetching stream URL: %s", self._attr_name, err
            )
            if not self._stream_url:
                self._attr_available = False
            return None
