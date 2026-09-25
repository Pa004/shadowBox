"""Typer CLI for M0 (validate only; simulate/compare/report land in M1-M3)."""

from pathlib import Path

import typer
from rich.console import Console

from shadowbox.dsl import load_model, load_scenario
from shadowbox.errors import ShadowBoxError

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def validate(
    model: Path = typer.Argument(..., help="Path to model.yaml"),
    scenario: Path = typer.Option(None, "--scenario", help="Path to scenario YAML"),
) -> None:
    """Validate a model and optionally a scenario (exit 0 ok, 3 invalid)."""
    try:
        system = load_model(model)
        if scenario is not None:
            load_scenario(scenario, system)
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    faults = f", {len(system.connections)} connections" if system.connections else ""
    console.print(f"[green]valid[/green]: {len(system.components)} components{faults}")


@app.command()
def version() -> None:
    """Print the package version (also keeps `validate` as a named subcommand)."""
    console.print("shadowbox 0.1.0 (M0)")


if __name__ == "__main__":
    app()
