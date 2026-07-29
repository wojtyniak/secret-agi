"""M2 exit criterion: one self-play run produces a complete model scorecard.

Plays real (mock-backed) games, judges the transcripts, and scores the result —
exercising the whole chain from a model decision through to a published number.
"""

import pytest

from secret_agi.analysis import ChatJudge, build_scorecards, load_game_record
from secret_agi.analysis.scorecard import cooperation_matrix
from secret_agi.database.connection import get_async_session
from secret_agi.database.operations import GameOperations
from secret_agi.engine.models import GameConfig
from secret_agi.match import GameRunner
from secret_agi.players.llm_player import LLMPlayer
from secret_agi.providers import MockAdapter

DB = "sqlite:///:memory:"


async def play(model: str, seed: int, *, models: list[str] | None = None):
    """Play one 5-player game and return its result."""
    ids = [f"p{i}" for i in range(5)]
    assigned = models or [model] * 5
    players = [
        LLMPlayer(pid, MockAdapter(model_name=assigned[i], seed=seed * 10 + i))
        for i, pid in enumerate(ids)
    ]
    config = GameConfig(
        5, ids, seed=seed, chat_enabled=True, chat_messages_per_player=1
    )
    runner = GameRunner(
        players, config=config, database_url=DB, probe_each_round=True
    )
    return await runner.run()


async def score(results, *, judge_labels: bool = True):
    """Judge and score a batch of finished games."""
    records = []
    for result in results:
        if judge_labels:
            judge = ChatJudge(MockAdapter(model_name="mock-judge", seed=7))
            await judge.judge_game(result.game_id, result.roles)
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
    return records


class TestSelfPlayScorecard:
    @pytest.mark.asyncio
    async def test_a_self_play_run_produces_a_complete_scorecard(self):
        results = [await play("mock-model", seed) for seed in (1, 2, 3)]
        records = await score(results)

        cards = build_scorecards(records)

        assert set(cards) == {"mock-model"}
        card = cards["mock-model"]
        assert card.games == 3
        assert card.decisions > 0

        # Every metric that has data must carry a real interval.
        payload = card.as_dict()
        for key in (
            "win_rate",
            "backstab_rate",
            "gullibility",
            "circle_of_trust",
            "invalid_action_rate",
            "tokens_per_game",
        ):
            metric = payload[key]
            assert metric["n"] > 0, f"{key} has no observations"
            assert metric["ci_low"] <= metric["value"] <= metric["ci_high"]

    @pytest.mark.asyncio
    async def test_win_rates_are_reported_for_every_role(self):
        results = [await play("mock-model", seed) for seed in (4, 5, 6)]
        records = await score(results)

        card = build_scorecards(records)["mock-model"]

        assert set(card.win_rate_by_role) == {"Safety", "Accelerationist", "AGI"}

    @pytest.mark.asyncio
    async def test_the_summary_renders_every_headline_metric(self):
        results = [await play("mock-model", 7)]
        records = await score(results)

        summary = build_scorecards(records)["mock-model"].summary()

        for heading in (
            "win rate",
            "Backstab Rate",
            "Poker Face",
            "Gullibility",
            "Circle of Trust",
            "Under Oath",
            "invalid action rate",
        ):
            assert heading in summary

    @pytest.mark.asyncio
    async def test_scoring_the_same_run_twice_gives_the_same_numbers(self):
        """Intervals must be a function of the data, not of when it was scored."""
        results = [await play("mock-model", seed) for seed in (8, 9)]
        records = await score(results)

        first = build_scorecards(records)["mock-model"].as_dict()
        second = build_scorecards(records)["mock-model"].as_dict()

        assert first == second


class TestMixedLobbyScorecards:
    @pytest.mark.asyncio
    async def test_each_model_gets_its_own_card(self):
        models = ["model-a", "model-b", "model-a", "model-b", "model-a"]
        results = [await play("", seed, models=models) for seed in (11, 12)]
        records = await score(results)

        cards = build_scorecards(records)

        assert set(cards) == {"model-a", "model-b"}
        assert cards["model-a"].games == 2
        assert cards["model-b"].games == 2

    @pytest.mark.asyncio
    async def test_the_cooperation_matrix_covers_both_models(self):
        models = ["model-a", "model-b", "model-a", "model-b", "model-a"]
        results = [await play("", seed, models=models) for seed in (13, 14, 15)]
        records = await score(results, judge_labels=False)

        matrix = cooperation_matrix(records)

        assert set(matrix) == {"model-a", "model-b"}
        for allies in matrix.values():
            for estimate in allies.values():
                assert estimate.n > 0


class TestInstrumentationCoverage:
    @pytest.mark.asyncio
    async def test_every_model_decision_writes_a_metric_row(self):
        result = await play("mock-model", 21)

        async with get_async_session() as session:
            metrics = await GameOperations.get_agent_metrics_for_game(
                session, result.game_id
            )

        assert metrics
        assert all(m.tokens_used and m.tokens_used > 0 for m in metrics)
        assert all(m.response_time_ms is not None for m in metrics)

    @pytest.mark.asyncio
    async def test_every_chat_message_ends_up_with_a_judge_label(self):
        """Acceptance criterion #4: no message goes unlabelled."""
        result = await play("mock-model", 22)
        judge = ChatJudge(MockAdapter(model_name="mock-judge", seed=3))
        await judge.judge_game(result.game_id, result.roles)

        async with get_async_session() as session:
            messages = await GameOperations.get_chat_messages_for_game(
                session, result.game_id
            )
            labels = await GameOperations.get_chat_labels_for_game(
                session, result.game_id
            )

        assert messages
        assert {label.message_id for label in labels} == {m.id for m in messages}

    @pytest.mark.asyncio
    async def test_probes_exist_for_every_round(self):
        result = await play("mock-model", 23)

        async with get_async_session() as session:
            probes = await GameOperations.get_belief_probes_for_game(
                session, result.game_id
            )

        assert probes
        rounds = {p.round_number for p in probes}
        assert rounds == set(range(1, max(rounds) + 1))

        # Each probe covers the other living players and never the speaker.
        for probe in probes:
            assert probe.beliefs
            assert probe.player_id not in probe.beliefs
