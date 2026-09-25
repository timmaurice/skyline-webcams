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
from homeassistant.const import CONF_URL, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.util.network import normalize_url
import voluptuous as vol

from . import SkylineConfigEntry
from .const import DOMAIN
from .helpers import async_camera_for_key, async_migrated_unique_id

_LOGGER = logging.getLogger(__name__)

# No limit. Cameras do not poll (Camera sets should_poll to False), so
# async_update only runs when the entity is added or update_entity is called.
# The scrapes behind it are already serialised per camera by _fetch_lock, and
# each camera scrapes its own page. A semaphore would only make one camera's
# actions (snapshot, record) wait for another's scrape: the YAML cameras share
# one platform, and with it one semaphore.
PARALLEL_UPDATES = 0

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


def local_server_url(hass: HomeAssistant) -> str | None:
    """Return the loopback URL of the HTTP server this instance is running.

    The stream worker runs inside Home Assistant, so loopback always reaches
    the server. Scheme and port come from the server's active config: the port
    is not a constant (Supervisor installs default to 80 since 2026.8, and it
    can be changed), and a server with a certificate does not answer plain HTTP.
    """
    api = hass.config.api
    if api is None:
        return None
    scheme = "https" if api.use_ssl else "http"
    return normalize_url(f"{scheme}://127.0.0.1:{api.port}")


PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_URL): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)


