"""Seeded, seat-balanced game schedules.

Two confounds this removes:

- **Seat position.** The starting Director is chosen at random, and turn order is
  clockwise from there, so a model that always occupies seat 0 does not play the
  same game as one that always occupies seat 4. Seat assignments are *rotated*:
  one seeded ordering per run, then a pure rotation of it per game. When the
  game count is a multiple of the table size the balance is **exact**; otherwise
  the leftover partial cycle leaves a gap of at most
  `min(games mod seats, seats - games mod seats)`. `max_seat_imbalance()`
  reports the realised figure, which every run report carries.
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

    # One shuffled base ordering per run, then a pure rotation of it per game.
    # Shuffling *per game* would destroy the rotation — a uniform shuffle of a
    # rotated list is just a uniform shuffle — leaving seat balance to chance,
    # which is exactly the confound the rotation exists to remove. Shuffling once
    # keeps the run from always starting model A in seat 0 while preserving the
    # exact ±1 balance a rotation gives.
    base = list(seats)
    rng.shuffle(base)

    games: list[ScheduledGame] = []
    for index in range(config.games):
        arrangement = _rotate(base, index)
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


def max_seat_imbalance(games: list[ScheduledGame]) -> int:
    """Largest gap between a model's most- and least-occupied seat.

    0 or 1 means the rotation is doing its job. Reported so the control can be
    checked rather than asserted.
    """
    worst = 0
    seats = {player_id for game in games for player_id in game.player_ids}
    for counts in seat_balance(games).values():
        occupancy = [counts.get(seat, 0) for seat in seats]
        worst = max(worst, max(occupancy) - min(occupancy))
    return worst
