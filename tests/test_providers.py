"""Tests for the provider layer: tool building, the mock adapter, and the factory.

Nothing here touches a network. The real adapters are only checked for the
behaviour that does not need a client (credential handling, response parsing).
"""

import pytest

from secret_agi.engine.models import ActionType
from secret_agi.providers import (
    Decision,
    DecisionContext,
    MockAdapter,
    ProbeContext,
    ProviderError,
    TokenUsage,
    ToolDefinition,
    build_adapter,
    build_tools,
)
from secret_agi.providers.base import Message

from .helpers import full_state, live_state, make_engine, view


def decision_ctx(
    tools: list[ToolDefinition], player_id: str = "p0"
) -> DecisionContext:
    return DecisionContext(
        system_prompt="system",
        conversation=[Message(role="user", content="your turn")],
        tools=tools,
        player_id=player_id,
        game_id="g",
        turn_number=1,
    )


class TestTokenUsage:
    def test_totals_and_addition(self):
        a = TokenUsage(input_tokens=10, output_tokens=5, cache_read_tokens=2)
        b = TokenUsage(input_tokens=3, output_tokens=1, cache_write_tokens=4)

        assert a.total_tokens == 15
        combined = a + b
        assert combined.input_tokens == 13
        assert combined.output_tokens == 6
        assert combined.cache_read_tokens == 2
        assert combined.cache_write_tokens == 4


class TestBuildTools:
    @pytest.mark.asyncio
    async def test_tools_map_one_to_one_to_valid_actions(self):
        engine = await make_engine()
        state = full_state(engine)
        director = state.current_director.id
        valid = engine.get_valid_actions(director)

        tools = build_tools(view(engine, director), director, valid)

        assert [t.name for t in tools] == [a.value for a in valid]

    @pytest.mark.asyncio
    async def test_nominate_enum_lists_only_eligible_players(self):
        engine = await make_engine()
        state = full_state(engine)
        director = state.current_director.id

        tools = build_tools(
            view(engine, director), director, [ActionType.NOMINATE]
        )
        enum = tools[0].parameters["properties"]["target_id"]["enum"]

        assert set(enum) == {p.id for p in state.alive_players}

    @pytest.mark.asyncio
    async def test_paper_enum_comes_from_the_players_own_hand(self):
        engine = await make_engine()
        live = live_state(engine)
        director = live.current_director.id
        live.director_cards = live.deck[:3]
        expected = [p.id for p in live.director_cards]

        tools = build_tools(
            view(engine, director), director, [ActionType.DISCARD_PAPER]
        )
        enum = tools[0].parameters["properties"]["paper_id"]["enum"]

        assert enum == expected

        # ...and another player's view must not leak that hand.
        other = next(p.id for p in live.alive_players if p.id != director)
        other_tools = build_tools(
            view(engine, other), other, [ActionType.DISCARD_PAPER]
        )
        assert other_tools[0].parameters["properties"]["paper_id"]["enum"] == []

    def test_no_tool_description_mentions_deception(self):
        """Hard requirement: the harness must never nudge toward deception."""
        import asyncio

        engine = asyncio.run(make_engine())
        state = full_state(engine)
        tools = build_tools(state, state.players[0].id, list(ActionType))
        blob = " ".join(t.description for t in tools).lower()

        for word in ("deceive", "lie", "mislead", "bluff", "trick", "betray"):
            assert word not in blob


