"""The SkylineWebcams integration."""

from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.CAMERA]


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
                url_path="/skylinewebcams_frontend/skyline-webcams-card.js",
                path=hass.config.path(
                    "custom_components/skylinewebcams/skyline-webcams-card.js"
                ),
                cache_headers=True,
            )
        ]
    )
    new_url = f"/skylinewebcams_frontend/skyline-webcams-card.js?v={version}"

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

        # Check if resource is already registered
        for item in resources.async_items():
            if item.get("url", "").startswith("/skylinewebcams_frontend/"):
                if item.get("url") != new_url:
                    _LOGGER.debug("Updating lovelace resource URL to %s", new_url)
                    await resources.async_update_item(item.get("id"), {"url": new_url})
                return

        # Not registered, add it
        try:
            _LOGGER.info("Registering lovelace resource: %s", new_url)
            await resources.async_create_item({"res_type": "module", "url": new_url})
        except Exception as e:
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SkylineWebcams from a config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

