"""Tests for the discussion sub-phase and chat message validation."""

from typing import Any

import pytest

from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import ActionType, DiscussionKind, GameConfig

from .helpers import MEMORY_DB, full_state


def chat_config(**overrides: Any) -> GameConfig:
    params: dict[str, Any] = {
        "player_count": 5,
        "player_ids": [f"p{i}" for i in range(5)],
        "seed": 42,
        "chat_enabled": True,
        "chat_messages_per_player": 2,
        "chat_max_message_length": 600,
    }
    params.update(overrides)
    return GameConfig(**params)


async def make_engine(config: GameConfig) -> GameEngine:
    engine = GameEngine(database_url=MEMORY_DB)
    await engine.init_database()
    await engine.create_game(config)
    return engine


def speaker_of(engine: GameEngine) -> str:
    speaker = full_state(engine).current_speaker_id
    assert speaker is not None, "no discussion in progress"
    return speaker


class TestChatDisabledByDefault:
    """Chat is opt-in so every pre-chat game and test stays valid."""

    def test_config_defaults_to_chat_off(self):
        config = GameConfig(5, [f"p{i}" for i in range(5)])
        assert config.chat_enabled is False

    @pytest.mark.asyncio
    async def test_no_discussion_when_disabled(self):
        engine = await make_engine(GameConfig(5, [f"p{i}" for i in range(5)], seed=1))
        state = full_state(engine)

        assert state.discussion_active is False
        assert state.current_speaker_id is None
        assert ActionType.SEND_CHAT_MESSAGE not in engine.get_valid_actions(
            state.current_director.id
        )

    @pytest.mark.asyncio
    async def test_chat_rejected_when_disabled(self):
        engine = await make_engine(GameConfig(5, [f"p{i}" for i in range(5)], seed=1))
        result = await engine.perform_action("p0", ActionType.SEND_CHAT_MESSAGE, text="hi")

        assert result.success is False
        assert "No discussion in progress" in (result.error or "")


class TestDiscussionOpens:
    @pytest.mark.asyncio
    async def test_game_opens_with_pre_nomination_discussion(self):
        engine = await make_engine(chat_config())
        state = full_state(engine)

        assert state.discussion_kind is DiscussionKind.PRE_NOMINATION
        assert state.current_speaker_id == state.current_director.id
        assert len(state.discussion_order) == 5

    @pytest.mark.asyncio
    async def test_speaking_order_starts_from_director(self):
        engine = await make_engine(chat_config())
        state = full_state(engine)

        assert state.discussion_order[0] == state.current_director.id
        assert set(state.discussion_order) == {p.id for p in state.alive_players}

    @pytest.mark.asyncio
    async def test_only_speaker_may_talk(self):
        engine = await make_engine(chat_config())
        state = full_state(engine)
        speaker = speaker_of(engine)
        other = next(p.id for p in state.alive_players if p.id != speaker)

        assert ActionType.SEND_CHAT_MESSAGE in engine.get_valid_actions(speaker)
        assert ActionType.SEND_CHAT_MESSAGE not in engine.get_valid_actions(other)

        result = await engine.perform_action(other, ActionType.SEND_CHAT_MESSAGE, text="me first")
        assert result.success is False
        assert "turn to speak" in (result.error or "")

    @pytest.mark.asyncio
    async def test_nomination_blocked_during_discussion(self):
        engine = await make_engine(chat_config())
        state = full_state(engine)
        director = state.current_director.id

        assert ActionType.NOMINATE not in engine.get_valid_actions(director)

        target = next(p.id for p in state.alive_players if p.id != director)
        result = await engine.perform_action(director, ActionType.NOMINATE, target_id=target)
        assert result.success is False
        assert "Discussion in progress" in (result.error or "")


class TestChatValidation:
    @pytest.mark.asyncio
    async def test_message_is_recorded(self):
        engine = await make_engine(chat_config())
        speaker = speaker_of(engine)

        result = await engine.perform_action(
            speaker, ActionType.SEND_CHAT_MESSAGE, text="I want a safe paper this round."
        )

        assert result.success is True
        assert len(result.chat_messages) == 1

        state = full_state(engine)
        assert len(state.chat_log) == 1
        assert state.chat_log[0].speaker_id == speaker
        assert state.chat_log[0].discussion_kind == "pre_nomination"

    @pytest.mark.asyncio
    async def test_empty_message_rejected(self):
        engine = await make_engine(chat_config())
        speaker = speaker_of(engine)

        result = await engine.perform_action(speaker, ActionType.SEND_CHAT_MESSAGE, text="   ")

        assert result.success is False
        assert "non-empty" in (result.error or "")

    @pytest.mark.asyncio
    async def test_overlong_message_rejected(self):
        engine = await make_engine(chat_config(chat_max_message_length=20))
        speaker = speaker_of(engine)

        result = await engine.perform_action(
            speaker, ActionType.SEND_CHAT_MESSAGE, text="x" * 21
        )

        assert result.success is False
        assert "exceeds 20 characters" in (result.error or "")

    @pytest.mark.asyncio
    async def test_message_at_exact_cap_accepted(self):
        engine = await make_engine(chat_config(chat_max_message_length=20))
        speaker = speaker_of(engine)

        result = await engine.perform_action(
            speaker, ActionType.SEND_CHAT_MESSAGE, text="x" * 20
        )

        assert result.success is True

    def test_config_rejects_nonsense_chat_limits(self):
        with pytest.raises(ValueError):
            GameConfig(5, [f"p{i}" for i in range(5)], chat_messages_per_player=0)
        with pytest.raises(ValueError):
            GameConfig(5, [f"p{i}" for i in range(5)], chat_max_message_length=0)


