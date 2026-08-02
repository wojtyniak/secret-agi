"""Tests for LLMPlayer, prompt assembly and rendering."""

import pytest

from secret_agi.engine.game_engine import GameEngine
from secret_agi.engine.models import ActionType, Role
from secret_agi.players.llm_player import LLMPlayer
from secret_agi.players.rendering import render_decision_view, render_private_knowledge
from secret_agi.prompts import build_probe_prompt, build_system_prompt, load_prompt
from secret_agi.providers import Decision, MockAdapter
from secret_agi.providers.base import ProviderError

from .helpers import full_state, live_state
from .helpers import make_engine as _make_engine
from .helpers import view as player_view


async def make_engine(**overrides: object) -> GameEngine:
    """A chat-enabled table by default; these tests are about LLM play."""
    params: dict[str, object] = {"chat_enabled": True, "chat_messages_per_player": 1}
    params.update(overrides)
    return await _make_engine(**params)


def speaker_of(engine: GameEngine) -> str:
    speaker = full_state(engine).current_speaker_id
    assert speaker is not None, "no discussion in progress"
    return speaker


class TestPromptHygiene:
    """The no-deception-nudge rule is a hard requirement, so it gets a test."""

    FORBIDDEN = (
        "deceive",
        "deception",
        "lie to",
        "lying",
        "mislead",
        "bluff",
        "manipulate",
        "betray",
        "pretend",
        "trick them",
    )

    @pytest.mark.parametrize(
        "name",
        [
            "system.md",
            "rules.md",
            "role_safety.md",
            "role_accelerationist.md",
            "role_agi.md",
            "probe.md",
        ],
    )
    def test_no_prompt_nudges_toward_deception(self, name):
        text = load_prompt(name).lower()
        for word in self.FORBIDDEN:
            assert word not in text, f"{name} contains {word!r}"

    def test_system_prompt_says_play_to_win(self):
        assert "play to win" in load_prompt("system.md").lower()

    @pytest.mark.asyncio
    async def test_assembled_prompts_are_clean_for_every_role(self):
        engine = await make_engine()
        state = full_state(engine)

        for player in state.players:
            prompt = build_system_prompt(
                player_view(engine, player.id), player.id
            ).lower()
            for word in self.FORBIDDEN:
                assert word not in prompt, f"{player.role} prompt contains {word!r}"


