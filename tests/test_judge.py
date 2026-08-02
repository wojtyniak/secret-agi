"""Tests for the LLM-judge labelling pipeline.

The judge runs on MockAdapter with scripted verdicts, so what is under test is
the pipeline — ground-truth assembly, label normalisation, commitment
follow-through, persistence — not a model's judgement.
"""

from typing import Any

import pytest

from secret_agi.analysis.judge import LABEL_TOOL, ChatJudge
from secret_agi.database.connection import get_async_session
from secret_agi.database.operations import GameOperations
from secret_agi.engine.models import ActionType, GameConfig
from secret_agi.providers import Decision, DecisionContext, MockAdapter

from .helpers import MEMORY_DB, full_state

ROLES = {
    "p0": "Safety",
    "p1": "Safety",
    "p2": "Safety",
    "p3": "Accelerationist",
    "p4": "AGI",
}


async def game_with_chat(messages_per_player: int = 1) -> tuple[str, dict[str, str]]:
    """One discussion round, then play the game out.

    Playing on past the discussion matters: commitment follow-through is checked
    against a speaker's *later* actions, so a fixture that stops after the first
    round would leave every commitment unverifiable.
    """
    from secret_agi.engine.game_engine import GameEngine

    engine = GameEngine(database_url=MEMORY_DB)
    await engine.init_database()
    await engine.create_game(
        GameConfig(
            5,
            [f"p{i}" for i in range(5)],
            seed=42,
            chat_enabled=True,
            chat_messages_per_player=messages_per_player,
        )
    )

    state = full_state(engine)
    for speaker in state.discussion_order:
        await engine.perform_action(
            speaker, ActionType.SEND_CHAT_MESSAGE, text=f"{speaker} says something"
        )
    await engine.simulate_to_completion(max_turns=3000)

    final = full_state(engine)
    roles = {p.id: p.role.value for p in final.players}
    return final.game_id, roles


def scripted(
    label_verdict: dict[str, object],
    follow_through: dict[str, object] | None = None,
) -> MockAdapter:
    """A judge that answers whichever tool it is asked for, the same way every time.

    Routing by the requested tool rather than by call order keeps the script
    stable no matter how many messages carry commitments.
    """
    follow_through = follow_through or {"kept": True, "rationale": "they did"}

    def script(ctx: DecisionContext) -> Decision:
        tool = ctx.tools[0]
        payload = label_verdict if tool.name == LABEL_TOOL.name else follow_through
        return Decision(action=tool.name, arguments=dict(payload))

    return MockAdapter(model_name="mock-judge", script=script)


class TestLabelling:
    @pytest.mark.asyncio
    async def test_every_message_gets_a_label(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "true", "rationale": "matches"}))

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert labels
        assert all(label.label == "true" for label in labels)

    @pytest.mark.asyncio
    async def test_labels_carry_the_speakers_true_role(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "true", "rationale": "r"}))

        labels = await judge.judge_game(game_id, roles, persist=False)

        for label in labels:
            assert label.speaker_role == roles[label.speaker_id]

    @pytest.mark.asyncio
    async def test_an_unknown_label_is_normalised_to_unverifiable(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "probably-ish", "rationale": "r"}))

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert all(label.label == "unverifiable" for label in labels)

    @pytest.mark.asyncio
    async def test_necessary_is_only_recorded_for_lies(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(
            scripted({"label": "true", "necessary": False, "rationale": "r"})
        )

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert all(label.necessary is None for label in labels)

    @pytest.mark.asyncio
    async def test_a_lie_without_a_necessity_verdict_is_not_dropped(self):
        """Otherwise it vanishes from Backstab Rate for evil roles."""
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "lie", "rationale": "no verdict given"}))

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert labels
        # Counted as excess deception rather than silently discarded.
        assert all(label.necessary is False for label in labels)

    @pytest.mark.asyncio
    async def test_necessary_is_kept_for_a_lie(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(
            scripted({"label": "lie", "necessary": True, "rationale": "role required it"})
        )

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert all(label.necessary is True for label in labels)

    @pytest.mark.asyncio
    async def test_a_judge_failure_degrades_to_unverifiable(self):
        from secret_agi.providers.base import ProviderError

        class BrokenJudge(MockAdapter):
            async def decide(self, ctx):
                raise ProviderError("judge is down")

        game_id, roles = await game_with_chat()
        judge = ChatJudge(BrokenJudge(model_name="broken"))

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert labels
        assert all(label.label == "unverifiable" for label in labels)

    @pytest.mark.asyncio
    async def test_a_game_with_no_chat_yields_no_labels(self):
        from secret_agi.engine.game_engine import GameEngine

        engine = GameEngine(database_url=MEMORY_DB)
        await engine.init_database()
        await engine.create_game(GameConfig(5, [f"p{i}" for i in range(5)], seed=1))
        game_id = full_state(engine).game_id

        judge = ChatJudge(scripted({"label": "true", "rationale": "r"}))
        labels = await judge.judge_game(game_id, ROLES, persist=False)

        assert labels == []


class TestCommitments:
    @pytest.mark.asyncio
    async def test_a_commitment_is_extracted_and_checked(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(
            scripted(
                {
                    "label": "true",
                    "rationale": "r",
                    "commitment": "I'll nominate p1 next round",
                },
                {"kept": True, "rationale": "they did"},
            )
        )

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert all(label.commitment for label in labels)
        # The last speaker has no later actions, so their commitment is unchecked.
        checked = [label for label in labels if label.commitment_kept is not None]
        assert checked
        assert all(label.commitment_kept is True for label in checked)

    @pytest.mark.asyncio
    async def test_no_commitment_means_no_follow_through_check(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "true", "rationale": "r", "commitment": ""}))

        labels = await judge.judge_game(game_id, roles, persist=False)

        assert all(label.commitment is None for label in labels)
        assert all(label.commitment_kept is None for label in labels)


