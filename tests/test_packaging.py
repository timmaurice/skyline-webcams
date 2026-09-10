"""What ends up in the HACS zip, and what the manifests declare.

The release workflow zips the integration folder with a list of exclusions, so
debug notes, a 2.4 MB screenshot and the test suite were downloaded by every
HACS user. The exclusion rules are checked against a tree written out here
rather than against the repository: the debug notes and the tests no longer
live under the integration at all, so a check that only walks the real folder
has nothing left to exclude and passes whatever the rules say.
"""

import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = REPO / "custom_components" / "skylinewebcams"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

# Everything a user needs at runtime: the integration itself, its translations
# and the bundled card. The brand images belong to the HA brands repository,
# not to a user's config folder.
SHIPPABLE_SUFFIXES = {".py", ".json", ".js"}

# hass.http.async_register_static_paths, which __init__ awaits during setup,
# first shipped in core 2024.7.0; before it there is only the synchronous
# register_static_path and setup raises. Without the floor HACS happily offers
# the integration to a core it cannot start on.
MINIMUM_CORE_VERSION = (2024, 7)


def zip_excludes() -> list[str]:
    """The -x patterns the release workflow passes to zip."""
    text = RELEASE_WORKFLOW.read_text()
    match = re.search(r"zip -r \.\./\.\./skylinewebcams\.zip \.(.*?)\n\n", text, re.S)
    assert match, "could not find the zip step in the release workflow"
    return re.findall(r'"([^"]+)"', match.group(1))


def matches(pattern: str, path: str) -> bool:
    """Apply one zip -x pattern the way zip does.

    zip lets * cross directory separators, which fnmatch does not, so the
    pattern is translated by hand.
    """
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, path) is not None


def surviving(paths: list[str]) -> list[str]:
    """The paths the release workflow's exclusions would leave in the zip."""
    excludes = zip_excludes()
    return [
        path
        for path in paths
        if not any(matches(pattern, path) for pattern in excludes)
    ]


def component_files() -> list[str]:
    """Paths, relative to the integration folder, as they are on disk."""
    return sorted(
        path.relative_to(COMPONENT).as_posix()
        for path in COMPONENT.rglob("*")
        if path.is_file()
    )


# One entry per thing the exclusion list is there for, plus the files that have
# to survive it. Written out here so every rule is exercised on every run,
# whatever the integration folder happens to contain.
RUNTIME_TREE = [
    "__init__.py",
    "camera.py",
    "config_flow.py",
    "helpers.py",
    "manifest.json",
    "skyline-webcams-card.js",
    "translations/de.json",
    "translations/en.json",
]

EXCLUDED_TREE = [
    # Test suite, at the top level and nested.
    "tests/__init__.py",
    "tests/test_camera.py",
    "tests/helpers/fake_site.py",
    # Byte code, which is what a developer's checkout is full of.
    "__pycache__/camera.cpython-312.pyc",
    "translations/__pycache__/de.cpython-312.pyc",
    # Documentation, and the 2.4 MB screenshot that went with it.
    "README.md",
    "docs/DEBUG_NOTES.md",
    "docs/debug.png",
    "debug.png",
    # Brand assets belong to the HA brands repository.
    "brand/icon.png",
    "brand/logo.svg",
    # Finder droppings, at any depth.
    ".DS_Store",
    "translations/.DS_Store",
]


def test_the_exclusion_rules_drop_everything_they_are_meant_to():
    assert surviving(EXCLUDED_TREE) == []


def test_the_exclusion_rules_keep_everything_a_user_needs():
    assert surviving(RUNTIME_TREE) == RUNTIME_TREE


def test_a_mixed_tree_is_split_the_way_it_should_be():
    """Both halves at once: the order files are walked in must not matter."""
    mixed = sorted(RUNTIME_TREE + EXCLUDED_TREE)

    assert surviving(mixed) == sorted(RUNTIME_TREE)


def test_no_debug_artefacts_in_the_integration_folder():
    """A 2.4 MB screenshot and the debug notes are documentation, not code."""
    stray = [
        path.relative_to(REPO).as_posix()
        for path in COMPONENT.rglob("*")
        if path.is_file()
        and (path.suffix == ".md" or path.name == "debug.png" or "tests" in path.parts)
    ]
    assert stray == []


def test_the_real_folder_still_ships_what_the_integration_needs():
    packaged = surviving(component_files())

    assert packaged, "the exclusion list swallowed the whole integration"
    assert "manifest.json" in packaged
    assert "camera.py" in packaged
    assert "helpers.py" in packaged
    assert "skyline-webcams-card.js" in packaged


def test_only_runtime_file_types_are_packaged():
    unexpected = [
        name
        for name in surviving(component_files())
        if pathlib.Path(name).suffix not in SHIPPABLE_SUFFIXES
    ]
    assert unexpected == []


def test_hacs_declares_a_core_version_the_integration_can_actually_run_on():
    hacs = json.loads((REPO / "hacs.json").read_text())
    declared = tuple(int(part) for part in hacs["homeassistant"].split(".")[:2])

    assert declared >= MINIMUM_CORE_VERSION
