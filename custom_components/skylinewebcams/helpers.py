"""Shared helpers: the unique id every path keys a camera on."""

from __future__ import annotations

import hmac
import logging
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import CONF_URL, DOMAIN

if TYPE_CHECKING:
    from .camera import SkylineWebcamsCamera

_LOGGER = logging.getLogger(__name__)

# The site serves the same camera under a language prefix, /en/..., /de/... .
LANGUAGE_SEGMENT = re.compile(r"^[a-z]{2}$")


def device_info_for_entry(entry: ConfigEntry) -> DeviceInfo:
    """The device an entry's entities belong to: the webcam.

    One device per entry, and an entry is one webcam, so this is a device per
    webcam as well. It is keyed on the entry id rather than the unique id: the
    unique id is the normalised URL, which the migration can still move, and a
    device keyed on it would be left behind when it does. YAML cameras get no
    device, Home Assistant only attaches one to an entry's entities.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="SkylineWebcams",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data[CONF_URL],
    )


def online_unique_id(camera_unique_id: str) -> str:
    """The unique id of the Online binary sensor that goes with a camera."""
    return f"{camera_unique_id}_online"


def unique_id_for_url(url: str) -> str:
    """Return one id for every spelling of the same camera page.

    The raw URL was used before, so the /en/ and /de/ variants of a page, or
    the same page with a trailing "?", each added another entry for the very
    same webcam.

    The path is lowercased although the upstream site is case-sensitive about
    it. Only one spelling of a page answers 200, and the config flow fetches
    the page before it creates anything, so the other spelling never becomes an
    entry - while a user retyping a URL in the wrong case is a real thing that
    would otherwise get its own camera.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and LANGUAGE_SEGMENT.match(segments[0].lower()):
        segments = segments[1:]
    path = "/".join(segment.lower() for segment in segments)
    return f"{host}/{path}"


@callback
def async_migrated_unique_id(
    hass: HomeAssistant, old_unique_id: str | None, url: str, own_key: str | None = None
) -> str | None:
    """Return the normalised id for a camera, taking its entity along.

    The entity registry keys an entity on the id it was first registered with,
    so handing the camera a new one without moving the registry entry would
    orphan the old entity and add a second one beside it.
    """
    if not url:
        return old_unique_id

    new_unique_id = unique_id_for_url(url)
    if not old_unique_id or old_unique_id == new_unique_id:
        return new_unique_id

    registry = er.async_get(hass)
    old_entity_id = registry.async_get_entity_id(CAMERA_DOMAIN, DOMAIN, old_unique_id)
    taken_by = registry.async_get_entity_id(CAMERA_DOMAIN, DOMAIN, new_unique_id)

    if (
        taken_by
        and taken_by != old_entity_id
        and _is_live(hass, taken_by, new_unique_id, own_key)
    ):
        # Two configurations for one camera - the same page under its /en/ and
        # its /de/ spelling, say. Both normalise onto one id, and which of them
        # survives is the user's call: unregistering a working entity to tidy
        # up an id would be worse than the duplicate.
        _LOGGER.warning(
            "Keeping the unique id of %s as %s: %s already uses %s",
            old_entity_id or old_unique_id,
            old_unique_id,
            taken_by,
            new_unique_id,
        )
        return old_unique_id

    if taken_by:
        # The id is held by a registry entry nothing is providing - this very
        # camera, left behind by an earlier run. Taking it back is what the
        # normalisation was for, and it restores the entity id the camera had
        # before, along with its history and everything set on it. The row
        # under the old id becomes the leftover instead, and can be deleted.
        _LOGGER.debug("Taking %s back over from a previous run", new_unique_id)
        return new_unique_id

    if old_entity_id:
        _LOGGER.debug(
            "Migrating the unique id of %s to %s", old_entity_id, new_unique_id
        )
        registry.async_update_entity(old_entity_id, new_unique_id=new_unique_id)

    return new_unique_id


def _is_live(
    hass: HomeAssistant, entity_id: str, unique_id: str, own_key: str | None
) -> bool:
    """Whether something is really using `entity_id` and its id right now.

    The registry alone cannot tell the two cases apart. A row holding the
    normalised id is either a camera somebody else configured, or this same
    camera's row from an earlier start - the migration writes exactly such a
    row, and reading it as a rival is what used to hand the camera its raw URL
    back on the next restart and register a duplicate `camera.<name>_2` beside
    it, leaving the original unavailable.

    What separates them is whether anything still provides that row. A row that
    belongs to a config entry is alive as long as the entry is; a YAML row
    belongs to no entry, so what answers for it is whether some *other* camera
    this integration has set up carries the id. `own_key` is what makes that
    "other" hold: a YAML camera is stored under a key derived from its URL, so
    finding itself there again - which is what a reload does, where the data
    from the previous run is still around - is not a rival.
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is not None and entry.config_entry_id:
        return hass.config_entries.async_get_entry(entry.config_entry_id) is not None
    return any(
        key != own_key and getattr(camera, "unique_id", None) == unique_id
        for key, camera in async_running_cameras(hass)
    )


@callback
def async_running_cameras(
    hass: HomeAssistant,
) -> Iterator[tuple[str, SkylineWebcamsCamera]]:
    """Every camera set up right now, with the key it is kept under.

    The two paths keep their cameras in different places. A config entry
    carries its own in `runtime_data`, keyed by the entry id. A YAML camera has
    no entry to hang it on, so the platform keeps those in `hass.data`, keyed by
    a hash of the URL. Going through every entry rather than only the loaded
    ones is deliberate: a camera exists from the moment its platform creates it,
    while its entry is still setting up.
    """
    yield from hass.data.get(DOMAIN, {}).items()
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime_data = getattr(entry, "runtime_data", None)
        if runtime_data is not None and runtime_data.camera is not None:
            yield entry.entry_id, runtime_data.camera


@callback
def async_camera_for_proxy_token(
    hass: HomeAssistant, token: str
) -> SkylineWebcamsCamera | None:
    """Return the camera a proxy token belongs to, whichever path set it up.

    The proxy runs without authentication, so the token in its path is the
    whole of the access check. It is not the entry id: that is no secret - it
    names the diagnostics file, sits in the URLs of the integrations page and
    never changes - and a YAML camera's key is a hash of its public URL.
    Compared in constant time, and across every camera rather than by dict
    lookup, so the time an answer takes says nothing about how close a guess
    came. There are a handful of cameras at most. Bytes, not str: the path
    arrives percent-decoded, and compare_digest raises on a non-ASCII str.
    """
    wanted = token.encode()
    found = None
    for _key, camera in async_running_cameras(hass):
        if hmac.compare_digest(camera.proxy_token.encode(), wanted):
            found = camera
    return found
