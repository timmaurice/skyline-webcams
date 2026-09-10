"""Camera platform for SkylineWebcams."""

from __future__ import annotations

import logging
import asyncio
import hmac
import re
import secrets
from hashlib import sha256
from urllib.parse import urlparse
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

ALLOWED_STREAM_HOST = "skylinewebcams.com"

# Backoff for the scraper, so a camera whose page is down does not get scraped
# again on every single proxy request. While the backoff runs, the cached URL is
# handed back unchanged: it may still play, and re-scraping a page that just
# failed would not have produced a better one.
FETCH_BACKOFF_BASE_SECONDS = 5
FETCH_BACKOFF_MAX_SECONDS = 300
# 5s * 2**6 = 320s, already past the cap above. Counting failures beyond this
# only builds a bigger power for a value the cap flattens anyway.
MAX_BACKOFF_FAILURES = 7


def is_allowed_stream_url(url: str | None) -> bool:
    """Check that a URL points at SkylineWebcams over HTTP(S).

    The proxy fetches this URL from inside the Home Assistant network, so
    anything that is not the upstream site must be rejected before a request
    is made.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host == ALLOWED_STREAM_HOST or host.endswith("." + ALLOWED_STREAM_HOST)


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

        # Segment requests carry a token that this proxy issued when it
        # rewrote the playlist. A caller supplied URL is never fetched, so the
        # endpoint cannot be used to reach arbitrary hosts.
        segment_token = request.query.get("seg")

        if segment_token:
            target_url = camera.resolve_segment_url(segment_token)
            if not target_url:
                return web.Response(status=404, text="Unknown stream segment")
        else:
            target_url = await camera.get_fresh_stream_url()
            if not target_url:
                return web.Response(status=502, text="Failed to fetch stream URL")

        if not is_allowed_stream_url(target_url):
            _LOGGER.warning(
                "[%s] Refusing to proxy a URL outside %s",
                camera.name,
                ALLOWED_STREAM_HOST,
            )
            return web.Response(status=403, text="Stream host not allowed")

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
                    headers={
                        "Content-Type": content_type,
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
                        # Token is invalid, force refresh. This bypasses the
                        # backoff as well as the cache: the URL we hold is
                        # provably dead, so serving it again is worse than
                        # scraping once more.
                        target_url = await camera.get_fresh_stream_url(force=True)
                        if not target_url:
                            return web.Response(
                                status=502, text="Failed to fetch fresh stream URL"
                            )
                        if not is_allowed_stream_url(target_url):
                            _LOGGER.warning(
                                "[%s] Refusing to proxy a URL outside %s",
                                camera.name,
                                ALLOWED_STREAM_HOST,
                            )
                            return web.Response(
                                status=403, text="Stream host not allowed"
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
                    from urllib.parse import urljoin

                    parsed_target = urlparse(target_url)
                    for line in text.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            chunk_url = urljoin(target_url, line)
                            parsed_chunk = urlparse(chunk_url)
                            if not parsed_chunk.query and parsed_target.query:
                                chunk_url = f"{chunk_url}?{parsed_target.query}"
                            if not is_allowed_stream_url(chunk_url):
                                _LOGGER.warning(
                                    "[%s] Dropping playlist entry outside %s",
                                    camera.name,
                                    ALLOWED_STREAM_HOST,
                                )
                                # Drop the tags that belong to the segment too,
                                # so no dangling #EXTINF is left behind.
                                while rewritten_lines and (
                                    not rewritten_lines[-1]
                                    or rewritten_lines[-1].startswith("#EXTINF")
                                    or rewritten_lines[-1].startswith(
                                        "#EXT-X-BYTERANGE"
                                    )
                                ):
                                    rewritten_lines.pop()
                                continue
                            token = camera.register_segment_url(chunk_url)
                            rewritten_lines.append(
                                f"/api/skylinewebcams_proxy/{entry_id}.ts?seg={token}"
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
                            headers={
                                "Content-Type": content_type,
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
        except Exception:
            _LOGGER.exception("[%s] Error while proxying the stream", camera.name)
            return web.Response(status=502, text="Proxy error")


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
        self._fetch_failures = 0
        self._retry_not_before = 0.0
        self._additional_attributes = {"source": self._url}
        self._attr_available = True
        self._session = None
        self._ts_cache = OrderedDict()
        self._ts_cache_capacity = 15
        # Segment URLs the proxy itself handed out, keyed by an opaque token.
        # The proxy never fetches a URL that is not in here.
        self._segment_urls: OrderedDict[str, str] = OrderedDict()
        self._segment_capacity = 256
        self._segment_secret = secrets.token_bytes(32)

    def get_session(self):
        if not self._session:
            self._session = async_create_clientsession(self.hass)
        return self._session

    def register_segment_url(self, url: str) -> str:
        """Register an upstream segment URL and return the token for it.

        The token is derived from the URL with a per-camera secret, so the same
        segment keeps the same token across playlist refreshes and the table
        does not grow on every reload.
        """
        token = hmac.new(self._segment_secret, url.encode(), sha256).hexdigest()[:32]
        if token in self._segment_urls:
            self._segment_urls.move_to_end(token)
        else:
            self._segment_urls[token] = url
            if len(self._segment_urls) > self._segment_capacity:
                self._segment_urls.popitem(last=False)
        return token

    def resolve_segment_url(self, token: str) -> str | None:
        """Return the upstream URL for a token the proxy issued earlier."""
        url = self._segment_urls.get(token)
        if url is not None:
            self._segment_urls.move_to_end(token)
        return url

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
        """Return a still image response directly using the stream or fallback to page poster."""
        if "poster" not in self._additional_attributes:
            await self.get_fresh_stream_url()

        url = await self.get_fresh_stream_url()
        if url:
            try:
                image_bytes = await async_get_image(
                    self.hass,
                    url,
                    extra_cmd=self.ffmpeg_arguments,
                    width=width,
                    height=height,
                )
                if image_bytes:
                    return image_bytes
            except Exception as err:
                _LOGGER.error(
                    "[%s] Failed to capture image from stream: %s", self._attr_name, err
                )

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

    async def get_fresh_stream_url(self, force: bool = False) -> str | None:
        """Get a fresh URL, caching it for 2 minutes to avoid rate limits.

        `force` skips both the cache and the backoff. The caller uses it when it
        has proof the cached URL is dead - handing that same URL back would only
        buy another failed fetch.
        """
        now = asyncio.get_event_loop().time()

        if not force and self._stream_url and (now - self._last_update < 120):
            return self._stream_url

        if not force and now < self._retry_not_before:
            _LOGGER.debug(
                "[%s] Skipping stream URL fetch, backing off for another %.0fs",
                self._attr_name,
                self._retry_not_before - now,
            )
            # The cached URL, same as the failure path below: it may be stale,
            # but handing back None where a fetch would have returned the old
            # one only makes the backoff window worse than the failure it is
            # protecting against.
            return self._stream_url

        url = await self._fetch_stream_url()
        if url:
            self._stream_url = url
            self._last_update = asyncio.get_event_loop().time()
            self._fetch_failures = 0
            self._retry_not_before = 0.0
        else:
            # Stop counting once the delay is capped: a camera whose page
            # stays gone for weeks would otherwise raise 2 to an ever growing
            # power for a value that is clamped to five minutes anyway.
            self._fetch_failures = min(self._fetch_failures + 1, MAX_BACKOFF_FAILURES)
            delay = min(
                FETCH_BACKOFF_BASE_SECONDS * 2 ** (self._fetch_failures - 1),
                FETCH_BACKOFF_MAX_SECONDS,
            )
            self._retry_not_before = asyncio.get_event_loop().time() + delay
            _LOGGER.debug(
                "[%s] Stream URL fetch failed %d time(s), next attempt in %ds",
                self._attr_name,
                self._fetch_failures,
                delay,
            )

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