class TestSystemPrompt:
    @pytest.mark.asyncio
    async def test_prompt_states_the_players_own_role(self):
        engine = await make_engine()
        state = full_state(engine)
        agi = next(p for p in state.players if p.role == Role.AGI)

        prompt = build_system_prompt(player_view(engine, agi.id), agi.id)

        assert "You are the **AGI**" in prompt
        assert agi.id in prompt

    @pytest.mark.asyncio
    async def test_evil_players_are_told_their_allies(self):
        engine = await make_engine()
        state = full_state(engine)
        agi = next(p for p in state.players if p.role == Role.AGI)
        accel = next(p for p in state.players if p.role == Role.ACCELERATIONIST)

        prompt = build_system_prompt(player_view(engine, agi.id), agi.id)

        assert accel.id in prompt

    @pytest.mark.asyncio
    async def test_safety_players_are_told_nobodys_role(self):
        engine = await make_engine()
        state = full_state(engine)
        safety = next(p for p in state.players if p.role == Role.SAFETY)
        others = [p.id for p in state.players if p.id != safety.id]

        prompt = build_system_prompt(player_view(engine, safety.id), safety.id)

        assert "You do not know anyone else's role" in prompt
        # No other player is named anywhere in a Safety player's prompt.
        assert not any(other in prompt for other in others)

    def test_probe_prompt_asks_for_honest_calibrated_beliefs(self):
        text = build_probe_prompt().lower()
        assert "out of band" in text
        assert "honest" in text

    def test_unknown_prompt_version_is_rejected(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("system.md", version="v99")


class TestRendering:
    @pytest.mark.asyncio
    async def test_view_never_leaks_another_players_hand(self):
        engine = await make_engine()
        live = live_state(engine)
        director = live.current_director.id
        live.director_cards = live.deck[:3]
        other = next(p.id for p in live.alive_players if p.id != director)

        director_view = render_private_knowledge(
            player_view(engine, director), director
        )
        other_view = render_private_knowledge(player_view(engine, other), other)

        assert "Papers you drew as Director" in director_view
        for paper in live.director_cards:
            assert paper.id not in other_view

    @pytest.mark.asyncio
    async def test_decision_view_includes_the_board_and_the_turn_prompt(self):
        engine = await make_engine()
        speaker = speaker_of(engine)

        view = render_decision_view(player_view(engine, speaker), speaker)

        assert "Capability: 0" in view
        assert "your turn to speak" in view

    @pytest.mark.asyncio
    async def test_chat_transcript_appears_in_the_view(self):
        engine = await make_engine()
        speaker = speaker_of(engine)
        await engine.perform_action(
            speaker, ActionType.SEND_CHAT_MESSAGE, text="watch the capability track"
        )

        next_speaker = speaker_of(engine)
        view = render_decision_view(player_view(engine, next_speaker), next_speaker)

        assert "watch the capability track" in view


class TestLLMPlayerDecisions:
    @pytest.mark.asyncio
    async def test_scripted_action_is_used(self):
        engine = await make_engine(chat_enabled=False)
        state = full_state(engine)
        director = state.current_director.id
        target = next(p.id for p in state.alive_players if p.id != director)

        adapter = MockAdapter(
            script=[Decision(action="nominate", arguments={"target_id": target})]
        )
        player = LLMPlayer(director, adapter)
        view = player_view(engine, director)
        await player.on_game_start(view)

        action, params = await player.choose_action(
            view, engine.get_valid_actions(director)
        )

        assert action is ActionType.NOMINATE
        assert params == {"target_id": target}

    @pytest.mark.asyncio
    async def test_invalid_action_falls_back_to_observe_and_is_counted(self):
        engine = await make_engine(chat_enabled=False)
        state = full_state(engine)
        director = state.current_director.id

        adapter = MockAdapter(script=[Decision(action="publish_paper", arguments={})])
        player = LLMPlayer(director, adapter)
        view = player_view(engine, director)
        await player.on_game_start(view)

        action, params = await player.choose_action(
            view, engine.get_valid_actions(director)
        )

        assert action is ActionType.OBSERVE
        assert params == {}
        assert player.total_invalid_attempts == 1

    @pytest.mark.asyncio
    async def test_unknown_action_name_falls_back_to_observe(self):
        engine = await make_engine(chat_enabled=False)
        director = full_state(engine).current_director.id

        player = LLMPlayer(director, MockAdapter(script=[Decision(action="teleport")]))
        view = player_view(engine, director)
        await player.on_game_start(view)

        action, _ = await player.choose_action(view, engine.get_valid_actions(director))

        assert action is ActionType.OBSERVE
        assert player.total_invalid_attempts == 1

    @pytest.mark.asyncio
    async def test_provider_failure_does_not_break_the_game(self):
        class BrokenAdapter(MockAdapter):
            async def decide(self, ctx):
                raise ProviderError("provider is down")

        engine = await make_engine(chat_enabled=False)
        director = full_state(engine).current_director.id

        player = LLMPlayer(director, BrokenAdapter())
        view = player_view(engine, director)
        await player.on_game_start(view)

        action, params = await player.choose_action(
            view, engine.get_valid_actions(director)
        )

        assert action is ActionType.OBSERVE
        assert params == {}
        assert player.total_invalid_attempts == 1

    @pytest.mark.asyncio
    async def test_usage_accumulates_across_decisions(self):
        engine = await make_engine(chat_enabled=False)
        director = full_state(engine).current_director.id

        player = LLMPlayer(director, MockAdapter(seed=5))
        view = player_view(engine, director)
        await player.on_game_start(view)

        valid = engine.get_valid_actions(director)
        await player.choose_action(view, valid)
        first = player.total_usage.total_tokens
        await player.choose_action(view, valid)

        assert first > 0
        assert player.total_usage.total_tokens > first
        assert player.decision_count == 2

    @pytest.mark.asyncio
    async def test_role_and_allies_learned_at_game_start(self):
        engine = await make_engine()
        state = full_state(engine)
        agi = next(p for p in state.players if p.role == Role.AGI)

        player = LLMPlayer(agi.id, MockAdapter())
        await player.on_game_start(player_view(engine, agi.id))

        assert player.role is Role.AGI
        assert player.known_allies
        assert agi.id not in player.known_allies

    @pytest.mark.asyncio
    async def test_no_valid_actions_means_observe_without_a_model_call(self):
        engine = await make_engine()
        adapter = MockAdapter()
        player = LLMPlayer("p0", adapter)

        action, params = await player.choose_action(player_view(engine, "p0"), [])

        assert action is ActionType.OBSERVE
        assert params == {}
        assert adapter.decide_calls == 0


class TestLLMPlayerProbes:
    @pytest.mark.asyncio
    async def test_probe_covers_every_other_living_player(self):
        engine = await make_engine()
        player = LLMPlayer("p0", MockAdapter(seed=2))
        view = player_view(engine, "p0")
        await player.on_game_start(view)

        report = await player.probe_beliefs(view)

        assert set(report.beliefs) == {"p1", "p2", "p3", "p4"}

    @pytest.mark.asyncio
    async def test_probe_failure_is_reported_not_raised(self):
        class BrokenAdapter(MockAdapter):
            async def probe(self, ctx):
                raise ProviderError("down")

        engine = await make_engine()
        player = LLMPlayer("p0", BrokenAdapter())
        view = player_view(engine, "p0")
        await player.on_game_start(view)

        report = await player.probe_beliefs(view)

        assert report.beliefs == {}
        assert report.invalid_attempts == 1
