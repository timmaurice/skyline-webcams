"""The migration onto the normalised unique id, for entries and for YAML.

Normalising the id only changed what new entries got. An entry created before
it kept the raw URL, so `_abort_if_unique_id_configured` compared a normalised
id against a raw one, found no match, and let the very same camera be added a
second time - the duplicate the normalisation exists to prevent. The YAML
platform keyed on the raw URL for the same reason.

The async cases run on pytest-asyncio in auto mode, configured in pytest.ini.
"""

from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.skylinewebcams import async_migrate_entry
from custom_components.skylinewebcams.camera import async_setup_platform
from custom_components.skylinewebcams.const import CONF_URL, DOMAIN
from custom_components.skylinewebcams.helpers import unique_id_for_url

CAMERA_URL = (
    "https://www.skylinewebcams.com/en/webcam/deutschland/bayern/schwangau/"
    "schloss-neuschwanstein.html"
)
# The same camera as a user who browsed the site in German would paste it.
OTHER_SPELLING = CAMERA_URL.replace("/en/", "/de/")
NORMALISED = unique_id_for_url(CAMERA_URL)


def make_entry(hass, unique_id: str, url: str = CAMERA_URL, version: int = 1):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Neuschwanstein",
        data={CONF_URL: url},
        unique_id=unique_id,
        version=version,
    )
    entry.add_to_hass(hass)
    return entry


async def test_an_old_entry_moves_onto_the_normalised_id(hass):
    entry = make_entry(hass, CAMERA_URL)
    registry = er.async_get(hass)
    entity = registry.async_get_or_create(
        "camera", DOMAIN, CAMERA_URL, config_entry=entry
    )

    assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id == NORMALISED
    assert entry.version == 2
    # The entity comes along: a new id on the entry alone would have orphaned
    # the registry entry and added a second camera beside it.
    assert registry.async_get(entity.entity_id).unique_id == NORMALISED
    assert (
        registry.async_get_entity_id("camera", DOMAIN, NORMALISED) == entity.entity_id
    )


async def test_the_migrated_entry_recognises_the_camera_however_it_is_spelled(hass):
    """This is the duplicate the missing migration allowed.

    `_abort_if_unique_id_configured` looks the typed URL's normalised id up
    among the ids the existing entries carry. While an old entry still held
    the raw URL, the lookup missed and the flow created a second entry.
    """
    entry = make_entry(hass, CAMERA_URL)
    configured_before = {e.unique_id for e in hass.config_entries.async_entries(DOMAIN)}
    assert unique_id_for_url(OTHER_SPELLING) not in configured_before

    await async_migrate_entry(hass, entry)

    configured_after = {e.unique_id for e in hass.config_entries.async_entries(DOMAIN)}
    assert unique_id_for_url(OTHER_SPELLING) in configured_after
    assert unique_id_for_url(CAMERA_URL) in configured_after


async def test_an_entry_that_is_already_normalised_only_gains_the_version(hass):
    entry = make_entry(hass, NORMALISED)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id == NORMALISED
    assert entry.version == 2


async def test_a_second_run_of_the_migration_does_nothing(hass):
    entry = make_entry(hass, NORMALISED, version=2)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id == NORMALISED
    assert entry.version == 2


async def test_a_migration_that_would_collide_keeps_the_old_id(hass, caplog):
    """Two entries for one camera is a mess, but not one to fix by force.

    Unregistering a working entity to free an id would lose its history and
    its customisations. The duplicate stays and the user decides.
    """
    registry = er.async_get(hass)
    newcomer = make_entry(hass, NORMALISED)
    squatter = registry.async_get_or_create(
        "camera", DOMAIN, NORMALISED, config_entry=newcomer
    )
    old = make_entry(hass, CAMERA_URL)
    old_entity = registry.async_get_or_create(
        "camera", DOMAIN, CAMERA_URL, suggested_object_id="old", config_entry=old
    )

    assert await async_migrate_entry(hass, old) is True

    assert old.unique_id == CAMERA_URL
    # Version still moves, so the migration is not retried on every restart.
    assert old.version == 2
    assert registry.async_get(old_entity.entity_id).unique_id == CAMERA_URL
    assert registry.async_get(squatter.entity_id).unique_id == NORMALISED
    assert "already uses" in caplog.text


