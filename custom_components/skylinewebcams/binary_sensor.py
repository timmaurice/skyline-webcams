"""Binary sensor platform for SkylineWebcams: whether a webcam is online.

A webcam that is switched off on the site still has a page that answers, so its
camera stays available and only its `offline` attribute says so. That is easy
to miss and awkward to automate on. This sensor puts it where Home Assistant
looks for it: a connectivity sensor on the webcam's device, on while the webcam
broadcasts and off while it is offline.

Only for the webcams added through the UI. A YAML camera belongs to no config
entry and has no device, so there is nothing to attach a sensor to; it carries
the `offline` attribute all the same.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SkylineConfigEntry, SkylineRuntimeData
from .helpers import device_info_for_entry, online_unique_id

# No limit. The sensor never polls and never fetches anything itself: its state
# is the camera's, pushed to it when the camera has looked at the page.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SkylineConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Online binary sensor of a config entry's webcam."""
    async_add_entities([SkylineWebcamsOnlineSensor(entry)])


class SkylineWebcamsOnlineSensor(BinarySensorEntity):
    """On while the webcam broadcasts, off while the site says it is offline."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_translation_key = "online"
    _attr_should_poll = False

    def __init__(self, entry: SkylineConfigEntry) -> None:
        """Initialize the sensor."""
        # The runtime data, not the camera: the two platforms are set up side
        # by side, so the camera may not exist yet when this sensor does.
        self._runtime_data: SkylineRuntimeData = entry.runtime_data
        # Derived from the camera's unique id, so the two travel together; the
        # reconfigure flow moves both when the URL changes.
        self._attr_unique_id = online_unique_id(entry.unique_id)
        self._attr_device_info = device_info_for_entry(entry)

    async def async_added_to_hass(self) -> None:
        """Follow the camera from now on."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._runtime_data.async_add_listener(self.async_write_ha_state)
        )

    @property
    def available(self) -> bool:
        """Available while the camera is: an unreachable page says nothing."""
        camera = self._runtime_data.camera
        return camera is not None and camera.available

    @property
    def is_on(self) -> bool | None:
        """Whether the webcam is online, None until its page has been read."""
        camera = self._runtime_data.camera
        if camera is None or camera.offline is None:
            return None
        return not camera.offline