def _init_domain_data(hass: HomeAssistant) -> None:
    """Register the proxy view once, and make room for the YAML cameras.

    This is the one piece of state that is not per entry. A view cannot be
    unregistered, so it is set up by whichever path comes first and stays for
    the rest of the run. The YAML cameras belong to no config entry, so there
    is no `runtime_data` for them to live in: they stay in `hass.data`, keyed
    by the hash of their URL. The presence of that dict is what says the view
    is registered already.
    """
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

    # The same normalised id the config entries use, so a camera configured in
    # YAML and the same camera added through the UI are recognised as one. The
    # entity keeps its registry entry: the id is migrated, not replaced.
    # For YAML, we use a hash of the URL as the entry_id for safe proxy routing
    entry_id = hashlib.md5(url.encode()).hexdigest()
    unique_id = async_migrated_unique_id(hass, url, url, entry_id)

    camera = SkylineWebcamsCamera(hass, url, name, unique_id, entry_id)
    hass.data[DOMAIN][entry_id] = camera
    async_add_entities([camera], True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkylineConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SkylineWebcams camera from a config entry."""
    _init_domain_data(hass)

    # One device per entry, and an entry is one webcam, so this is a device per
    # webcam as well. It is keyed on the entry id rather than the unique id:
    # the unique id is the normalised URL, which the migration can still move,
    # and a device keyed on it would be left behind when it does. YAML cameras
    # get no device, Home Assistant only attaches one to an entry's entities.
    device_info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="SkylineWebcams",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data[CONF_URL],
    )
    camera = SkylineWebcamsCamera(
        hass,
        entry.data[CONF_URL],
        entry.title,
        entry.unique_id,
        entry.entry_id,
        device_info=device_info,
    )
    entry.runtime_data.camera = camera
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

        camera = async_camera_for_key(self.hass, entry_id)
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
                camera.log_name,
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
                    "[%s] Serving cached TS chunk for %s", camera.log_name, target_url
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
                                camera.log_name,
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
                                    camera.log_name,
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
            _LOGGER.exception("[%s] Error while proxying the stream", camera.log_name)
            return web.Response(status=502, text="Proxy error")


class SkylineWebcamsCamera(Camera, RestoreEntity):
    """Define a SkylineWebcams camera."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = "hls"
    _attr_icon = "mdi:webcam"
    # There is no fixed name to translate: a camera is called what the user
    # called it, the title of its entry or `name:` in YAML. The translation key
    # carries the names of the state attributes instead.
    #
    # Switching has_entity_name on renames nothing that exists. Every camera
    # has a unique id, so its registry entry keeps the entity id it was given.
    # A YAML camera has no device, and its friendly name is the entity name
    # alone; an entry's camera has no name of its own and shows the device's,
    # which is the entry title. Either way the same string as before.
    _attr_has_entity_name = True
    _attr_translation_key = "webcam"

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        name: str,
        unique_id: str | None,
        entry_id: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialize the camera."""
        super().__init__()
        self.hass = hass
        self._entry_id = entry_id
        self._url = url
        # What the log lines call this camera. The entity name cannot do that
        # job: a camera with a device has none of its own, the device carries
        # it.
        self.log_name = name
        if device_info is None:
            self._attr_name = name
        else:
            # The main feature of its device, so the camera takes the device's
            # name - which is the entry title, the name it had before.
            self._attr_name = None
            self._attr_device_info = device_info
        self._attr_unique_id = unique_id
        self._stream_url = None
        # -inf, not 0: the clock behind _is_cached is asyncio's monotonic one,
        # whose origin is the machine's boot. On a freshly booted host 0 sits
        # inside the 120-second window, so "never fetched" would read as "just
        # fetched" - which is exactly how a CI runner differs from a laptop that
        # has been up for days.
        self._last_update = float("-inf")
        # Bumped whenever a scrape replaces the URL, and whenever one runs at
        # all. Together they tell a caller waiting on the lock whether what it
        # would ask for has already happened.
        self._stream_version = 0
        self._fetch_attempts = 0
        self._fetch_failures = 0
        self._retry_not_before = 0.0
        # One scrape at a time per camera. Startup asks for the stream URL from
        # several directions at once, and without this each of them opened its
        # own request to the same page.
        self._fetch_lock = asyncio.Lock()
        # Whether the current run of failures has already been logged at ERROR.
        # Repeating the same message every 30 seconds for a site that is down
        # buries everything else in the log.
        self._failure_logged = False
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
        _LOGGER.debug("[%s] Entity added to Home Assistant", self.log_name)

        if (old_state := await self.async_get_last_state()) is not None:
            for attr in ["description", "country", "region", "place", "poster"]:
                if attr in old_state.attributes:
                    self._additional_attributes[attr] = old_state.attributes[attr]

        # No extra fetch task here: the entity is added with
        # update_before_add=True and the state write below runs async_update,
        # so a third request would only race the other two.
        self.async_schedule_update_ha_state(True)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        # Taken out of wherever the proxy finds it, so a camera that has been
        # removed is not streamed from any more - its entry may well still be
        # loaded, when only the entity was deleted.
        entry = self.platform.config_entry if self.platform else None
        if entry is None:
            self.hass.data.get(DOMAIN, {}).pop(self._entry_id, None)
        elif (
            runtime_data := getattr(entry, "runtime_data", None)
        ) is not None and runtime_data.camera is self:
            runtime_data.camera = None
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

    def as_diagnostics(self) -> dict:
        """Return the state behind the camera, for diagnostics.

        Unredacted: diagnostics.py decides what leaves the instance. This only
        collects what explains a camera that does not play - whether it has a
        stream URL and how old it is, and where the backoff stands.
        """
        now = asyncio.get_event_loop().time()
        return {
            "entity_id": self.entity_id,
            "unique_id": self.unique_id,
            "available": self._attr_available,
            "attributes": self.extra_state_attributes,
            "stream_url": self._stream_url,
            "stream_url_age_seconds": (
                round(now - self._last_update, 1) if self._stream_url else None
            ),
            "fetch_attempts": self._fetch_attempts,
            "fetch_failures": self._fetch_failures,
            "backoff_remaining_seconds": round(
                max(self._retry_not_before - now, 0.0), 1
            ),
            "failure_logged": self._failure_logged,
            "known_segments": len(self._segment_urls),
            "cached_segments": len(self._ts_cache),
        }

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
                    "[%s] Failed to capture image from stream: %s", self.log_name, err
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
            _LOGGER.error("[%s] Failed to fetch camera image: %s", self.log_name, err)
        return None

    async def stream_source(self) -> str | None:
        """Provide the local proxy URL to Home Assistant's stream worker."""
        # Instead of giving the expiring URL to HA, we give it our internal proxy.
        # When HA tries to load this, our View intercepts it and redirects to a fresh token!
        try:
            base_url = get_url(self.hass, prefer_external=False)
        except NoURLAvailableError:
            base_url = local_server_url(self.hass)
            if base_url is None:
                _LOGGER.warning(
                    "[%s] No URL to this Home Assistant instance and no HTTP "
                    "server config to fall back on; cannot provide a stream",
                    self.log_name,
                )
                return None

        proxy_url = f"{base_url}/api/skylinewebcams_proxy/{self._entry_id}.m3u8"
        _LOGGER.debug(
            "[%s] Providing proxy stream URL to HA worker: %s",
            self.log_name,
            proxy_url,
        )
        return proxy_url

    async def get_fresh_stream_url(self, force: bool = False) -> str | None:
        """Get a fresh URL, caching it for 2 minutes to avoid rate limits.

        `force` skips both the cache and the backoff. The caller uses it when it
        has proof the cached URL is dead - handing that same URL back would only
        buy another failed fetch.

        A forced caller is still coalesced with everyone else waiting on the
        lock: what it must not be served is the entry it has just proved dead,
        which is the one it saw on the way in. Anything that happened after
        that - a newer URL, or a fetch attempt that came back empty - answers
        its question as well as its own request would have, so the site is
        asked once no matter how many viewers a token expires under.
        """
        # Taken before queueing on the lock, so "after" means after this
        # caller asked, not after it got to the front of the queue.
        seen = (self._stream_version, self._fetch_attempts)

        if self._is_cached(force):
            return self._stream_url

        async with self._fetch_lock:
            # Whoever held the lock may have just fetched what we came for.
            if self._is_cached(force) or self._has_moved_on(seen):
                return self._stream_url
            return await self._fetch_and_cache(force)

    def _is_cached(self, force: bool) -> bool:
        """Whether the URL in hand can be served without asking the site."""
        if force:
            return False
        now = asyncio.get_event_loop().time()
        return bool(self._stream_url) and (now - self._last_update < 120)

    def _has_moved_on(self, seen: tuple[int, int]) -> bool:
        """Whether a fetch has run since the caller looked at the cache."""
        return (self._stream_version, self._fetch_attempts) != seen

    async def _fetch_and_cache(self, force: bool) -> str | None:
        """Scrape a fresh URL, or serve the cached one while backing off."""
        now = asyncio.get_event_loop().time()

        if not force and now < self._retry_not_before:
            _LOGGER.debug(
                "[%s] Skipping stream URL fetch, backing off for another %.0fs",
                self.log_name,
                self._retry_not_before - now,
            )
            # The cached URL, same as the failure path below: it may be stale,
            # but handing back None where a fetch would have returned the old
            # one only makes the backoff window worse than the failure it is
            # protecting against.
            return self._stream_url

        try:
            url = await self._fetch_stream_url()
        finally:
            # Counted even when the scrape raised: the callers behind us asked
            # for a fetch, and a fetch is what happened.
            self._fetch_attempts += 1

        if url:
            self._stream_url = url
            self._stream_version += 1
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
                self.log_name,
                self._fetch_failures,
                delay,
            )

        return self._stream_url

    async def _fetch_stream_url(self) -> str | None:
        """Fetch the actual stream URL from the webcam page."""
        _LOGGER.debug(
            "[%s] Fetching fresh stream URL from %s", self.log_name, self._url
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
                        self._log_fetch_failure(
                            "[%s] Webcam page answered %s",
                            self.log_name,
                            response.status,
                        )
                        self._attr_available = False
                        # Same as the error paths below: an entity that has
                        # gone unavailable is only unavailable once the state
                        # is written.
                        if self.entity_id:
                            self.async_write_ha_state()
                        return None

                    self._attr_available = True
                    text = await response.text()
                    soup = await self._parse_html(text)

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

                    if self._failure_logged:
                        _LOGGER.info(
                            "[%s] Stream URL is reachable again", self.log_name
                        )
                        self._failure_logged = False

                    if self.entity_id:
                        self.async_write_ha_state()
                    return f"https://hd-auth.skylinewebcams.com/{stream_path}"

        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            return self._handle_fetch_error(
                "[%s] Network error while fetching stream URL: %s", err
            )
        except Exception as err:  # noqa: BLE001 - see the docstring below
            # Anything else is still an outage as far as this camera is
            # concerned, and it has to arrive at the same place: a failure that
            # escaped left the backoff unarmed, so the next proxy request
            # scraped again immediately and Home Assistant logged at ERROR
            # every cycle - the log flooding this was meant to stop, reached
            # through a different exception class. The parser runs inside this
            # try as well, and bs4 does not raise ClientError.
            return self._handle_fetch_error(
                "[%s] Unexpected error while fetching stream URL: %s", err
            )

    def _handle_fetch_error(self, message: str, err: Exception) -> None:
        """Log a failed scrape once, mark the camera unavailable, give up.

        Returning None puts the caller on the backoff path, which is what keeps
        a camera whose page is broken from being scraped on every request.
        """
        self._log_fetch_failure(message, self.log_name, err)
        self._attr_available = False
        if self.entity_id:
            self.async_write_ha_state()
        return None

    async def _parse_html(self, text: str) -> BeautifulSoup:
        """Parse a webcam page off the event loop.

        The pages run to hundreds of kilobytes and html.parser is slow enough
        that parsing them inline stalls the loop for every camera in turn.
        """
        return await self.hass.async_add_executor_job(
            BeautifulSoup, text, "html.parser"
        )

    def _log_fetch_failure(self, message: str, *args) -> None:
        """Log the first failure of a run at ERROR, the rest at DEBUG.

        A site that stays down would otherwise write an ERROR line per camera
        every refresh interval, which is what buried the log during the QA run.
        Recovery is logged once at INFO.
        """
        if self._failure_logged:
            _LOGGER.debug(message, *args)
            return
        _LOGGER.error(message, *args)
        self._failure_logged = True
