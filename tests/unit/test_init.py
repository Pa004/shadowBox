"""Init round-trip: bundled cards scaffold a working directory without a clone."""

from pathlib import Path

from typer.testing import CliRunner

from shadowbox.cards import list_cards, write_tree
from shadowbox.cli import app
from shadowbox.dsl import load_model, load_scenario

runner = CliRunner()
EXPECTED_CARDS = {
    "db-down.yaml",
    "cache-poison.yaml",
    "latency-500ms.yaml",
    "traffic-10x.yaml",
    "zone-loss.yaml",
    "slow-dependency.yaml",
    "queue-overflow.yaml",
}


def test_list_cards() -> None:
    assert set(list_cards()) == EXPECTED_CARDS


def test_write_tree_round_trip(tmp_path: Path) -> None:
    written = write_tree(tmp_path)
    assert len(written) == 3 + len(EXPECTED_CARDS)
    model = load_model(tmp_path / "model.yaml")
    for card in sorted((tmp_path / "cards").glob("*.yaml")):
        load_scenario(card, model)  # every shipped card validates


def test_cli_init_flow(tmp_path: Path) -> None:
    first = runner.invoke(app, ["init", "--out", str(tmp_path)])
    assert first.exit_code == 0
    assert (tmp_path / "cards" / "db-down.yaml").exists()
    second = runner.invoke(app, ["init", "--out", str(tmp_path)])
    assert second.exit_code == 3
    assert "E_EXISTS" in second.output
    forced = runner.invoke(app, ["init", "--out", str(tmp_path), "--force"])
    assert forced.exit_code == 0
