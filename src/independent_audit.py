"""Independent raw-tuple oracle for recovery-epoch instances.

This module deliberately imports no project model, solver, cost, replay, or
certificate code.  It accepts only primitive tuples and performs its own
validation, capacity updates, rounded-cost calculation, and memoized exhaustive
search.  Keeping this implementation separate reduces common-mode risk in the
main finite campaign; agreement is still a finite check, not a formal proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

RawTier = tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RawSolution:
    feasible: bool
    cost: int | None
    epochs: int | None
    states: int
    transitions: int

    @property
    def status(self) -> str:
        return "feasible" if self.feasible else "infeasible"

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "status": self.status,
            "cost": self.cost,
            "epochs": self.epochs,
            "states": self.states,
            "transitions": self.transitions,
        }


def _validate_tier(tier: RawTier) -> None:
    if not isinstance(tier, tuple):
        raise TypeError("raw tiers must be tuples")
    for segment in tier:
        if not isinstance(segment, tuple) or len(segment) != 2:
            raise TypeError("raw segments must be (occupied, live) tuples")
        occupied, live = segment
        if type(occupied) is not int or type(live) is not int:
            raise TypeError("raw occupied/live values must be integers")
        if occupied <= 0 or live < 0 or live > occupied:
            raise ValueError("require occupied > 0 and 0 <= live <= occupied")


def _raw_cost(live: int, quantum: int, commit: int) -> int:
    if live == 0:
        payload = 0
    else:
        payload = ((live + quantum - 1) // quantum) * quantum
    return payload + commit


def solve_raw(
    tier0: RawTier,
    tier1: RawTier,
    free: tuple[int, int],
    quantum: int,
    commit: int,
) -> RawSolution:
    """Return exact minimum cost using only explicit free-space transitions.

    The recursion tries every legal nonempty remaining prefix from either
    source.  Its memo key includes the explicit free vector rather than relying
    on the project's prefix-capacity identity.
    """
    _validate_tier(tier0)
    _validate_tier(tier1)
    if (
        not isinstance(free, tuple)
        or len(free) != 2
        or any(type(value) is not int or value < 0 for value in free)
    ):
        raise ValueError("free must be a pair of non-negative integers")
    if type(quantum) is not int or quantum <= 0:
        raise ValueError("quantum must be positive")
    if type(commit) is not int or commit < 0:
        raise ValueError("commit must be non-negative")

    tiers = (tier0, tier1)
    n0, n1 = len(tier0), len(tier1)
    transitions = 0

    @lru_cache(maxsize=None)
    def search(i: int, j: int, f0: int, f1: int) -> tuple[int, int] | None:
        nonlocal transitions
        if (i, j) == (n0, n1):
            return (0, 0)
        winner: tuple[int, int] | None = None
        for source in (0, 1):
            start = i if source == 0 else j
            limit = n0 if source == 0 else n1
            live_sum = 0
            occupied_sum = 0
            for end in range(start + 1, limit + 1):
                occupied, live = tiers[source][end - 1]
                live_sum += live
                occupied_sum += occupied
                target_free = f1 if source == 0 else f0
                if live_sum > target_free:
                    break
                transitions += 1
                if source == 0:
                    suffix = search(end, j, f0 + occupied_sum, f1 - live_sum)
                else:
                    suffix = search(i, end, f0 - live_sum, f1 + occupied_sum)
                if suffix is None:
                    continue
                candidate = (
                    _raw_cost(live_sum, quantum, commit) + suffix[0],
                    1 + suffix[1],
                )
                if winner is None or candidate < winner:
                    winner = candidate
        return winner

    optimum = search(0, 0, free[0], free[1])
    states = search.cache_info().currsize
    if optimum is None:
        return RawSolution(False, None, None, states, transitions)
    return RawSolution(True, optimum[0], optimum[1], states, transitions)
