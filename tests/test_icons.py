"""The camera's icon comes from icons.json, not from the state.

With a fixed `_attr_icon` the icon travelled in every state as an `icon`
attribute, and an icon translation could never take over: the frontend prefers
that attribute to anything it looks up. Now the state carries none, and the
frontend resolves the icon from the entity registry - the entity's platform
names the integration whose icons.json to load, its translation key the entry
in it. So a translation key without an icon falls back to the camera domain's
generic icon, quietly, and an icon without a translation key is never used.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import ast
import json
import pathlib

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.icon import async_get_icons

from custom_components.skylinewebcams.const import CONF_URL, DOMAIN
from custom_components.skylinewebcams.helpers import unique_id_for_url

from .conftest import CAMERA_URL, make_entry

COMPONENT = (
    pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "skylinewebcams"
)
ICONS = json.loads((COMPONENT / "icons.json").read_text())
STRINGS = json.loads((COMPONENT / "strings.json").read_text())

# Modules that are entity platforms, named after the domain they provide.
PLATFORMS = {"camera"}


def translation_keys_in_code() -> set[tuple[str, str]]:
    """Every (platform, translation_key) an entity class of a platform sets."""
    found: set[tuple[str, str]] = set()
    for platform in PLATFORMS:
        tree = ast.parse((COMPONENT / f"{platform}.py").read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "_attr_translation_key"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
            ):
                found.add((platform, node.value.value))
    return found


def icon_keys() -> set[tuple[str, str]]:
    return {
        (platform, key) for platform, keys in ICONS["entity"].items() for key in keys
    }


def test_there_are_translation_keys_to_check():
    assert translation_keys_in_code() == {("camera", "webcam")}


def test_every_translation_key_has_an_icon_and_no_icon_is_orphaned():
    assert icon_keys() == translation_keys_in_code()


def test_every_icon_key_is_a_translation_key_of_strings_json():
    """Both files are keyed the same way, so they have to agree on the keys."""
    translated = {
        (platform, key) for platform, keys in STRINGS["entity"].items() for key in keys
    }
    assert icon_keys() <= translated


def test_every_entity_icon_has_a_default():
    for platform, keys in ICONS["entity"].items():
        for key, icon in keys.items():
            assert icon["default"].startswith("mdi:"), (platform, key)


def test_no_entity_class_sets_a_fixed_icon():
    """A fixed icon would put the attribute back and override icons.json."""
    for platform in PLATFORMS:
        source = (COMPONENT / f"{platform}.py").read_text()
        assert "_attr_icon" not in source, platform


async def resolved_icon(hass, entity_id: str) -> str:
    """The icon the frontend would show, looked up the way it looks it up."""
    entity = er.async_get(hass).async_get(entity_id)
    icons = await async_get_icons(hass, "entity", [entity.platform])
    domain = entity.entity_id.split(".")[0]
    return icons[entity.platform][domain][entity.translation_key]["default"]


async def test_an_entry_camera_has_no_icon_attribute(hass, setup_entry):
    entry = make_entry(hass)
    await setup_entry(entry)

    state = hass.states.get("camera.neuschwanstein")
    assert "icon" not in state.attributes
    assert await resolved_icon(hass, "camera.neuschwanstein") == "mdi:webcam"


async def test_a_yaml_camera_gets_the_icon_as_well(hass, setup_yaml):
    """A YAML camera has no entry and no device, but it is in the registry.

    The frontend looks icons up by the registry entry's platform, which is the
    integration domain for a YAML platform too. Being in the registry is what
    it takes, and every camera has a unique id: the URL it is configured with.
    """
    await setup_yaml({"platform": DOMAIN, CONF_URL: CAMERA_URL, "name": "Castle"})

    state = hass.states.get("camera.castle")
    assert "icon" not in state.attributes
    entity = er.async_get(hass).async_get("camera.castle")
    assert entity.unique_id == unique_id_for_url(CAMERA_URL)
    assert entity.config_entry_id is None
    assert entity.platform == DOMAIN
    assert await resolved_icon(hass, "camera.castle") == "mdi:webcam"
