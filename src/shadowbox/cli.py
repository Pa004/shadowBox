"""Typer CLI: validate (M0) and simulate (M1); compare/report land in M3."""

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console

from shadowbox import engine as engine_mod
from shadowbox.dsl import load_model, load_scenario
from shadowbox.errors import ShadowBoxError
from shadowbox.importers.compose import import_compose
from shadowbox.metrics import summarize
from shadowbox.report import build_report

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
    console.print("shadowbox 0.1.0 (M2)")


@app.command(name="import")
def import_model(
    from_path: Path = typer.Option(..., "--from", help="Path to docker-compose.yaml"),
    out: Path = typer.Option(Path("model.yaml"), "--out", help="Imported model output path"),
) -> None:
    """Import a compose file into a validated model (all fields estimated)."""
    try:
        model, warnings = import_compose(from_path)
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    out.write_text(
        yaml.safe_dump(model.model_dump(mode="json", by_alias=True), sort_keys=False),
        encoding="utf-8",
    )
    for warning in warnings:
        console.print(f"[yellow]warn[/yellow]: {warning}")
    console.print(f"[green]imported[/green]: {len(model.components)} components -> {out}")


@app.command()
def simulate(
    model: Path = typer.Argument(..., help="Path to model.yaml"),
    scenario: Path = typer.Option(..., "--scenario", help="Path to scenario YAML"),
    seed: int = typer.Option(42, "--seed", help="Deterministic RNG seed"),
    out: Path = typer.Option(Path("report.json"), "--out", help="Report output path"),
    format: str = typer.Option("json", "--format", help="json or text"),
) -> None:
    """Run a deterministic simulation and write the report envelope."""
    try:
        system = load_model(model)
        ordered = load_scenario(scenario, system)
        result = engine_mod.simulate(system, ordered, seed)
        metrics = summarize(system, result, ordered.duration_s)
        report = build_report(
            system.model_dump(mode="json", by_alias=True),
            ordered.model_dump(mode="json"),
            seed,
            metrics,
            result.events_processed,
        )
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    if format == "text":
        out.write_text(_as_text(report), encoding="utf-8")
    else:
        out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    latency = metrics["latency_ms"]
    assert isinstance(latency, dict)
    error_rate = metrics["error_rate"]
    assert isinstance(error_rate, float)
    p99 = latency["p99"]
    assert isinstance(p99, (int, float))
    metrics_hash = report["metrics_hash"]
    assert isinstance(metrics_hash, str)
    console.print(
        f"[green]done[/green]: {result.succeeded}/{result.total} ok, "
        f"error_rate={error_rate:.3f}, p99={p99:.0f}ms, "
        f"hash={metrics_hash[:12]} -> {out}"
    )


def _as_text(report: dict[str, object]) -> str:
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    latency = metrics["latency_ms"]
    assert isinstance(latency, dict)
    lines = [
        f"engine: {report['engine']}",
        f"seed: {report['seed']}",
        f"metrics_hash: {report['metrics_hash']}",
        f"throughput_rps: {metrics['throughput_rps']}",
        f"error_rate: {metrics['error_rate']}",
        f"latency_ms p50/p95/p99: {latency['p50']}/{latency['p95']}/{latency['p99']}",
        f"timeouts: {metrics['timeouts']}, cascade_depth: {metrics['cascade_depth']}",
        f"confidence: {report['confidence']} ({report['calibration_source']})",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    app()
