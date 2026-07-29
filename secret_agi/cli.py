"""`secretagi` — run, resume, score and export benchmark runs."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Any

import typer

from .analysis.scorecard import build_scorecards, cooperation_matrix, load_game_record
from .match import RunConfig, RunOrchestrator, load_run_config
from .match.runner import STATE_FILENAME, RunReport, _result_from_json

app = typer.Typer(
    add_completion=False,
    help="Secret AGI Bench: run LLM agents through the Secret AGI game and score them.",
)

DEFAULT_RUNS_DIR = Path("runs")
REPORT_FILENAME = "report.json"
SCORECARD_FILENAME = "scorecard.json"


@app.command()
def run(
    config_path: Annotated[Path, typer.Argument(help="Path to a YAML run config.")],
    runs_dir: Annotated[
        Path,
        typer.Option("--runs-dir", help="Where run state and reports are written."),
    ] = DEFAULT_RUNS_DIR,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Play a full run: every game in the config's schedule."""
    _configure_logging(verbose)
    config = _load(config_path)
    report = asyncio.run(_execute(config, runs_dir, resume=False))
    _emit(report, config, runs_dir)


@app.command()
def resume(
    run_id: Annotated[
        str, typer.Argument(help="The run id to resume (its directory name).")
    ],
    config_path: Annotated[
        Path,
        typer.Option("--config", help="The same run config the run started from."),
    ],
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = DEFAULT_RUNS_DIR,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Continue a run that was interrupted, replaying only unfinished games."""
    _configure_logging(verbose)
    config = _load(config_path)

    state_file = runs_dir / run_id / STATE_FILENAME
    if not state_file.is_file():
        typer.echo(f"No resumable run at {state_file}", err=True)
        raise typer.Exit(code=1)

    report = asyncio.run(_execute(config, runs_dir, resume=True, run_id=run_id))
    _emit(report, config, runs_dir, run_id=run_id)


@app.command()
def score(
    run_id: Annotated[str, typer.Argument(help="The run id to score.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = DEFAULT_RUNS_DIR,
    config_path: Annotated[
        Path | None,
        typer.Option("--config", help="Run config, for the database URL."),
    ] = None,
    json_only: Annotated[
        bool, typer.Option("--json", help="Print JSON, no summary.")
    ] = False,
) -> None:
    """Compute scorecards for a finished run."""
    report = _read_report(runs_dir / run_id / REPORT_FILENAME)
    database_url = None
    if config_path is not None:
        database_url = _load(config_path).database_url

    payload = asyncio.run(_score(report, database_url))
    target = runs_dir / run_id / SCORECARD_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if json_only:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(payload["summary"])
    typer.echo(f"\nScorecard written to {target}")


@app.command()
def export(
    run_id: Annotated[str, typer.Argument(help="The run id to export.")],
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = DEFAULT_RUNS_DIR,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Destination JSON file."),
    ] = None,
) -> None:
    """Export a run's report and scorecards as a single JSON document."""
    run_path = runs_dir / run_id
    report = _read_report(run_path / REPORT_FILENAME)

    scorecard_path = run_path / SCORECARD_FILENAME
    scorecards = (
        json.loads(scorecard_path.read_text(encoding="utf-8"))
        if scorecard_path.is_file()
        else None
    )
    if scorecards is None:
        typer.echo("No scorecard found; run `secretagi score` first.", err=True)
        raise typer.Exit(code=1)

    document = {"report": report, "scorecards": scorecards}
    destination = output or run_path / "export.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(document, indent=2), encoding="utf-8")
    typer.echo(f"Exported to {destination}")


@app.command()
def validate(
    config_path: Annotated[Path, typer.Argument(help="Path to a YAML run config.")],
) -> None:
    """Check a run config without playing anything."""
    config = _load(config_path)
    schedule_size = config.games
    typer.echo(f"{config.name}: OK")
    typer.echo(f"  {schedule_size} games of {config.player_count} players")
    typer.echo(f"  models: {', '.join(config.models)}")
    typer.echo(f"  seed: {config.seed}   parallelism: {config.parallelism}")
    typer.echo(f"  chat: {'on' if config.chat.enabled else 'off'}")


async def _execute(
    config: RunConfig, runs_dir: Path, *, resume: bool, run_id: str | None = None
) -> RunReport:
    directory = runs_dir / (run_id or f"{config.name}-{config.seed}")
    orchestrator = RunOrchestrator(config, run_dir=directory)
    return await orchestrator.run(resume=resume)


async def _score(report: dict[str, Any], database_url: str | None) -> dict[str, Any]:
    from .database.connection import init_database

    await init_database(
        database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        if database_url and database_url.startswith("sqlite://")
        else database_url
    )

    records = []
    for game in report.get("games", []):
        result = _result_from_json(game)
        if not result.completed:
            continue
        records.append(
            await load_game_record(
                result.game_id,
                result.roles,
                result.models,
                result.winners,
                capability=result.capability,
                safety=result.safety,
            )
        )

    cards = build_scorecards(records)
    matrix = cooperation_matrix(records)
    summary = "\n\n".join(card.summary() for card in cards.values())

    return {
        "run_id": report.get("run_id"),
        "games_scored": len(records),
        "scorecards": {name: card.as_dict() for name, card in cards.items()},
        "cooperation_matrix": {
            model: {ally: est.as_dict() for ally, est in allies.items()}
            for model, allies in matrix.items()
        },
        "cost": report.get("cost"),
        "seat_balance": report.get("seat_balance"),
        "summary": summary or "No completed games to score.",
    }


def _emit(
    report: RunReport, config: RunConfig, runs_dir: Path, run_id: str | None = None
) -> None:
    directory = runs_dir / (run_id or report.run_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / REPORT_FILENAME).write_text(
        json.dumps(report.as_dict(), indent=2), encoding="utf-8"
    )

    typer.echo(
        f"{report.config_name}: {report.games_completed}/{report.games_requested} games completed"
    )
    if report.stopped_early:
        typer.echo(f"Stopped early: {report.stopped_early}")

    cost = report.cost
    typer.echo(f"Tokens: {cost['total_tokens']}   Cost: ${cost['total_cost_usd']:.4f}")
    if cost["unpriced_models"]:
        typer.echo(f"(no prices configured for: {', '.join(cost['unpriced_models'])})")
    typer.echo(f"Report written to {directory / REPORT_FILENAME}")


def _load(path: Path) -> RunConfig:
    try:
        return load_run_config(path)
    except (OSError, ValueError) as exc:
        typer.echo(f"Could not load {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _read_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        typer.echo(f"No run report at {path}", err=True)
        raise typer.Exit(code=1)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    app()
