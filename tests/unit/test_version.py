"""Release hygiene: package version is explicit and bumped per release."""

from importlib.metadata import version as pkg_version

EXPECTED = "0.3.2"


def test_package_version_matches_release() -> None:
    assert pkg_version("shadowbox") == EXPECTED
