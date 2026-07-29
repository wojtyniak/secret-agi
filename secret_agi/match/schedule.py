"""Seeded, seat-balanced game schedules.

Two confounds this removes:

- **Seat position.** The starting Director is chosen at random, and turn order is
  clockwise from there, so a model that always occupies seat 0 does not play the
  same game as one that always occupies seat 4. Seat assignments are rotated so
  every model spends an equal share of games in every seat.
- **Role assignment.** Roles are dealt by the engine from the game seed. Because
  each game's seed is derived deterministically from the run seed, the whole
  schedule is reproducible from `(run seed, config)` alone — which is what makes
  a published run checkable by a third party.

Role *balancing* (every model plays every role the same number of times) is a
property of averaging over enough seeded games rather than something forced per
game: forcing it would mean overriding the engine's dealing, and a run where the
AGI is never dealt to model X is not a run of the actual game.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .config import PlayerConfig, RunConfig


@dataclass(frozen=True)
class ScheduledGame:
    """One game's fully-determined setup."""

    index: int
    seed: int
    player_ids: list[str]
    seat_models: list[PlayerConfig]
    """`seat_models[i]` is the model occupying `player_ids[i]`."""

    @property
    def assignments(self) -> dict[str, PlayerConfig]:
        return dict(zip(self.player_ids, self.seat_models, strict=True))

    def model_of(self, player_id: str) -> str:
        return self.assignments[player_id].model


def build_schedule(config: RunConfig) -> list[ScheduledGame]:
    """Expand a run config into its full list of games.

    Deterministic in `(config.seed, config)`: the same inputs always produce the
    same schedule, so a published config and seed reproduce a published run.
    """
    player_ids = [f"player_{i}" for i in range(config.player_count)]
    seats = config.seat_models
    rng = random.Random(config.seed)

    games: list[ScheduledGame] = []
    for index in range(config.games):
        rotated = _rotate(seats, index)
        # Shuffle within the rotation so repeated games do not lock the same
        # models into the same relative order.
        arrangement = _seeded_shuffle(rotated, rng)
        games.append(
            ScheduledGame(
                index=index,
                # Derived, not drawn, so a game's seed is a pure function of the
                # run seed and its index — resumable and independently checkable.
                seed=_game_seed(config.seed, index),
                player_ids=list(player_ids),
                seat_models=arrangement,
            )
        )

    return games


def seat_balance(games: list[ScheduledGame]) -> dict[str, dict[str, int]]:
    """How many times each model occupied each seat. For reporting the control."""
    counts: dict[str, dict[str, int]] = {}
    for game in games:
        for player_id, player in game.assignments.items():
            counts.setdefault(player.model, {}).setdefault(player_id, 0)
            counts[player.model][player_id] += 1
    return counts


def _game_seed(run_seed: int, index: int) -> int:
    # A large odd stride keeps consecutive games' seeds far apart without needing
    # to store them.
    return (run_seed * 1_000_003 + index * 7_919 + 1) % (2**31 - 1)


def _rotate(seats: list[PlayerConfig], offset: int) -> list[PlayerConfig]:
    if not seats:
        return []
    shift = offset % len(seats)
    return seats[shift:] + seats[:shift]


def _seeded_shuffle(
    seats: list[PlayerConfig], rng: random.Random
) -> list[PlayerConfig]:
    arrangement = list(seats)
    rng.shuffle(arrangement)
    return arrangement
