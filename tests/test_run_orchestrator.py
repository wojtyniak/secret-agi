"""Tests for the run orchestrator: concurrency, cost caps and resumability.

All on the mock adapter, so nothing here reaches a provider.
"""

import asyncio
import json

import pytest

from secret_agi.match import ModelPrice, RunOrchestrator, parse_run_config
from secret_agi.match.runner import STATE_FILENAME
from secret_agi.providers.base import TokenUsage


def config(tmp_path, **overrides):
    raw = {
        "name": "test-run",
        "player_count": 5,
        "games": 3,
        "seed": 5,
        "parallelism": 2,
        "database_url": f"sqlite:///{tmp_path / 'run.db'}",
        "players": [{"provider": "mock", "model": "mock-a", "seats": 5}],
        "chat": {"enabled": True, "messages_per_player": 1},
        "judge": {"enabled": False, "provider": "mock", "model": "mock-judge"},
    }
    raw.update(overrides)
    return parse_run_config(raw)


class TestRunExecution:
    @pytest.mark.asyncio
    async def test_a_run_plays_every_scheduled_game(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        assert report.games_requested == 3
        assert report.games_completed == 3
        assert all(r.completed for r in report.results)
        assert report.stopped_early is None

    @pytest.mark.asyncio
    async def test_games_get_distinct_ids(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        assert len({r.game_id for r in report.results}) == 3

    @pytest.mark.asyncio
    async def test_the_report_records_the_seat_balance_control(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        assert report.seat_balance
        assert "mock-a" in report.seat_balance

    @pytest.mark.asyncio
    async def test_the_same_seed_reproduces_the_run(self, tmp_path):
        first = await RunOrchestrator(
            config(tmp_path / "a"), run_dir=tmp_path / "a"
        ).run()
        second = await RunOrchestrator(
            config(tmp_path / "b"), run_dir=tmp_path / "b"
        ).run()

        assert [r.winners for r in first.results] == [r.winners for r in second.results]
        assert [r.roles for r in first.results] == [r.roles for r in second.results]

    @pytest.mark.asyncio
    async def test_games_actually_overlap(self, tmp_path):
        """Parallelism has to mean concurrency, not just a bigger loop."""
        orchestrator = RunOrchestrator(
            config(tmp_path, games=4, parallelism=4), run_dir=tmp_path
        )

        in_flight = 0
        peak = 0
        original = orchestrator._play_game

        async def tracked(game):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                await asyncio.sleep(0)
                return await original(game)
            finally:
                in_flight -= 1

        orchestrator._play_game = tracked  # type: ignore[method-assign]
        await orchestrator.run()

        assert peak > 1, "games ran strictly one after another"

    @pytest.mark.asyncio
    async def test_provider_concurrency_is_capped_independently(self, tmp_path):
        orchestrator = RunOrchestrator(
            config(tmp_path, games=2, parallelism=2, provider_concurrency=1),
            run_dir=tmp_path,
        )
        report = await orchestrator.run()

        # One in-flight call per provider still completes every game.
        assert report.games_completed == 2


class TestCostCap:
    @pytest.mark.asyncio
    async def test_a_run_stops_cleanly_at_its_token_cap(self, tmp_path):
        orchestrator = RunOrchestrator(
            config(tmp_path, games=5, parallelism=1, max_total_tokens=1),
            run_dir=tmp_path,
        )

        report = await orchestrator.run()

        # The first game blows the cap; the rest are never started.
        assert report.stopped_early is not None
        assert report.games_completed < 5
        assert report.games_completed >= 1

    @pytest.mark.asyncio
    async def test_completed_games_survive_an_early_stop(self, tmp_path):
        orchestrator = RunOrchestrator(
            config(tmp_path, games=4, parallelism=1, max_total_tokens=1),
            run_dir=tmp_path,
        )

        report = await orchestrator.run()

        assert report.results
        assert all(r.completed for r in report.results)

    @pytest.mark.asyncio
    async def test_a_generous_cap_does_not_stop_the_run(self, tmp_path):
        orchestrator = RunOrchestrator(
            config(tmp_path, max_total_tokens=10**12), run_dir=tmp_path
        )

        report = await orchestrator.run()

        assert report.stopped_early is None
        assert report.games_completed == 3

    @pytest.mark.asyncio
    async def test_costs_are_reported_when_prices_are_known(self, tmp_path):
        orchestrator = RunOrchestrator(
            config(tmp_path, games=1),
            run_dir=tmp_path,
            prices={
                "mock-a": ModelPrice(input_per_million=1.0, output_per_million=2.0)
            },
        )

        report = await orchestrator.run()

        assert report.cost["total_cost_usd"] > 0
        assert report.cost["unpriced_models"] == []

    @pytest.mark.asyncio
    async def test_unpriced_models_are_flagged_rather_than_counted_free(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path, games=1), run_dir=tmp_path).run()

        assert report.cost["unpriced_models"] == ["mock-a"]
        assert report.cost["total_tokens"] > 0


class TestResumability:
    @pytest.mark.asyncio
    async def test_state_is_written_as_games_finish(self, tmp_path):
        await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        state = json.loads((tmp_path / STATE_FILENAME).read_text())

        assert state["games_total"] == 3
        assert len(state["completed"]) == 3

    @pytest.mark.asyncio
    async def test_resuming_replays_only_unfinished_games(self, tmp_path):
        run_config = config(tmp_path, games=4, parallelism=1)

        # Simulate a kill after two games by writing a partial state file.
        first = await RunOrchestrator(run_config, run_dir=tmp_path).run()
        state = json.loads((tmp_path / STATE_FILENAME).read_text())
        state["completed"] = {
            k: v for k, v in state["completed"].items() if int(k) < 2
        }
        (tmp_path / STATE_FILENAME).write_text(json.dumps(state))

        played: list[int] = []
        orchestrator = RunOrchestrator(run_config, run_dir=tmp_path)
        original = orchestrator._play_game

        async def tracked(game):
            played.append(game.index)
            return await original(game)

        orchestrator._play_game = tracked  # type: ignore[method-assign]
        second = await orchestrator.run(resume=True)

        assert sorted(played) == [2, 3], "resume replayed already-finished games"
        assert second.games_completed == first.games_completed == 4

    @pytest.mark.asyncio
    async def test_a_resumed_run_matches_an_uninterrupted_one(self, tmp_path):
        """Interrupting a run must not change its results."""
        run_config = config(tmp_path / "whole", games=3, parallelism=1)
        whole = await RunOrchestrator(run_config, run_dir=tmp_path / "whole").run()

        partial_config = config(tmp_path / "split", games=3, parallelism=1)
        split_dir = tmp_path / "split"
        await RunOrchestrator(partial_config, run_dir=split_dir).run()
        state = json.loads((split_dir / STATE_FILENAME).read_text())
        state["completed"] = {
            k: v for k, v in state["completed"].items() if int(k) < 1
        }
        (split_dir / STATE_FILENAME).write_text(json.dumps(state))
        resumed = await RunOrchestrator(partial_config, run_dir=split_dir).run(
            resume=True
        )

        by_index = lambda report: sorted(  # noqa: E731
            (r.winners, r.turns, sorted(r.roles.items())) for r in report.results
        )
        assert by_index(resumed) == by_index(whole)

    @pytest.mark.asyncio
    async def test_resuming_into_a_different_schedule_is_refused(self, tmp_path):
        """Silently mixing two runs' games would corrupt the results."""
        await RunOrchestrator(config(tmp_path, games=3), run_dir=tmp_path).run()

        mismatched = config(tmp_path, games=5)
        with pytest.raises(ValueError, match="refusing to resume"):
            await RunOrchestrator(mismatched, run_dir=tmp_path).run(resume=True)

    @pytest.mark.asyncio
    async def test_resuming_with_no_state_starts_fresh(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run(
            resume=True
        )

        assert report.games_completed == 3

    @pytest.mark.asyncio
    async def test_a_corrupt_state_file_does_not_crash_the_run(self, tmp_path):
        (tmp_path / STATE_FILENAME).write_text("{not json")

        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run(
            resume=True
        )

        assert report.games_completed == 3

    @pytest.mark.asyncio
    async def test_a_run_without_a_directory_keeps_no_state(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=None).run()

        assert report.games_completed == 3
        assert not (tmp_path / STATE_FILENAME).exists()


class TestJudgeIntegration:
    @pytest.mark.asyncio
    async def test_the_judge_labels_the_run_when_enabled(self, tmp_path):
        from secret_agi.database.connection import get_async_session
        from secret_agi.database.operations import GameOperations

        run_config = config(
            tmp_path,
            games=1,
            judge={"enabled": True, "provider": "mock", "model": "mock-judge"},
        )
        report = await RunOrchestrator(run_config, run_dir=tmp_path).run()

        async with get_async_session() as session:
            labels = await GameOperations.get_chat_labels_for_game(
                session, report.results[0].game_id
            )

        assert labels
        assert all(row.judge_model == "mock-judge" for row in labels)

    @pytest.mark.asyncio
    async def test_a_disabled_judge_writes_no_labels(self, tmp_path):
        from secret_agi.database.connection import get_async_session
        from secret_agi.database.operations import GameOperations

        report = await RunOrchestrator(config(tmp_path, games=1), run_dir=tmp_path).run()

        async with get_async_session() as session:
            labels = await GameOperations.get_chat_labels_for_game(
                session, report.results[0].game_id
            )

        assert labels == []


class TestReportShape:
    @pytest.mark.asyncio
    async def test_the_report_serialises_every_game(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        payload = report.as_dict()

        assert payload["games_completed"] == 3
        assert len(payload["games"]) == 3
        for game in payload["games"]:
            assert {"game_id", "winners", "roles", "models"} <= set(game)

    @pytest.mark.asyncio
    async def test_token_totals_are_carried_in_the_report(self, tmp_path):
        report = await RunOrchestrator(config(tmp_path), run_dir=tmp_path).run()

        assert report.cost["total_tokens"] > 0
        assert report.cost["tokens_per_game"] > 0


class TestPriceModel:
    def test_zero_usage_costs_nothing(self):
        price = ModelPrice(input_per_million=5.0, output_per_million=15.0)
        assert price.cost(TokenUsage()) == 0.0

    def test_output_tokens_are_priced_separately(self):
        price = ModelPrice(input_per_million=0.0, output_per_million=10.0)
        assert price.cost(TokenUsage(output_tokens=1_000_000)) == pytest.approx(10.0)