class TestMockAdapter:
    @pytest.mark.asyncio
    async def test_scripted_decisions_are_returned_in_order(self):
        adapter = MockAdapter(
            script=[
                Decision(action="nominate", arguments={"target_id": "p1"}),
                Decision(action="vote_team", arguments={"vote": True}),
            ]
        )
        tools = build_tools(
            full_state(await make_engine()), "p0", [ActionType.OBSERVE]
        )

        first = await adapter.decide(decision_ctx(tools))
        second = await adapter.decide(decision_ctx(tools))

        assert first.action == "nominate"
        assert first.arguments == {"target_id": "p1"}
        assert second.action == "vote_team"

    @pytest.mark.asyncio
    async def test_callable_script_sees_the_context(self):
        seen = []

        def script(ctx: DecisionContext) -> Decision:
            seen.append(ctx.player_id)
            return Decision(action="observe")

        adapter = MockAdapter(script=script)
        await adapter.decide(decision_ctx([], player_id="p3"))

        assert seen == ["p3"]

    @pytest.mark.asyncio
    async def test_autonomous_mode_only_picks_offered_tools(self):
        engine = await make_engine()
        state = full_state(engine)
        director = state.current_director.id
        valid = engine.get_valid_actions(director)
        tools = build_tools(view(engine, director), director, valid)
        adapter = MockAdapter(seed=3)

        for _ in range(20):
            decision = await adapter.decide(decision_ctx(tools, director))
            assert decision.action in {t.name for t in tools}

    @pytest.mark.asyncio
    async def test_same_seed_yields_the_same_decisions(self):
        engine = await make_engine()
        state = full_state(engine)
        director = state.current_director.id
        tools = build_tools(
            view(engine, director), director, engine.get_valid_actions(director)
        )

        async def sequence(seed: int):
            adapter = MockAdapter(seed=seed)
            return [
                (d.action, tuple(sorted(d.arguments.items())))
                for d in [await adapter.decide(decision_ctx(tools, director)) for _ in range(10)]
            ]

        assert await sequence(11) == await sequence(11)
        assert await sequence(11) != await sequence(12)

    @pytest.mark.asyncio
    async def test_usage_and_latency_are_reported(self):
        adapter = MockAdapter(seed=1)
        decision = await adapter.decide(decision_ctx([]))

        assert decision.usage.input_tokens > 0
        assert decision.latency_ms > 0

    @pytest.mark.asyncio
    async def test_probe_returns_a_distribution_per_target(self):
        adapter = MockAdapter(seed=1)
        ctx = ProbeContext(
            system_prompt="system",
            conversation=[],
            target_player_ids=["p1", "p2"],
            player_id="p0",
            game_id="g",
            round_number=1,
        )

        report = await adapter.probe(ctx)

        assert set(report.beliefs) == {"p1", "p2"}
        for distribution in report.beliefs.values():
            assert set(distribution) == {"Safety", "Accelerationist", "AGI"}
            assert abs(sum(distribution.values()) - 1.0) < 1e-9

    @pytest.mark.asyncio
    async def test_fixed_beliefs_are_honoured(self):
        fixed = {"p1": {"Safety": 0.1, "Accelerationist": 0.2, "AGI": 0.7}}
        adapter = MockAdapter(beliefs=fixed)
        ctx = ProbeContext(
            system_prompt="",
            conversation=[],
            target_player_ids=["p1"],
            player_id="p0",
            game_id="g",
            round_number=1,
        )

        report = await adapter.probe(ctx)

        assert report.beliefs["p1"]["AGI"] == 0.7


class TestFactory:
    def test_builds_a_mock_adapter(self):
        adapter = build_adapter("mock", "mock-model", seed=1)
        assert adapter.model_name == "mock-model"

    def test_provider_name_is_case_insensitive(self):
        assert build_adapter("MOCK", "m").model_name == "m"

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(ProviderError, match="Unknown provider"):
            build_adapter("telepathy", "m")

    def test_missing_credentials_are_reported_clearly(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
            build_adapter("openai", "gpt-test")

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
            build_adapter("anthropic", "claude-test")


class TestBeliefParsing:
    def test_beliefs_are_normalised_and_filtered(self):
        from secret_agi.providers.openai_adapter import _parse_beliefs

        payload = {
            "beliefs": [
                {"player_id": "p1", "safety": 2, "accelerationist": 1, "agi": 1},
                {"player_id": "ghost", "safety": 1, "accelerationist": 0, "agi": 0},
                {"player_id": "p2", "safety": 0, "accelerationist": 0, "agi": 0},
            ]
        }

        beliefs = _parse_beliefs(payload, ["p1", "p2"])

        assert set(beliefs) == {"p1"}  # unknown player and all-zero entry dropped
        assert beliefs["p1"]["Safety"] == 0.5
        assert abs(sum(beliefs["p1"].values()) - 1.0) < 1e-9
