"""The SkylineWebcams integration."""

from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_URL
from .helpers import async_migrated_unique_id
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.CAMERA]

import voluptuous as vol

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

CARD_FILENAME = "skyline-webcams-card.js"
CARD_URL_PREFIX = "/skylinewebcams_frontend/"


async def _async_reconcile_card_resource(resources, new_url: str) -> None:
    """Leave exactly one Lovelace resource pointing at the bundled card.

    The resource store is loaded lazily: until something awaits it, async_items()
    returns an empty list. Registering off that empty list appended a second
    resource on every restart, and the browser then loaded the bundle twice.
    """
    # Default to False, not True: assuming a collection we cannot recognise is
    # already loaded would let us register against an empty item list and save
    # a store that has lost every other card's resource. Missing async_load
    # raises instead, and the caller skips registration.
    if not getattr(resources, "loaded", False):
        await resources.async_load()
        resources.loaded = True

    own = [
        item
        for item in resources.async_items()
        if item.get("url", "").startswith(CARD_URL_PREFIX)
    ]

    if not own:
        _LOGGER.info("Registering lovelace resource: %s", new_url)
        await resources.async_create_item({"res_type": "module", "url": new_url})
        return

    for duplicate in own[1:]:
        _LOGGER.info("Removing duplicate lovelace resource %s", duplicate.get("url"))
        await resources.async_delete_item(duplicate.get("id"))

    if own[0].get("url") != new_url:
        _LOGGER.debug("Updating lovelace resource URL to %s", new_url)
        await resources.async_update_item(own[0].get("id"), {"url": new_url})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the SkylineWebcams component."""
    from homeassistant.loader import async_get_integration

    integration = await async_get_integration(hass, DOMAIN)
    version = integration.version or "1.0.0"

    # Register static path for the card
    from homeassistant.components.http import StaticPathConfig

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                url_path=f"{CARD_URL_PREFIX}{CARD_FILENAME}",
                path=hass.config.path(f"custom_components/{DOMAIN}/{CARD_FILENAME}"),
                cache_headers=True,
            )
        ]
    )
    new_url = f"{CARD_URL_PREFIX}{CARD_FILENAME}?v={version}"

    async def _async_register_lovelace_resource(event=None):
        _LOGGER.debug("Attempting to register lovelace resource")
        if "lovelace" not in hass.data:
            _LOGGER.warning("Lovelace not found in hass.data")
            return

        lovelace_data = hass.data["lovelace"]
        mode = getattr(lovelace_data, "resource_mode", "storage")
        resources = getattr(lovelace_data, "resources", None)

        if not resources:
            _LOGGER.warning("Lovelace data does not have resources")
            return

        if mode != "storage":
            _LOGGER.warning(
                "Lovelace is not in storage mode (mode is '%s'), cannot auto-register",
                mode,
            )
            return

        try:
            await _async_reconcile_card_resource(resources, new_url)
        except Exception as e:  # noqa: BLE001 - never let bookkeeping break setup
            _LOGGER.warning("Failed to register lovelace resource: %s", e)

    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    if hass.state == CoreState.running:
        hass.async_create_task(_async_register_lovelace_resource())
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _async_register_lovelace_resource
        )

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Move an entry keyed on the raw URL onto the normalised unique id.

    Without this the normalisation only applied to entries added after it:
    an older entry kept its raw-URL id, so _abort_if_unique_id_configured no
    longer recognised the camera and adding it again from the UI created a
    second entry for it - the duplicate the normalisation exists to prevent.
    """
    if entry.version > 1:
        return True

    unique_id = async_migrated_unique_id(
        hass, entry.unique_id, entry.data.get(CONF_URL, ""), entry.entry_id
    )
    if unique_id != entry.unique_id:
        _LOGGER.info(
            "Migrating %s from unique id %s to %s",
            entry.title,
            entry.unique_id,
            unique_id,
        )
        hass.config_entries.async_update_entry(entry, unique_id=unique_id, version=2)
    else:
        hass.config_entries.async_update_entry(entry, version=2)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SkylineWebcams from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
