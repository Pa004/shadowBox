"""Typer CLI: validate (M0) and simulate (M1); compare/report land in M3."""

import json
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import typer
import uvicorn
import yaml
from rich.console import Console

from shadowbox import engine as engine_mod
from shadowbox.cards import list_cards, write_tree
from shadowbox.compare import (
    DEFAULT_THRESHOLDS,
    compare_reports,
    parse_thresholds,
    seed_warning,
)
from shadowbox.dsl import load_model, load_scenario
from shadowbox.errors import SchemaError, ShadowBoxError
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
    try:
        number = pkg_version("shadowbox")
    except PackageNotFoundError:
        number = "0.0.0+local"
    console.print(f"shadowbox {number}")


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


def _read_report(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SchemaError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(data, dict) or "metrics" not in data:
        raise SchemaError(f"{path}: not a shadowbox report")
    return data


@app.command()
def report(
    report_path: Path = typer.Argument(..., help="Path to report.json"),
    format: str = typer.Option("json", "--format", help="json or text"),
) -> None:
    """Render an existing report file (exit 0 ok, 3 invalid)."""
    try:
        found = _read_report(report_path)
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    if format == "text":
        console.print(_as_text(found), end="")
    else:
        console.print_json(json.dumps(found, indent=2, sort_keys=True))


@app.command()
def compare(
    a: Path = typer.Option(..., "--a", help="Baseline report.json"),
    b: Path = typer.Option(..., "--b", help="Candidate report.json"),
    threshold: str = typer.Option(DEFAULT_THRESHOLDS, "--threshold", help="p99:+10%,..."),
) -> None:
    """Compare two reports (exit 0 pass/improvement, 2 regression, 3 invalid)."""
    try:
        base = _read_report(a)
        candidate = _read_report(b)
        result = compare_reports(base, candidate, parse_thresholds(threshold))
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    warning = seed_warning(base, candidate)
    if warning is not None:
        console.print(f"[yellow]warn[/yellow]: {warning}")
    for metric in sorted(result.deltas):
        console.print(f"{metric}: {result.deltas[metric]:+.2f}")
    if result.breaches:
        console.print(f"[red]regression[/red]: breached {', '.join(sorted(result.breaches))}")
        raise typer.Exit(code=2)
    console.print(f"[green]{result.verdict}[/green]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    db: Path = typer.Option(Path("shadowbox.db"), "--db", help="SQLite file"),
) -> None:
    """Run the local API server (blocks; Ctrl-C to stop)."""
    from shadowbox import api as api_mod
    from shadowbox.store import AsyncSqliteStore

    uvicorn.run(api_mod.create_app(AsyncSqliteStore(db)), host=host, port=port)


@app.command(name="init")
def init_project(
    out: Path = typer.Option(Path("."), "--out", help="Target directory"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files"),
    cards: bool = typer.Option(True, "--cards/--no-cards", help="Include chaos cards"),
) -> None:
    """Scaffold example model plus chaos cards (works without a repo clone)."""
    try:
        written = write_tree(out, force, include_cards=cards)
    except ShadowBoxError as exc:
        console.print(f"[red]{exc.code}[/red]: {exc}")
        raise typer.Exit(code=3) from exc
    console.print(f"[green]initialized[/green]: {len(written)} files -> {out}")
    console.print(f"cards available: {', '.join(n.replace('.yaml', '') for n in list_cards())}")


if __name__ == "__main__":
    app()
