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

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = REPO / "custom_components" / "skylinewebcams"
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
TESTS_WORKFLOW = REPO / ".github" / "workflows" / "tests.yml"

# Everything a user needs at runtime: the integration itself, its translations
# and the bundled card. The brand images belong to the HA brands repository,
# not to a user's config folder.
SHIPPABLE_SUFFIXES = {".py", ".json", ".js"}


def zip_excludes() -> list[str]:
    """The -x patterns the release workflow passes to zip.

    The fleet-wide workflow keeps them in two lists: ZIP_EXCLUDE_ALWAYS on the
    job, shared by every integration, and this repo's own ZIP_EXCLUDE in the
    per-repo env block. The zip step passes both.
    """
    text = RELEASE_WORKFLOW.read_text()
    assert (
        'lines "$ZIP_EXCLUDE_ALWAYS"; lines "$ZIP_EXCLUDE"' in text
    ), "the zip step no longer passes both exclusion lists"
    workflow = yaml.safe_load(text)
    patterns = workflow["jobs"]["release"]["env"]["ZIP_EXCLUDE_ALWAYS"]
    patterns += workflow["env"]["ZIP_EXCLUDE"]
    return [line.strip() for line in patterns.splitlines() if line.strip()]


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
    "icons.json",
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
    assert "icons.json" in packaged
    assert "skyline-webcams-card.js" in packaged


def test_only_runtime_file_types_are_packaged():
    unexpected = [
        name
        for name in surviving(component_files())
        if pathlib.Path(name).suffix not in SHIPPABLE_SUFFIXES
    ]
    assert unexpected == []


def core_version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def ci_minimum_core() -> tuple[int, ...]:
    """The oldest core the test workflow accepts as a valid run."""
    match = re.search(r"MINIMUM_CORE: '([0-9.]+)'", TESTS_WORKFLOW.read_text())
    assert match, "could not find MINIMUM_CORE in the test workflow"
    return core_version(match.group(1))


def test_hacs_offers_no_core_the_suite_never_ran_against():
    """hacs.json is what HACS filters on, so it must not reach below CI.

    It said 2024.7.0 - the floor for async_register_static_paths - while CI
    ran on 2026.9.3 and nothing in between was ever tested.
    """
    hacs = json.loads((REPO / "hacs.json").read_text())

    assert core_version(hacs["homeassistant"]) >= ci_minimum_core()
