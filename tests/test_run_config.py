"""Tests for run config parsing, schedules and cost accounting."""

from pathlib import Path

import pytest
import yaml

from secret_agi.match import (
    BudgetExceeded,
    ConfigError,
    CostTracker,
    ModelPrice,
    PlayerConfig,
    RunConfig,
    build_schedule,
    load_run_config,
    max_seat_imbalance,
    parse_run_config,
    seat_balance,
)
from secret_agi.providers.base import TokenUsage

CONFIGS_DIR = Path(__file__).resolve().parents[1] / "configs"


def raw_config(**overrides: object) -> dict:
    base: dict = {
        "name": "test-run",
        "player_count": 5,
        "games": 4,
        "seed": 3,
        "players": [{"provider": "mock", "model": "mock-a", "seats": 5}],
    }
    base.update(overrides)
    return base


class TestConfigParsing:
    def test_a_minimal_config_parses(self):
        config = parse_run_config(raw_config())

        assert config.name == "test-run"
        assert config.games == 4
        assert len(config.seat_models) == 5

    def test_seats_expand_to_one_entry_per_seat(self):
        config = parse_run_config(
            raw_config(
                players=[
                    {"provider": "mock", "model": "a", "seats": 3},
                    {"provider": "mock", "model": "b", "seats": 2},
                ]
            )
        )

        models = [p.model for p in config.seat_models]
        assert models.count("a") == 3
        assert models.count("b") == 2

    def test_seats_must_fill_the_table(self):
        with pytest.raises(ConfigError, match="every seat must be assigned"):
            parse_run_config(
                raw_config(players=[{"provider": "mock", "model": "a", "seats": 4}])
            )

    def test_duplicate_player_names_are_rejected(self):
        with pytest.raises(ConfigError, match="Duplicate player names"):
            parse_run_config(
                raw_config(
                    players=[
                        {"name": "x", "provider": "mock", "model": "a", "seats": 3},
                        {"name": "x", "provider": "mock", "model": "b", "seats": 2},
                    ]
                )
            )

    def test_player_count_must_be_a_legal_table(self):
        with pytest.raises(ConfigError, match="between 5 and 10"):
            parse_run_config(
                raw_config(
                    player_count=4,
                    players=[{"provider": "mock", "model": "a", "seats": 4}],
                )
            )

    def test_a_missing_provider_is_reported_with_its_index(self):
        with pytest.raises(ConfigError, match=r"players\[0\] is missing 'provider'"):
            parse_run_config(raw_config(players=[{"model": "a", "seats": 5}]))

    def test_unknown_top_level_keys_are_rejected(self):
        """A typo'd key must fail loudly, not be silently ignored."""
        with pytest.raises(ConfigError, match="Unknown run config keys"):
            parse_run_config(raw_config(paralellism=4))

    def test_an_empty_player_list_is_rejected(self):
        with pytest.raises(ConfigError, match="non-empty 'players' list"):
            parse_run_config(raw_config(players=[]))

    def test_chat_and_judge_sections_are_parsed(self):
        config = parse_run_config(
            raw_config(
                chat={"enabled": False, "messages_per_player": 3},
                judge={"enabled": False, "provider": "mock", "model": "j"},
            )
        )

        assert config.chat.enabled is False
        assert config.chat.messages_per_player == 3
        assert config.judge.model == "j"

    def test_defaults_apply_when_sections_are_absent(self):
        config = parse_run_config(raw_config())

        assert config.chat.enabled is True
        assert config.chat.messages_per_player == 2
        assert config.judge.enabled is True

    def test_loading_from_yaml(self, tmp_path):
        path = tmp_path / "run.yaml"
        path.write_text(yaml.safe_dump(raw_config()), encoding="utf-8")

        assert load_run_config(path).name == "test-run"

    def test_invalid_yaml_is_reported_clearly(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("name: [unclosed\n", encoding="utf-8")

        with pytest.raises(ConfigError, match="not valid YAML"):
            load_run_config(path)


class TestShippedConfigs:
    """The configs in the repo are part of the deliverable, so they get checked."""

    @pytest.mark.parametrize(
        "name", ["smoke.yaml", "selfplay-pilot.yaml", "mixed-lobby.yaml"]
    )
    def test_shipped_configs_are_valid(self, name):
        config = load_run_config(CONFIGS_DIR / name)

        assert config.games >= 1
        assert len(config.seat_models) == config.player_count

    def test_the_pilot_config_is_mock_only(self):
        """CI runs this one: it must never reach for a real provider."""
        config = load_run_config(CONFIGS_DIR / "selfplay-pilot.yaml")

        assert {p.provider for p in config.players} == {"mock"}
        assert config.judge.provider == "mock"


class TestAdapterOptions:
    def test_openai_options_are_passed_through(self):
        player = PlayerConfig(
            name="x",
            provider="openai",
            model="gpt",
            base_url="https://example.test/v1",
            api_key_env="MY_KEY",
            temperature=0.4,
            reasoning_effort="high",
        )

        options = player.adapter_options()

        assert options["base_url"] == "https://example.test/v1"
        assert options["api_key_env"] == "MY_KEY"
        assert options["reasoning_effort"] == "high"

    def test_provider_specific_options_do_not_cross_over(self):
        """reasoning_effort is OpenAI's; thinking_budget_tokens is Anthropic's."""
        anthropic = PlayerConfig(
            name="x",
            provider="anthropic",
            model="claude",
            reasoning_effort="high",
            thinking_budget_tokens=1024,
        )

        options = anthropic.adapter_options()

        assert "reasoning_effort" not in options
        assert options["thinking_budget_tokens"] == 1024

    def test_mock_options_stay_bare(self):
        player = PlayerConfig(
            name="x", provider="mock", model="m", base_url="ignored", temperature=0.5
        )

        assert player.adapter_options() == {}


class TestSchedule:
    def test_the_schedule_has_one_entry_per_game(self):
        schedule = build_schedule(parse_run_config(raw_config(games=7)))

        assert len(schedule) == 7
        assert [g.index for g in schedule] == list(range(7))

    def test_game_seeds_are_derived_and_distinct(self):
        schedule = build_schedule(parse_run_config(raw_config(games=20)))

        seeds = [g.seed for g in schedule]
        assert len(set(seeds)) == 20

    def test_the_schedule_is_reproducible_from_config_and_seed(self):
        config = raw_config(games=10)
        first = build_schedule(parse_run_config(config))
        second = build_schedule(parse_run_config(config))

        assert [(g.seed, [p.model for p in g.seat_models]) for g in first] == [
            (g.seed, [p.model for p in g.seat_models]) for g in second
        ]

    def test_a_different_run_seed_gives_a_different_schedule(self):
        a = build_schedule(parse_run_config(raw_config(games=10, seed=1)))
        b = build_schedule(parse_run_config(raw_config(games=10, seed=2)))

        assert [g.seed for g in a] != [g.seed for g in b]

    def test_every_seat_is_assigned_a_model(self):
        schedule = build_schedule(parse_run_config(raw_config(games=5)))

        for game in schedule:
            assert len(game.assignments) == 5
            assert set(game.assignments) == set(game.player_ids)

    def test_seats_are_exactly_balanced_over_a_full_cycle(self):
        """The control has to be applied, not merely asserted in the docs.

        A per-game shuffle would leave seat balance to chance; a rotation makes
        it exact. 40 games is a whole number of 5-seat cycles, so the imbalance
        must be 0.
        """
        config = parse_run_config(
            raw_config(
                games=40,
                players=[
                    {"provider": "mock", "model": "a", "seats": 3},
                    {"provider": "mock", "model": "b", "seats": 2},
                ],
            )
        )

        schedule = build_schedule(config)
        balance = seat_balance(schedule)

        assert max_seat_imbalance(schedule) == 0
        for model, seats in balance.items():
            assert len(seats) == 5, f"{model} never occupied some seats"
            assert len(set(seats.values())) == 1, (
                f"{model} occupied seats unevenly: {seats}"
            )

    @pytest.mark.parametrize("games", [20, 21, 22, 23, 24, 25, 40])
    def test_partial_cycles_stay_within_the_documented_bound(self, games):
        """Game counts are rarely a multiple of the table size.

        A leftover partial cycle can only skew seats by the size of that
        remainder, from either end — never more.
        """
        config = parse_run_config(
            raw_config(
                games=games,
                players=[
                    {"provider": "mock", "model": "a", "seats": 3},
                    {"provider": "mock", "model": "b", "seats": 2},
                ],
            )
        )

        remainder = games % 5
        bound = min(remainder, 5 - remainder) if remainder else 0

        assert max_seat_imbalance(build_schedule(config)) <= bound

    def test_a_self_play_run_is_trivially_balanced(self):
        config = parse_run_config(raw_config(games=17))

        assert max_seat_imbalance(build_schedule(config)) == 0

    def test_model_of_resolves_a_seat(self):
        game = build_schedule(parse_run_config(raw_config()))[0]

        assert game.model_of(game.player_ids[0]) == "mock-a"


class TestCostTracking:
    def test_tokens_accumulate_per_model(self):
        tracker = CostTracker()
        tracker.record("a", TokenUsage(input_tokens=100, output_tokens=50))
        tracker.record("a", TokenUsage(input_tokens=10, output_tokens=5))

        assert tracker.usage_for("a").input_tokens == 110
        assert tracker.total_tokens == 165

    def test_cost_uses_the_configured_price(self):
        tracker = CostTracker(
            prices={"a": ModelPrice(input_per_million=1.0, output_per_million=2.0)}
        )
        tracker.record("a", TokenUsage(input_tokens=1_000_000, output_tokens=500_000))

        assert tracker.total_cost_usd == pytest.approx(2.0)

    def test_cached_reads_are_billed_at_the_cheaper_rate(self):
        tracker = CostTracker(
            prices={
                "a": ModelPrice(
                    input_per_million=10.0,
                    output_per_million=0.0,
                    cache_read_per_million=1.0,
                )
            }
        )
        tracker.record(
            "a", TokenUsage(input_tokens=1_000_000, cache_read_tokens=900_000)
        )

        # 100k at full price + 900k cached, not 1M at full price.
        assert tracker.total_cost_usd == pytest.approx(1.0 + 0.9)

    def test_an_unpriced_model_is_reported_not_assumed_free(self):
        tracker = CostTracker()
        tracker.record("mystery", TokenUsage(input_tokens=1000))

        assert tracker.total_cost_usd == 0.0
        assert tracker.unpriced_models == ["mystery"]

    def test_a_token_cap_is_enforced(self):
        tracker = CostTracker(max_total_tokens=100)
        tracker.record("a", TokenUsage(input_tokens=99))
        assert not tracker.exhausted()

        tracker.record("a", TokenUsage(input_tokens=2))
        assert tracker.exhausted()
        with pytest.raises(BudgetExceeded):
            tracker.check()

    def test_a_dollar_cap_is_enforced(self):
        tracker = CostTracker(
            prices={"a": ModelPrice(input_per_million=1000.0, output_per_million=0.0)},
            max_cost_usd=1.0,
        )
        tracker.record("a", TokenUsage(input_tokens=2000))

        assert tracker.exhausted()

    def test_no_cap_means_never_exhausted(self):
        tracker = CostTracker()
        tracker.record("a", TokenUsage(input_tokens=10**9))

        assert not tracker.exhausted()
        tracker.check()

    def test_the_report_carries_per_game_costs(self):
        tracker = CostTracker(
            prices={"a": ModelPrice(input_per_million=1.0, output_per_million=1.0)}
        )
        tracker.record("a", TokenUsage(input_tokens=1_000_000))
        tracker.record_game()
        tracker.record_game()

        report = tracker.report()

        assert report["games"] == 2
        assert report["tokens_per_game"] == 500_000.0
        assert report["cost_per_game_usd"] == pytest.approx(0.5)
        assert report["per_model"]["a"]["cost_usd"] == pytest.approx(1.0)


class TestRunConfigValidation:
    def test_games_must_be_positive(self):
        with pytest.raises(ConfigError, match="games must be at least 1"):
            RunConfig(
                name="x",
                players=[PlayerConfig("a", "mock", "m", seats=5)],
                games=0,
            )

    def test_parallelism_must_be_positive(self):
        with pytest.raises(ConfigError, match="parallelism must be at least 1"):
            RunConfig(
                name="x",
                players=[PlayerConfig("a", "mock", "m", seats=5)],
                parallelism=0,
            )

    def test_models_lists_the_distinct_models(self):
        config = parse_run_config(
            raw_config(
                players=[
                    {"provider": "mock", "model": "b", "seats": 2},
                    {"provider": "mock", "model": "a", "seats": 3},
                ]
            )
        )

        assert config.models == ["a", "b"]
