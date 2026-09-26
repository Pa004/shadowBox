"""Bundled example and chaos cards, readable from an installed wheel (M6).

Canonical files live under `src/shadowbox/data/`; `init` copies them to the
user's directory so the tool works without a repo clone.
"""

from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from shadowbox.errors import ExistsError

_DATA = resources.files("shadowbox.data")
CARDS_DIR = _DATA / "cards"
EXAMPLE_DIR = _DATA / "example"

EXAMPLE_FILES = ("model.yaml", "docker-compose.yaml", "scenarios/db-failure.yaml")


def list_cards() -> list[str]:
    """Sorted chaos-card names shipped in the package."""
    return sorted(p.name for p in CARDS_DIR.iterdir() if p.name.endswith(".yaml"))


def read_card(name: str) -> str:
    """Card YAML text; name with or without `.yaml` suffix."""
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    return (CARDS_DIR / filename).read_text(encoding="utf-8")


def _copy_tree(source: Traversable, target: Path, written: list[str], force: bool) -> None:
    for entry in sorted(source.iterdir(), key=lambda p: p.name):
        dest = target / entry.name
        if entry.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            _copy_tree(entry, dest, written, force)
        elif entry.is_file():
            if dest.exists() and not force:
                raise ExistsError(f"{dest} exists (use --force to overwrite)")
            dest.write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
            written.append(str(dest))


def write_tree(out: Path, force: bool = False, include_cards: bool = True) -> list[str]:
    """Copy example (plus cards unless excluded) into `out`; returns written paths."""
    written: list[str] = []
    for filename in EXAMPLE_FILES:
        dest = out / filename
        if dest.exists() and not force:
            raise ExistsError(f"{dest} exists (use --force to overwrite)")
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = (_DATA / "example" / filename).read_text(encoding="utf-8")
        dest.write_text(text, encoding="utf-8")
        written.append(str(dest))
    if include_cards:
        cards_out = out / "cards"
        cards_out.mkdir(parents=True, exist_ok=True)
        _copy_tree(CARDS_DIR, cards_out, written, force)
    return written