async def test_an_entry_without_a_url_is_left_as_it_is(hass):
    """Nothing to normalise against, so the id it has is the best one there is."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="mystery", version=1)
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.unique_id == "mystery"
    assert entry.version == 2


@pytest.fixture
def yaml_hass(hass):
    """The camera platform without its HTTP view: hass.http is not set up here."""
    hass.data[DOMAIN] = {}
    return hass


async def test_the_yaml_platform_keys_on_the_same_id_as_the_ui(yaml_hass):
    """A YAML camera used to key on the raw URL, so it never deduped at all."""
    added = []

    await async_setup_platform(
        yaml_hass,
        {CONF_URL: CAMERA_URL, "name": "Neuschwanstein"},
        lambda entities, update_before_add=False: added.extend(entities),
    )

    assert [camera.unique_id for camera in added] == [NORMALISED]


async def test_a_yaml_camera_keeps_its_entity_when_the_id_is_normalised(yaml_hass):
    registry = er.async_get(yaml_hass)
    entity = registry.async_get_or_create("camera", DOMAIN, CAMERA_URL)

    await async_setup_platform(
        yaml_hass,
        {CONF_URL: CAMERA_URL, "name": "Neuschwanstein"},
        lambda entities, update_before_add=False: None,
    )

    assert registry.async_get(entity.entity_id).unique_id == NORMALISED


async def test_a_yaml_camera_survives_the_next_restart(yaml_hass, caplog):
    """The restart after the migration must not mint a second camera.

    This is what a YAML user saw. On the first start after the normalisation
    the camera's registry entry is moved from the raw URL onto the normalised
    id - that much the test above pins. On the *next* start nothing holds the
    raw URL any more, so the collision check found the normalised id "taken",
    could not see that the holder was this very camera, and backed off onto the
    raw URL. Home Assistant then had two ids for one webcam: it kept the
    migrated entity, registered a second one beside it as `camera.<name>_2`,
    and the first went unavailable - taking every dashboard, automation and
    template that named it with it.

    Nothing owns the old id, so there is nothing to migrate and nothing to
    collide with. The camera simply is the entity that already holds the
    normalised id.
    """
    registry = er.async_get(yaml_hass)
    config = {CONF_URL: CAMERA_URL, "name": "Neuschwanstein"}

    # First start: the raw-URL entity is migrated onto the normalised id.
    migrated = registry.async_get_or_create("camera", DOMAIN, CAMERA_URL)
    await async_setup_platform(
        yaml_hass, config, lambda entities, update_before_add=False: None
    )
    assert registry.async_get(migrated.entity_id).unique_id == NORMALISED

    # Second start: same configuration, same camera, nothing else changed.
    caplog.clear()
    added: list = []
    await async_setup_platform(
        yaml_hass,
        config,
        lambda entities, update_before_add=False: added.extend(entities),
    )

    assert [camera.unique_id for camera in added] == [NORMALISED]
    assert "already uses" not in caplog.text
    # Still one camera, and still the one that was there before.
    assert (
        registry.async_get_entity_id("camera", DOMAIN, NORMALISED) == migrated.entity_id
    )
    assert registry.async_get_entity_id("camera", DOMAIN, CAMERA_URL) is None


def registering(hass, added: list):
    """An `async_add_entities` that registers, the way Home Assistant's does.

    A stub that only collects the cameras leaves the registry empty, so the
    next camera finds nothing holding the id and the collision under test never
    happens. Registering is the part of adding an entity that this file is
    about.
    """
    registry = er.async_get(hass)

    def _add(entities, update_before_add: bool = False) -> None:
        for camera in entities:
            registry.async_get_or_create(
                "camera", DOMAIN, camera.unique_id, suggested_object_id=camera.name
            )
            added.append(camera)

    return _add


async def test_a_real_collision_is_still_left_alone(yaml_hass, caplog):
    """The back-off is for a genuine clash and has to survive the fix.

    Two YAML cameras pointing at the same page under different spellings: the
    second one's id normalises onto an entity the first is already running.
    Taking it away would cost that camera its history and its customisations,
    so the duplicate stays and the user decides.

    The first camera is set up rather than faked into the registry, because the
    fix turns on exactly that difference: a row somebody is running is a rival,
    a row left behind by an earlier start is this camera's own.
    """
    added: list = []
    for url, name in ((CAMERA_URL, "English"), (OTHER_SPELLING, "German")):
        await async_setup_platform(
            yaml_hass, {CONF_URL: url, "name": name}, registering(yaml_hass, added)
        )

    assert [camera.unique_id for camera in added] == [NORMALISED, OTHER_SPELLING]
    assert "already uses" in caplog.text


async def test_a_yaml_camera_survives_a_reload_too(yaml_hass, caplog):
    """Reloading the YAML leaves the previous run's cameras in `hass.data`.

    A restart clears it; "Reload all YAML configuration" does not. Finding
    itself still in there must not read as a rival, or a reload would mint the
    duplicate a restart no longer does.
    """
    config = {CONF_URL: CAMERA_URL, "name": "Neuschwanstein"}
    await async_setup_platform(
        yaml_hass, config, lambda entities, update_before_add=False: None
    )

    caplog.clear()
    added: list = []
    await async_setup_platform(
        yaml_hass,
        config,
        lambda entities, update_before_add=False: added.extend(entities),
    )

    assert [camera.unique_id for camera in added] == [NORMALISED]
    assert "already uses" not in caplog.text
