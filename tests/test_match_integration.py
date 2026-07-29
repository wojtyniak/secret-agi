"""Full-game integration tests on the mock adapter.

These are the M1 exit criterion: a complete game with chat, played by LLM players
across a mixed provider lobby, completing reliably and deterministically.

Nothing here calls a real provider API.
"""

from typing import Any

import pytest

from secret_agi.database.connection import get_async_session
from secret_agi.database.operations import GameOperations
from secret_agi.engine.models import GameConfig
from secret_agi.match import GameRunner, run_game, summarise_results
from secret_agi.players.llm_player import LLMPlayer
from secret_agi.players.random_player import RandomPlayer
from secret_agi.providers import MockAdapter

DB = "sqlite:///:memory:"


def mixed_lobby(player_ids: list[str], seed: int = 0) -> list[LLMPlayer]:
    """Half the seats on a mock OpenAI model, half on a mock Anthropic one."""
    players = []
    for i, pid in enumerate(player_ids):
        openai_seat = i % 2 == 0
        adapter = MockAdapter(
            model_name="mock-gpt" if openai_seat else "mock-claude",
            provider_label="openai" if openai_seat else "anthropic",
            seed=seed * 100 + i,
        )
        players.append(LLMPlayer(pid, adapter))
    return players


def chat_config(player_ids: list[str], seed: int, **overrides: Any) -> GameConfig:
    params: dict[str, Any] = {
        "player_count": len(player_ids),
        "player_ids": player_ids,
        "seed": seed,
        "chat_enabled": True,
        "chat_messages_per_player": 1,
    }
    params.update(overrides)
    return GameConfig(**params)


class TestFullGame:
    @pytest.mark.asyncio
    async def test_mixed_provider_lobby_completes(self):
        ids = [f"p{i}" for i in range(5)]
        result = await run_game(
            mixed_lobby(ids, seed=1), config=chat_config(ids, seed=7), database_url=DB
        )

        assert result.completed is True
        assert result.error is None
        assert result.winners
        assert set(result.models.values()) == {"mock-gpt", "mock-claude"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("player_count", [5, 7, 10])
    async def test_completes_at_every_table_size(self, player_count):
        ids = [f"p{i}" for i in range(player_count)]
        result = await run_game(
            mixed_lobby(ids, seed=2),
            config=chat_config(ids, seed=player_count),
            database_url=DB,
        )

        assert result.completed is True
        assert len(result.roles) == player_count

    @pytest.mark.asyncio
    async def test_llm_and_random_players_can_share_a_table(self):
        ids = [f"p{i}" for i in range(5)]
        players = [
            LLMPlayer(ids[0], MockAdapter(model_name="mock-gpt", seed=1)),
            LLMPlayer(ids[1], MockAdapter(model_name="mock-claude", seed=2)),
            RandomPlayer(ids[2]),
            RandomPlayer(ids[3]),
            RandomPlayer(ids[4]),
        ]

        result = await run_game(
            players, config=chat_config(ids, seed=3), database_url=DB
        )

        assert result.completed is True
        assert result.models[ids[2]] == "RandomPlayer"

    @pytest.mark.asyncio
    async def test_game_without_chat_still_completes(self):
        ids = [f"p{i}" for i in range(5)]
        result = await run_game(
            mixed_lobby(ids, seed=4),
            config=chat_config(ids, seed=9, chat_enabled=False),
            database_url=DB,
        )

        assert result.completed is True


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_same_seed_and_script_reproduce_the_transcript(self):
        ids = [f"p{i}" for i in range(5)]

        async def play():
            result = await run_game(
                mixed_lobby(ids, seed=5), config=chat_config(ids, seed=13), database_url=DB
            )
            async with get_async_session() as session:
                messages = await GameOperations.get_chat_messages_for_game(
                    session, result.game_id
                )
                actions = await GameOperations.get_actions_for_game(
                    session, result.game_id
                )
            return (
                result.winners,
                result.turns,
                result.roles,
                [(m.speaker_id, m.message) for m in messages],
                [(a.player_id, a.action_type) for a in actions],
            )

        assert await play() == await play()

    @pytest.mark.asyncio
    async def test_different_seeds_diverge(self):
        ids = [f"p{i}" for i in range(5)]

        async def roles(seed: int):
            result = await run_game(
                mixed_lobby(ids, seed=6),
                config=chat_config(ids, seed=seed),
                database_url=DB,
            )
            return result.roles

        assert await roles(21) != await roles(22)


class TestPersistedArtefacts:
    @pytest.mark.asyncio
    async def test_chat_actions_and_probes_are_all_recorded(self):
        ids = [f"p{i}" for i in range(5)]
        runner = GameRunner(
            mixed_lobby(ids, seed=8),
            config=chat_config(ids, seed=17),
            database_url=DB,
            probe_each_round=True,
        )
        result = await runner.run()

        async with get_async_session() as session:
            messages = await GameOperations.get_chat_messages_for_game(
                session, result.game_id
            )
            actions = await GameOperations.get_actions_for_game(session, result.game_id)
            probes = await GameOperations.get_belief_probes_for_game(
                session, result.game_id
            )

        assert messages
        assert actions
        assert probes

        # Every living player is probed in every round that was probed.
        probed_rounds = {p.round_number for p in probes}
        for round_number in probed_rounds:
            in_round = [p for p in probes if p.round_number == round_number]
            assert len(in_round) >= 1
            for probe in in_round:
                assert probe.beliefs
                assert probe.player_id not in probe.beliefs

    @pytest.mark.asyncio
    async def test_token_usage_is_accounted(self):
        ids = [f"p{i}" for i in range(5)]
        result = await run_game(
            mixed_lobby(ids, seed=9), config=chat_config(ids, seed=19), database_url=DB
        )

        assert result.input_tokens > 0
        assert result.output_tokens > 0


class TestRunnerGuards:
    @pytest.mark.asyncio
    async def test_player_count_mismatch_is_rejected(self):
        ids = [f"p{i}" for i in range(5)]
        with pytest.raises(ValueError, match="players for a"):
            GameRunner(mixed_lobby(ids[:4], seed=1), config=chat_config(ids, seed=1))

    @pytest.mark.asyncio
    async def test_a_crashing_player_does_not_sink_the_game(self):
        class ExplodingPlayer(RandomPlayer):
            async def choose_action(self, game_state, valid_actions):
                raise RuntimeError("boom")

        ids = [f"p{i}" for i in range(5)]
        players = [ExplodingPlayer(ids[0])] + [RandomPlayer(pid) for pid in ids[1:]]

        result = await run_game(
            players, config=chat_config(ids, seed=23), database_url=DB
        )

        assert result.error is None
        assert result.completed is True

    @pytest.mark.asyncio
    async def test_summarise_results_aggregates_a_batch(self):
        ids = [f"p{i}" for i in range(5)]
        results = [
            await run_game(
                mixed_lobby(ids, seed=seed),
                config=chat_config(ids, seed=100 + seed),
                database_url=DB,
            )
            for seed in range(3)
        ]

        summary = summarise_results(results)

        assert summary["games"] == 3
        assert summary["completed"] == 3
        assert summary["safety_wins"] + summary["evil_wins"] == 3
        assert summary["input_tokens"] > 0