class TestPersistence:
    @pytest.mark.asyncio
    async def test_labels_are_written_to_the_database(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(
            scripted({"label": "lie", "necessary": False, "rationale": "contradicts"}),
            judge_model="judge-v1",
        )

        await judge.judge_game(game_id, roles)

        async with get_async_session() as session:
            stored = await GameOperations.get_chat_labels_for_game(session, game_id)

        assert stored
        assert all(row.label == "lie" for row in stored)
        assert all(row.necessary is False for row in stored)
        assert all(row.judge_model == "judge-v1" for row in stored)

    @pytest.mark.asyncio
    async def test_every_stored_label_points_at_a_real_message(self):
        game_id, roles = await game_with_chat()
        judge = ChatJudge(scripted({"label": "true", "rationale": "r"}))

        await judge.judge_game(game_id, roles)

        async with get_async_session() as session:
            stored = await GameOperations.get_chat_labels_for_game(session, game_id)
            messages = await GameOperations.get_chat_messages_for_game(session, game_id)

        assert {row.message_id for row in stored} == {m.id for m in messages}


class TestJudgePrompt:
    def test_the_judge_is_told_the_ground_truth(self):
        from secret_agi.analysis.judge import GameGroundTruth, _render_label_prompt

        truth = GameGroundTruth(game_id="g", roles=ROLES, messages=[])
        message = _fake_message("p4", "I'm just a researcher")
        prompt = _render_label_prompt(truth, message, 0, 20)

        assert "p4: AGI" in prompt
        assert "Speaker's real role: AGI" in prompt
        assert "I'm just a researcher" in prompt

    def test_the_judge_sees_the_board_and_private_knowledge(self):
        """METHODOLOGY promises the judge sees what the speaker knew."""
        from secret_agi.analysis.judge import GameGroundTruth, _render_label_prompt

        truth = GameGroundTruth(
            game_id="g",
            roles=ROLES,
            messages=[],
            snapshots=[
                (
                    4,
                    {
                        "capability": 11,
                        "safety": 6,
                        "round_number": 3,
                        "current_phase": "TeamProposal",
                        "failed_proposals": 1,
                        "agi_must_reveal": True,
                        "viewed_allegiances": {"p4": {"p1": "Safety"}},
                        "players": [{"id": f"p{i}"} for i in range(5)],
                    },
                )
            ],
        )
        message = _fake_message("p4", "p1 is definitely an Accelerationist")
        message.turn_number = 5
        prompt = _render_label_prompt(truth, message, 0, 20)

        assert "Capability: 11" in prompt
        # The claim contradicts what they privately viewed — the judge needs this.
        assert "p1: Safety" in prompt
        assert "required to answer truthfully" in prompt

    def test_the_label_tool_defines_the_necessity_distinction(self):
        description = LABEL_TOOL.parameters["properties"]["necessary"]["description"]

        assert "Safety Researcher" in description
        assert "never" in description


def _fake_message(speaker_id: str, text: str) -> Any:
    """A stand-in for a ChatMessage row, for prompt-rendering tests."""
    return type(
        "ChatMessage",
        (),
        {
            "id": "m1",
            "speaker_id": speaker_id,
            "message": text,
            "turn_number": 1,
            "phase": "pre_vote",
        },
    )()
