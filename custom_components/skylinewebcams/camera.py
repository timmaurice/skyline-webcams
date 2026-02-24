"""Camera platform for SkylineWebcams."""

from __future__ import annotations

import logging
import asyncio
import re
import aiohttp
import async_timeout
from bs4 import BeautifulSoup
from aiohttp import web

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.network import get_url

from .const import CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SkylineWebcams camera from a config entry."""
    # Register the internal proxy view if it hasn't been created yet
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
        hass.http.register_view(SkylineWebcamsProxyView(hass))

    camera = SkylineWebcamsCamera(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = camera
    async_add_entities([camera], True)


class SkylineWebcamsProxyView(HomeAssistantView):
    """View to provide a dynamic redirect to the latest stream URL."""

    url = "/api/skylinewebcams/{entry_id}"
    name = "api:skylinewebcams"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Handle GET request to return a 302 redirect to the fresh stream."""
        camera: SkylineWebcamsCamera | None = self.hass.data.get(DOMAIN, {}).get(
            entry_id
        )

        if not camera:
            return web.Response(status=404, text="Camera not found")

        stream_url = await camera.get_fresh_stream_url()
        if not stream_url:
            return web.Response(
                status=502, text="Failed to fetch stream URL from provider"
            )

        # Redirect the HA Stream Worker to the actual, freshly-tokenized stream URL
        raise web.HTTPFound(stream_url)


class SkylineWebcamsCamera(Camera, RestoreEntity):
    """Define a SkylineWebcams camera."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = "hls"
    _attr_icon = "mdi:webcam"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._entry_id = entry.entry_id
        self._url = entry.data[CONF_URL]
        self._attr_name = entry.title
        self._attr_unique_id = entry.unique_id
        self._stream_url = None
        self._last_update = 0
        self._additional_attributes = {"source": self._url}
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("[%s] Entity added to Home Assistant", self._attr_name)

        if (old_state := await self.async_get_last_state()) is not None:
            for attr in ["description", "country", "region", "place"]:
                if attr in old_state.attributes:
                    self._additional_attributes[attr] = old_state.attributes[attr]

        self.async_schedule_update_ha_state(True)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self.hass.data.get(DOMAIN, {}).pop(self._entry_id, None)
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._attr_available

    async def async_update(self) -> None:
        """Update camera state in background."""
        await self.get_fresh_stream_url()

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
        """Return a still image response directly using a fresh URL."""
        stream_url = await self.get_fresh_stream_url()
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
        """Provide the local proxy URL to Home Assistant's stream worker."""
        # Instead of giving the expiring URL to HA, we give it our internal proxy.
        # When HA tries to load this, our View intercepts it and redirects to a fresh token!
        try:
            base_url = get_url(self.hass, prefer_external=False)
        except Exception:
            base_url = "http://127.0.0.1:8123"

        proxy_url = f"{base_url}/api/skylinewebcams/{self._entry_id}"
        _LOGGER.debug(
            "[%s] Providing proxy stream URL to HA worker: %s",
            self._attr_name,
            proxy_url,
        )
        return proxy_url

    async def get_fresh_stream_url(self) -> str | None:
        """Get a fresh URL, caching it briefly to avoid spamming the provider."""
        now = asyncio.get_event_loop().time()

        # Cache the token for 60 seconds to prevent scraping Skyline multiple times a minute
        if self._stream_url and (now - self._last_update < 60):
            return self._stream_url

        url = await self._fetch_stream_url()
        if url:
            self._stream_url = url
            self._last_update = asyncio.get_event_loop().time()

        return self._stream_url

    async def _fetch_stream_url(self) -> str | None:
        """Fetch the actual stream URL from the webcam page."""
        _LOGGER.debug(
            "[%s] Fetching fresh stream URL from %s", self._attr_name, self._url
        )

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.skylinewebcams.com/",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with async_timeout.timeout(20):
                    async with session.get(self._url, headers=headers) as response:
                        if response.status != 200:
                            self._attr_available = False
                            return None

                        self._attr_available = True
                        text = await response.text()
                        soup = BeautifulSoup(text, "html.parser")

                        # Extract metadata
                        if h2 := soup.find("h2"):
                            self._additional_attributes["description"] = h2.get_text(
                                strip=True
                            )

                        if breadcrumb := soup.find("ol", class_="breadcrumb"):
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
                            if match := re.search(pattern, text, re.IGNORECASE):
                                stream_path = match.group(1)
                                break

                        if not stream_path:
                            return None

                        if "livee.m3u8" in stream_path:
                            stream_path = stream_path.replace("livee.m3u8", "live.m3u8")

                        return f"https://hd-auth.skylinewebcams.com/{stream_path}"

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error(
                "[%s] Network error while fetching stream URL: %s", self._attr_name, err
            )
            self._attr_available = False
            return None