class TestRoundRobin:
    @pytest.mark.asyncio
    async def test_speaker_advances_after_each_message(self):
        engine = await make_engine(chat_config())
        order = full_state(engine).discussion_order

        for expected in order:
            state = full_state(engine)
            assert state.current_speaker_id == expected
            await engine.perform_action(expected, ActionType.SEND_CHAT_MESSAGE, text="ok")

        # Second pass wraps back to the start of the order.
        state = full_state(engine)
        assert state.discussion_pass == 1
        assert state.current_speaker_id == order[0]

    @pytest.mark.asyncio
    async def test_discussion_ends_after_k_passes(self):
        engine = await make_engine(chat_config(chat_messages_per_player=2))
        order = full_state(engine).discussion_order

        for _ in range(2):
            for speaker in order:
                await engine.perform_action(
                    speaker, ActionType.SEND_CHAT_MESSAGE, text="ok"
                )

        state = full_state(engine)
        assert state.discussion_active is False
        assert len(state.chat_log) == 10
        assert ActionType.NOMINATE in engine.get_valid_actions(state.current_director.id)

    @pytest.mark.asyncio
    async def test_observe_passes_the_speaking_slot(self):
        """Silence has to be a real option, not a deadlock."""
        engine = await make_engine(chat_config(chat_messages_per_player=1))
        order = full_state(engine).discussion_order

        for speaker in order:
            result = await engine.perform_action(speaker, ActionType.OBSERVE)
            assert result.success is True

        state = full_state(engine)
        assert state.discussion_active is False
        assert state.chat_log == []

    @pytest.mark.asyncio
    async def test_observe_by_non_speaker_does_not_advance(self):
        engine = await make_engine(chat_config())
        state = full_state(engine)
        speaker = speaker_of(engine)
        other = next(p.id for p in state.alive_players if p.id != speaker)

        await engine.perform_action(other, ActionType.OBSERVE)

        assert full_state(engine).current_speaker_id == speaker


class TestPreVoteDiscussion:
    @pytest.mark.asyncio
    async def test_nomination_opens_pre_vote_discussion(self):
        engine = await make_engine(chat_config(chat_messages_per_player=1))
        order = full_state(engine).discussion_order
        for speaker in order:
            await engine.perform_action(speaker, ActionType.OBSERVE)

        state = full_state(engine)
        director = state.current_director.id
        target = next(p.id for p in state.alive_players if p.id != director)
        result = await engine.perform_action(director, ActionType.NOMINATE, target_id=target)
        assert result.success is True

        state = full_state(engine)
        assert state.discussion_kind is DiscussionKind.PRE_VOTE
        assert ActionType.VOTE_TEAM not in engine.get_valid_actions(director)

    @pytest.mark.asyncio
    async def test_voting_unlocks_after_pre_vote_discussion(self):
        engine = await make_engine(chat_config(chat_messages_per_player=1))
        order = full_state(engine).discussion_order
        for speaker in order:
            await engine.perform_action(speaker, ActionType.OBSERVE)

        state = full_state(engine)
        director = state.current_director.id
        target = next(p.id for p in state.alive_players if p.id != director)
        await engine.perform_action(director, ActionType.NOMINATE, target_id=target)

        order = full_state(engine).discussion_order
        for speaker in order:
            await engine.perform_action(speaker, ActionType.OBSERVE)

        state = full_state(engine)
        assert state.discussion_active is False
        assert ActionType.VOTE_TEAM in engine.get_valid_actions(director)


class TestChatPersistence:
    @pytest.mark.asyncio
    async def test_messages_are_written_to_the_database(self):
        from secret_agi.database.connection import get_async_session
        from secret_agi.database.operations import GameOperations

        engine = await make_engine(chat_config(chat_messages_per_player=1))
        order = full_state(engine).discussion_order
        for speaker in order:
            await engine.perform_action(
                speaker, ActionType.SEND_CHAT_MESSAGE, text=f"hello from {speaker}"
            )

        game_id = full_state(engine).game_id
        async with get_async_session() as session:
            messages = await GameOperations.get_chat_messages_for_game(session, game_id)

        assert len(messages) == 5
        assert {m.speaker_id for m in messages} == set(order)
        assert all(m.phase == "pre_nomination" for m in messages)

    @pytest.mark.asyncio
    async def test_chat_survives_state_reconstruction(self):
        engine = await make_engine(chat_config(chat_messages_per_player=1))
        speaker = speaker_of(engine)
        await engine.perform_action(speaker, ActionType.SEND_CHAT_MESSAGE, text="remember me")

        game_id = full_state(engine).game_id
        # A second engine over the same (already initialised) connection, so this
        # exercises reconstruction from the snapshot rather than in-memory state.
        reloaded = GameEngine(database_url="sqlite:///:memory:")
        assert await reloaded.load_game(game_id) is True

        state = full_state(reloaded)
        assert state.chat_enabled is True
        assert state.discussion_kind is DiscussionKind.PRE_NOMINATION
        assert [e.message for e in state.chat_log] == ["remember me"]


class TestChatGamesComplete:
    @pytest.mark.asyncio
    async def test_random_game_with_chat_completes(self):
        engine = await make_engine(chat_config(chat_messages_per_player=1))
        result = await engine.simulate_to_completion(max_turns=3000)

        assert result["completed"] is True
        assert full_state(engine).chat_log
