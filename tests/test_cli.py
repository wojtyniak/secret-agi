"""Tests for the `secretagi` CLI: run, resume, score, export, validate."""

import json

import pytest
import yaml
from typer.testing import CliRunner

from secret_agi.cli import REPORT_FILENAME, SCORECARD_FILENAME, app

runner = CliRunner()


@pytest.fixture
def run_config(tmp_path):
    """A tiny mock-only run config on disk."""
    config = {
        "name": "cli-test",
        "player_count": 5,
        "games": 2,
        "seed": 4,
        "parallelism": 2,
        "database_url": f"sqlite:///{tmp_path / 'cli.db'}",
        "players": [{"provider": "mock", "model": "mock-a", "seats": 5}],
        "chat": {"enabled": True, "messages_per_player": 1},
        "judge": {"enabled": True, "provider": "mock", "model": "mock-judge"},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


class TestValidate:
    def test_a_good_config_validates(self, run_config):
        result = runner.invoke(app, ["validate", str(run_config)])

        assert result.exit_code == 0
        assert "cli-test: OK" in result.stdout
        assert "mock-a" in result.stdout

    def test_a_bad_config_exits_nonzero(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.safe_dump({"name": "x", "players": []}), encoding="utf-8")

        result = runner.invoke(app, ["validate", str(path)])

        assert result.exit_code == 1

    def test_a_missing_config_exits_nonzero(self, tmp_path):
        result = runner.invoke(app, ["validate", str(tmp_path / "nope.yaml")])

        assert result.exit_code == 1


class TestRunAndScore:
    def test_run_plays_the_schedule_and_writes_a_report(self, run_config, tmp_path):
        runs_dir = tmp_path / "runs"

        result = runner.invoke(
            app, ["run", str(run_config), "--runs-dir", str(runs_dir)]
        )

        assert result.exit_code == 0, result.stdout
        assert "2/2 games completed" in result.stdout

        report = json.loads(
            (runs_dir / "cli-test-4" / REPORT_FILENAME).read_text(encoding="utf-8")
        )
        assert report["games_completed"] == 2
        assert len(report["games"]) == 2

    def test_score_emits_a_scorecard_and_a_summary(self, run_config, tmp_path):
        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])

        result = runner.invoke(
            app,
            [
                "score",
                "cli-test-4",
                "--runs-dir",
                str(runs_dir),
                "--config",
                str(run_config),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "mock-a" in result.stdout
        assert "Backstab Rate" in result.stdout

        payload = json.loads(
            (runs_dir / "cli-test-4" / SCORECARD_FILENAME).read_text(encoding="utf-8")
        )
        assert payload["games_scored"] == 2
        assert "mock-a" in payload["scorecards"]

    def test_scorecard_json_carries_intervals_on_every_metric(
        self, run_config, tmp_path
    ):
        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])
        runner.invoke(
            app,
            ["score", "cli-test-4", "--runs-dir", str(runs_dir), "--config", str(run_config)],
        )

        payload = json.loads(
            (runs_dir / "cli-test-4" / SCORECARD_FILENAME).read_text(encoding="utf-8")
        )
        card = payload["scorecards"]["mock-a"]

        for metric in ("win_rate", "backstab_rate", "gullibility", "circle_of_trust"):
            assert set(card[metric]) >= {"value", "ci_low", "ci_high", "n"}

    def test_score_without_a_run_exits_nonzero(self, tmp_path):
        result = runner.invoke(
            app, ["score", "no-such-run", "--runs-dir", str(tmp_path)]
        )

        assert result.exit_code == 1

    def test_json_flag_prints_machine_readable_output(self, run_config, tmp_path):
        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])

        result = runner.invoke(
            app,
            [
                "score",
                "cli-test-4",
                "--runs-dir",
                str(runs_dir),
                "--config",
                str(run_config),
                "--json",
            ],
        )

        assert result.exit_code == 0
        assert json.loads(result.stdout)["games_scored"] == 2


class TestResume:
    def test_resume_completes_an_interrupted_run(self, run_config, tmp_path):
        from secret_agi.match.runner import STATE_FILENAME

        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])

        # Drop one finished game from the state, as a kill mid-run would.
        state_path = runs_dir / "cli-test-4" / STATE_FILENAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["completed"].pop("1")
        state_path.write_text(json.dumps(state), encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "resume",
                "cli-test-4",
                "--config",
                str(run_config),
                "--runs-dir",
                str(runs_dir),
            ],
        )

        assert result.exit_code == 0, result.stdout
        assert "2/2 games completed" in result.stdout

    def test_resuming_a_run_that_does_not_exist_exits_nonzero(
        self, run_config, tmp_path
    ):
        result = runner.invoke(
            app,
            [
                "resume",
                "ghost",
                "--config",
                str(run_config),
                "--runs-dir",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 1


class TestExport:
    def test_export_bundles_the_report_and_scorecards(self, run_config, tmp_path):
        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])
        runner.invoke(
            app,
            ["score", "cli-test-4", "--runs-dir", str(runs_dir), "--config", str(run_config)],
        )

        destination = tmp_path / "export.json"
        result = runner.invoke(
            app,
            [
                "export",
                "cli-test-4",
                "--runs-dir",
                str(runs_dir),
                "--output",
                str(destination),
            ],
        )

        assert result.exit_code == 0, result.stdout
        document = json.loads(destination.read_text(encoding="utf-8"))
        assert "report" in document
        assert "scorecards" in document
        assert document["scorecards"]["games_scored"] == 2

    def test_exporting_before_scoring_exits_nonzero(self, run_config, tmp_path):
        runs_dir = tmp_path / "runs"
        runner.invoke(app, ["run", str(run_config), "--runs-dir", str(runs_dir)])

        result = runner.invoke(
            app, ["export", "cli-test-4", "--runs-dir", str(runs_dir)]
        )

        assert result.exit_code == 1
