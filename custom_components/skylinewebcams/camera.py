"""Camera platform for SkylineWebcams."""

from __future__ import annotations

import logging
import asyncio
import re
import aiohttp
from bs4 import BeautifulSoup
from aiohttp import web
from collections import OrderedDict

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.network import get_url
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import aiohttp
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)


def _init_domain_data(hass: HomeAssistant) -> None:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
        hass.http.register_view(SkylineWebcamsHlsProxyView(hass))


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict,
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict | None = None,
) -> None:
    """Set up SkylineWebcams camera from YAML configuration."""
    _init_domain_data(hass)

    import hashlib

    url = config[CONF_URL]
    name = config.get(CONF_NAME, "Skyline Webcam")

    # Use URL as unique_id for YAML as well
    unique_id = url
    # For YAML, we use a hash of the URL as the entry_id for safe proxy routing
    entry_id = hashlib.md5(url.encode()).hexdigest()

    camera = SkylineWebcamsCamera(hass, url, name, unique_id, entry_id)
    hass.data[DOMAIN][entry_id] = camera
    async_add_entities([camera], True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SkylineWebcams camera from a config entry."""
    _init_domain_data(hass)

    camera = SkylineWebcamsCamera(
        hass, entry.data[CONF_URL], entry.title, entry.unique_id, entry.entry_id
    )
    hass.data[DOMAIN][entry.entry_id] = camera
    async_add_entities([camera], True)


class SkylineWebcamsHlsProxyView(HomeAssistantView):
    """View to proxy HLS stream directly to bypass Referer checks."""

    url = "/api/skylinewebcams_proxy/{entry_id}"
    name = "api:skylinewebcams_proxy"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        """Handle GET request to proxy the stream."""
        if entry_id.endswith(".m3u8"):
            entry_id = entry_id[:-5]
        elif entry_id.endswith(".ts"):
            entry_id = entry_id[:-3]

        camera = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if not camera:
            return web.Response(status=404, text="Camera not found")

        target_url = request.query.get("url")

        if not target_url:
            target_url = await camera.get_fresh_stream_url()
            if not target_url:
                return web.Response(status=502, text="Failed to fetch stream URL")

        is_ts_request = request.path.endswith(".ts") or (
            target_url and ".ts" in target_url
        )

        if is_ts_request and target_url:
            cached_data = camera.get_cached_ts(target_url)
            if cached_data:
                content_type, body_bytes = cached_data
                _LOGGER.debug(
                    "[%s] Serving cached TS chunk for %s", camera.name, target_url
                )
                return web.Response(
                    body=body_bytes,
                    content_type=content_type,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "public, max-age=3600",
                    },
                )

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.skylinewebcams.com/",
            "Accept": "*/*",
        }

        try:
            session = camera.get_session()
            async with session.get(target_url, headers=headers) as resp:
                if resp.status != 200:
                    return web.Response(status=resp.status, text="Proxy fetch failed")

                content_type = resp.headers.get("Content-Type", "")

                if "mpegurl" in content_type.lower() or target_url.endswith(".m3u8"):
                    # Rewrite the M3U8 playlist
                    text = await resp.text()

                    # Check if token is expired (empty playlist or copyright violation)
                    if "copyright_violation" in text or ".ts" not in text:
                        # Token is invalid, force refresh
                        camera._last_update = 0
                        target_url = await camera.get_fresh_stream_url()
                        if not target_url:
                            return web.Response(
                                status=502, text="Failed to fetch fresh stream URL"
                            )

                        # Retry fetch
                        async with session.get(
                            target_url, headers=headers
                        ) as retry_resp:
                            if retry_resp.status != 200:
                                return web.Response(
                                    status=retry_resp.status,
                                    text="Proxy retry fetch failed",
                                )
                            text = await retry_resp.text()
                    rewritten_lines = []
                    from urllib.parse import urljoin, quote, urlparse

                    parsed_target = urlparse(target_url)
                    for line in text.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            chunk_url = urljoin(target_url, line)
                            parsed_chunk = urlparse(chunk_url)
                            if not parsed_chunk.query and parsed_target.query:
                                chunk_url = f"{chunk_url}?{parsed_target.query}"
                            encoded_url = quote(chunk_url, safe="")
                            rewritten_lines.append(
                                f"/api/skylinewebcams_proxy/{entry_id}.ts?url={encoded_url}"
                            )
                        else:
                            rewritten_lines.append(line)

                    return web.Response(
                        body="\n".join(rewritten_lines).encode("utf-8"),
                        content_type="application/vnd.apple.mpegurl",
                        headers={"Access-Control-Allow-Origin": "*"},
                    )
                else:
                    if is_ts_request and target_url:
                        body_bytes = await resp.read()
                        camera.put_cached_ts(target_url, content_type, body_bytes)
                        return web.Response(
                            body=body_bytes,
                            content_type=content_type,
                            headers={
                                "Access-Control-Allow-Origin": "*",
                                "Cache-Control": "public, max-age=3600",
                            },
                        )

                    # Stream the binary data incrementally
                    headers = {
                        "Content-Type": content_type,
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "public, max-age=3600",
                    }
                    if "Content-Length" in resp.headers:
                        headers["Content-Length"] = resp.headers["Content-Length"]

                    response = web.StreamResponse(
                        status=200, reason="OK", headers=headers
                    )
                    await response.prepare(request)

                    async for chunk in resp.content.iter_chunked(4096):
                        await response.write(chunk)

                    await response.write_eof()
                    return response
        except Exception as e:
            return web.Response(status=500, text=str(e))


class SkylineWebcamsCamera(Camera, RestoreEntity):
    """Define a SkylineWebcams camera."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = "hls"
    _attr_icon = "mdi:webcam"

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        name: str,
        unique_id: str | None,
        entry_id: str,
    ) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._entry_id = entry_id
        self._url = url
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._stream_url = None
        self._last_update = 0
        self._additional_attributes = {"source": self._url}
        self._attr_available = True
        self._session = None
        self._ts_cache = OrderedDict()
        self._ts_cache_capacity = 15

    def get_session(self):
        if not self._session:
            self._session = async_create_clientsession(self.hass)
        return self._session

    def get_cached_ts(self, url: str) -> tuple[str, bytes] | None:
        """Get cached TS chunk."""
        if url in self._ts_cache:
            self._ts_cache.move_to_end(url)
            return self._ts_cache[url]
        return None

    def put_cached_ts(self, url: str, content_type: str, data: bytes) -> None:
        """Cache TS chunk."""
        if url in self._ts_cache:
            self._ts_cache.move_to_end(url)
        self._ts_cache[url] = (content_type, data)
        if len(self._ts_cache) > self._ts_cache_capacity:
            self._ts_cache.popitem(last=False)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("[%s] Entity added to Home Assistant", self._attr_name)

        if (old_state := await self.async_get_last_state()) is not None:
            for attr in ["description", "country", "region", "place", "poster"]:
                if attr in old_state.attributes:
                    self._additional_attributes[attr] = old_state.attributes[attr]

        self.hass.async_create_task(self.get_fresh_stream_url())
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
        attrs = self._additional_attributes.copy()
        attrs["entry_id"] = self._entry_id
        return attrs

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
        """Return a still image response directly using the page poster."""
        if "poster" not in self._additional_attributes:
            await self.get_fresh_stream_url()

        poster_url = self._additional_attributes.get("poster")
        if not poster_url:
            return None

        try:
            session = self.get_session()
            async with asyncio.timeout(10):
                async with session.get(poster_url) as response:
                    if response.status == 200:
                        return await response.read()
        except Exception as err:
            _LOGGER.error("[%s] Failed to fetch camera image: %s", self._attr_name, err)
        return None

    async def stream_source(self) -> str | None:
        """Provide the local proxy URL to Home Assistant's stream worker."""
        # Instead of giving the expiring URL to HA, we give it our internal proxy.
        # When HA tries to load this, our View intercepts it and redirects to a fresh token!
        try:
            base_url = get_url(self.hass, prefer_external=False)
        except Exception:
            base_url = "http://127.0.0.1:8123"

        proxy_url = f"{base_url}/api/skylinewebcams_proxy/{self._entry_id}.m3u8"
        _LOGGER.debug(
            "[%s] Providing proxy stream URL to HA worker: %s",
            self._attr_name,
            proxy_url,
        )
        return proxy_url

    async def get_fresh_stream_url(self) -> str | None:
        """Get a fresh URL, caching it for 2 minutes to avoid rate limits."""
        now = asyncio.get_event_loop().time()

        if self._stream_url and (now - self._last_update < 120):
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
            session = self.get_session()
            async with asyncio.timeout(20):
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

                    if og_img := soup.find("meta", attrs={"property": "og:image"}):
                        self._additional_attributes["poster"] = og_img.get("content")

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

                    if self.entity_id:
                        self.async_write_ha_state()
                    return f"https://hd-auth.skylinewebcams.com/{stream_path}"

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error(
                "[%s] Network error while fetching stream URL: %s", self._attr_name, err
            )
            self._attr_available = False
            if self.entity_id:
                self.async_write_ha_state()
            return None
