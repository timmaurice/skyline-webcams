"""Diagnostics support for SkylineWebcams."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.core import HomeAssistant

from . import SkylineConfigEntry

# The HLS proxy is served without authentication and routed by the entry id, so
# the id is all it takes to pull a stream through this instance. A diagnostics
# file ends up attached to a public issue. Home Assistant still names the file
# after the entry, which this cannot change - but the content does not have to
# repeat it.
TO_REDACT = {"entry_id"}


def redact_url_query(url: str | None) -> str | None:
    """Keep where a URL points, drop what its query carries.

    The stream URL the scraper finds is signed: `live.m3u8?a=<token>`. The host
    and path are what tells one kind of failure from another, the token is a
    credential for the stream until it expires.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    return parts._replace(query=REDACTED).geturl()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SkylineConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime_data = getattr(entry, "runtime_data", None)
    camera = runtime_data.camera if runtime_data is not None else None

    camera_data = None
    if camera is not None:
        camera_data = camera.as_diagnostics()
        camera_data["stream_url"] = redact_url_query(camera_data["stream_url"])

    return async_redact_data(
        {
            "entry": {
                "title": entry.title,
                "version": entry.version,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
            },
            # None while the entry is not loaded: the camera goes with it.
            "camera": camera_data,
        },
        TO_REDACT,
    )
