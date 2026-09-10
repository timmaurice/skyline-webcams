"""Shared helpers: the unique id every path keys a camera on."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The site serves the same camera under a language prefix, /en/..., /de/... .
LANGUAGE_SEGMENT = re.compile(r"^[a-z]{2}$")


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
    hass: HomeAssistant, old_unique_id: str | None, url: str
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

    if taken_by and taken_by != old_entity_id:
        # Two entries for one camera is the mess the normalised id prevents,
        # but which of them survives is the user's call: unregistering a
        # working entity to tidy up an id would be worse than the duplicate.
        _LOGGER.warning(
            "Keeping the unique id of %s as %s: %s already uses %s",
            old_entity_id or old_unique_id,
            old_unique_id,
            taken_by,
            new_unique_id,
        )
        return old_unique_id

    if old_entity_id:
        _LOGGER.debug(
            "Migrating the unique id of %s to %s", old_entity_id, new_unique_id
        )
        registry.async_update_entity(old_entity_id, new_unique_id=new_unique_id)

    return new_unique_id
