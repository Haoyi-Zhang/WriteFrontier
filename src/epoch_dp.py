"""Exact solvers and reserve frontiers for the recovery-epoch model."""
from __future__ import annotations

from dataclasses import dataclass
from math import inf
from typing import Iterable

from epoch_model import (
    Batch,
    EpochInstance,
    batch_cost,
    batch_totals,
    lower_bound,
    replay,
    serialize_instance,
    serialize_schedule,
)


class SearchBudgetExceeded(RuntimeError):
    """A finite checker stopped without classifying the instance."""


@dataclass(frozen=True, slots=True)
class FeasibilityScan:
    """Linear-time feasibility decision and replayable certificate."""

    status: str
    schedule: tuple[Batch, ...]
    steps: int
    blocking_state: tuple[int, int] | None = None
    blocking_free: tuple[int, int] | None = None
    next_live: tuple[int | None, int | None] | None = None

    @property
    def feasible(self) -> bool:
        return self.status == "feasible"

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "steps": self.steps,
            "schedule": [
                {"source": b.source, "start": b.start, "end": b.end}
                for b in self.schedule
            ],
            "blocking_state": None if self.blocking_state is None else list(self.blocking_state),
            "blocking_free": None if self.blocking_free is None else list(self.blocking_free),
            "next_live": None if self.next_live is None else list(self.next_live),
        }


def scan_feasibility(instance: EpochInstance) -> FeasibilityScan:
    """Decide feasibility by repeatedly taking one legal first segment.

    Legal-step confluence proves that any deterministic legal choice is safe.
    This implementation prefers source 0 on ties, updates free space
    incrementally, and returns either a complete single-segment schedule or a
    blocking-state certificate.  It does not call either optimizer.  The
    incremental decision loop uses constant working registers, excluding its
    output schedule.  Successful-completion checks call final_free and replay,
    whose prefix arrays and replay records use linear auxiliary space.
    """

    n0, n1 = instance.lengths
    i = j = 0
    f0, f1 = instance.free
    schedule: list[Batch] = []
    while (i, j) != (n0, n1):
        live0 = instance.tiers[0][i].live if i < n0 else None
        live1 = instance.tiers[1][j].live if j < n1 else None
        legal0 = live0 is not None and live0 <= f1
        legal1 = live1 is not None and live1 <= f0
        if not legal0 and not legal1:
            return FeasibilityScan(
                "infeasible",
                tuple(schedule),
                len(schedule),
                (i, j),
                (f0, f1),
                (live0, live1),
            )
        if legal0:
            seg = instance.tiers[0][i]
            schedule.append(Batch(0, i, i + 1))
            f1 -= seg.live
            f0 += seg.occupied
            i += 1
        else:
            assert legal1 and live1 is not None
            seg = instance.tiers[1][j]
            schedule.append(Batch(1, j, j + 1))
            f0 -= seg.live
            f1 += seg.occupied
            j += 1
    if (f0, f1) != instance.final_free():
        raise AssertionError("linear scan and prefix identity disagree")
    replay(instance, schedule)
    return FeasibilityScan("feasible", tuple(schedule), len(schedule))


def make_blocking_certificate(
    instance: EpochInstance, scan: FeasibilityScan | None = None
) -> dict:
    """Encode an independently checkable negative certificate.

    The certificate embeds the original ordered instance, the exact partial
    path taken by the linear scan, and the claimed reached state.  The separate
    checker recomputes legality and all accounting from primitive JSON fields.
    """

    result = scan_feasibility(instance) if scan is None else scan
    if result.feasible:
        raise ValueError("a feasible scan has no blocking certificate")
    if (
        result.blocking_state is None
        or result.blocking_free is None
        or result.next_live is None
    ):
        raise ValueError("infeasible scan is missing blocking fields")
    return {
        "kind": "ordered-prefix-block",
        "instance": serialize_instance(instance),
        "partial_schedule": serialize_schedule(result.schedule),
        "reached_state": list(result.blocking_state),
        "free": list(result.blocking_free),
        "next_live": list(result.next_live),
    }


@dataclass(frozen=True, slots=True)
class Solution:
    status: str
    cost: int | None
    schedule: tuple[Batch, ...]
    states: int
    transitions: int
    lower_bound: int

    @property
    def feasible(self) -> bool:
        return self.status == "feasible"

    @property
    def batches(self) -> int:
        return len(self.schedule)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "cost": self.cost,
            "schedule": [
                {"source": b.source, "start": b.start, "end": b.end}
                for b in self.schedule
            ],
            "states": self.states,
            "transitions": self.transitions,
            "lower_bound": self.lower_bound,
            "ratio_to_lower_bound": (
                None
                if self.cost is None or self.lower_bound == 0
                else self.cost / self.lower_bound
            ),
        }


def _prefixes(instance: EpochInstance) -> tuple[list[int], list[int], list[int], list[int]]:
    o0, o1, l0, l1 = instance.prefix_arrays()
    return list(o0), list(o1), list(l0), list(l1)


def solve_normal_form(instance: EpochInstance, max_states: int = 5_000_000) -> Solution:
    """Exact shortest path over schedules that alternate source tiers.

    The adjacent-epoch merge lemma proves that some optimum has this form:
    consecutive epochs from the same source can be merged, remain feasible,
    and do not increase rounded-payload-plus-commit cost.
    """
    n0, n1 = instance.lengths
    lb = lower_bound(instance)
    if not instance.final_fits():
        return Solution("infeasible-final", None, (), 1, 0, lb)
    if n0 == 0 and n1 == 0:
        return Solution("feasible", 0, (), 1, 0, 0)
    o0, o1, l0, l1 = _prefixes(instance)
    # State is (processed0, processed1, last_source), with 2 meaning none.
    dist: dict[tuple[int, int, int], tuple[int, int]] = {(0, 0, 2): (0, 0)}
    parent: dict[tuple[int, int, int], tuple[tuple[int, int, int], Batch]] = {}
    transitions = 0
    states_seen = 1
    for done in range(n0 + n1 + 1):
        layer = sorted(
            (state for state in dist if state[0] + state[1] == done),
            key=lambda x: (x[0], x[1], x[2]),
        )
        for state in layer:
            i, j, last = state
            score = dist[state]
            f0 = instance.free[0] + o0[i] - l1[j]
            f1 = instance.free[1] + o1[j] - l0[i]
            if min(f0, f1) < 0:
                raise AssertionError("reachable DP state has negative free space")
            for source in (0, 1):
                if source == last:
                    continue
                start = i if source == 0 else j
                limit = n0 if source == 0 else n1
                target_free = f1 if source == 0 else f0
                prefix_live = l0 if source == 0 else l1
                for end in range(start + 1, limit + 1):
                    live = prefix_live[end] - prefix_live[start]
                    if live > target_free:
                        # Prefix live bytes are nondecreasing.
                        break
                    transitions += 1
                    batch = Batch(source, start, end)
                    nxt = (end, j, source) if source == 0 else (i, end, source)
                    candidate = (
                        score[0] + batch_cost(live, instance.quantum, instance.commit_bytes),
                        score[1] + 1,
                    )
                    old = dist.get(nxt)
                    if old is None:
                        states_seen += 1
                        if states_seen > max_states:
                            raise SearchBudgetExceeded("normal-form state budget exceeded")
                    if old is None or candidate < old:
                        dist[nxt] = candidate
                        parent[nxt] = (state, batch)
    finals = [
        (score, state)
        for state, score in dist.items()
        if state[0] == n0 and state[1] == n1
    ]
    if not finals:
        return Solution("infeasible", None, (), states_seen, transitions, lb)
    score, state = min(finals, key=lambda item: (item[0], item[1][2]))
    rev: list[Batch] = []
    while state != (0, 0, 2):
        prev, batch = parent[state]
        rev.append(batch)
        state = prev
    schedule = tuple(reversed(rev))
    checked = replay(instance, schedule)
    if checked["cost"] != score[0]:
        raise AssertionError("DP and replay costs disagree")
    return Solution("feasible", score[0], schedule, states_seen, transitions, lb)


def solve_unrestricted(instance: EpochInstance, max_states: int = 5_000_000) -> Solution:
    """Independent exact shortest path allowing either source at every state.

    This is used as an oracle for the normal-form restriction.  Its state and
    transition code intentionally differ from ``solve_normal_form``.
    """
    n0, n1 = instance.lengths
    lb = lower_bound(instance)
    if not instance.final_fits():
        return Solution("infeasible-final", None, (), 1, 0, lb)
    o0, o1, l0, l1 = _prefixes(instance)
    best: list[list[float]] = [[inf] * (n1 + 1) for _ in range(n0 + 1)]
    epochs: list[list[int]] = [[10**9] * (n1 + 1) for _ in range(n0 + 1)]
    predecessor: dict[tuple[int, int], tuple[tuple[int, int], Batch]] = {}
    best[0][0] = 0
    epochs[0][0] = 0
    transitions = 0
    states = 0
    for total in range(n0 + n1 + 1):
        for i in range(max(0, total - n1), min(n0, total) + 1):
            j = total - i
            if best[i][j] == inf:
                continue
            states += 1
            if states > max_states:
                raise SearchBudgetExceeded("unrestricted state budget exceeded")
            free = (instance.free[0] + o0[i] - l1[j],
                    instance.free[1] + o1[j] - l0[i])
            for source, start, limit in ((0, i, n0), (1, j, n1)):
                running_live = 0
                for end in range(start + 1, limit + 1):
                    running_live += instance.tiers[source][end - 1].live
                    if running_live > free[1 - source]:
                        break
                    transitions += 1
                    ni, nj = (end, j) if source == 0 else (i, end)
                    candidate = int(best[i][j]) + batch_cost(
                        running_live, instance.quantum, instance.commit_bytes
                    )
                    candidate_epochs = epochs[i][j] + 1
                    if (candidate, candidate_epochs) < (best[ni][nj], epochs[ni][nj]):
                        best[ni][nj] = candidate
                        epochs[ni][nj] = candidate_epochs
                        predecessor[(ni, nj)] = ((i, j), Batch(source, start, end))
    if best[n0][n1] == inf:
        return Solution("infeasible", None, (), states, transitions, lb)
    state = (n0, n1)
    rev: list[Batch] = []
    while state != (0, 0):
        prev, batch = predecessor[state]
        rev.append(batch)
        state = prev
    schedule = tuple(reversed(rev))
    checked = replay(instance, schedule)
    if checked["cost"] != int(best[n0][n1]):
        raise AssertionError("unrestricted solver and replay costs disagree")
    return Solution(
        "feasible", int(best[n0][n1]), schedule, states, transitions, lb
    )


def brute_force_oracle(instance: EpochInstance, max_nodes: int = 2_000_000) -> Solution:
    """Exhaustively enumerate all legal batch schedules without memoization.

    Intended only for tiny instances.  Explicit free-space updates make this a
    useful adverse control against both dynamic programs.
    """
    n0, n1 = instance.lengths
    lb = lower_bound(instance)
    if not instance.final_fits():
        return Solution("infeasible-final", None, (), 1, 0, lb)
    best_cost: int | None = None
    best_schedule: tuple[Batch, ...] = ()
    nodes = 0
    transitions = 0

    def visit(i: int, j: int, f0: int, f1: int, cost: int, path: tuple[Batch, ...]) -> None:
        nonlocal best_cost, best_schedule, nodes, transitions
        nodes += 1
        if nodes > max_nodes:
            raise SearchBudgetExceeded("brute-force node budget exceeded")
        if best_cost is not None and cost >= best_cost:
            return
        if (i, j) == (n0, n1):
            best_cost = cost
            best_schedule = path
            return
        for source in (0, 1):
            start = i if source == 0 else j
            limit = n0 if source == 0 else n1
            running_live = 0
            running_occupied = 0
            for end in range(start + 1, limit + 1):
                seg = instance.tiers[source][end - 1]
                running_live += seg.live
                running_occupied += seg.occupied
                free_target = f1 if source == 0 else f0
                if running_live > free_target:
                    break
                transitions += 1
                if source == 0:
                    visit(
                        end,
                        j,
                        f0 + running_occupied,
                        f1 - running_live,
                        cost + batch_cost(running_live, instance.quantum, instance.commit_bytes),
                        path + (Batch(0, i, end),),
                    )
                else:
                    visit(
                        i,
                        end,
                        f0 - running_live,
                        f1 + running_occupied,
                        cost + batch_cost(running_live, instance.quantum, instance.commit_bytes),
                        path + (Batch(1, j, end),),
                    )

    visit(0, 0, instance.free[0], instance.free[1], 0, ())
    if best_cost is None:
        return Solution("infeasible", None, (), nodes, transitions, lb)
    replay(instance, best_schedule)
    return Solution("feasible", best_cost, best_schedule, nodes, transitions, lb)


def pareto_frontier(
    tiers: tuple[tuple, tuple],
    max_free: tuple[int, int],
    quantum: int = 4,
    commit_bytes: int = 1,
) -> list[dict]:
    """Exact componentwise-minimal feasible free-space vectors in a box."""
    feasible: list[dict] = []
    for f0 in range(max_free[0] + 1):
        for f1 in range(max_free[1] + 1):
            instance = EpochInstance(tiers, (f0, f1), quantum, commit_bytes)
            solution = solve_normal_form(instance)
            if solution.feasible:
                feasible.append(
                    {
                        "free0": f0,
                        "free1": f1,
                        "cost": solution.cost,
                        "batches": solution.batches,
                    }
                )
    return [
        point
        for point in feasible
        if not any(
            other is not point
            and other["free0"] <= point["free0"]
            and other["free1"] <= point["free1"]
            and (
                other["free0"] < point["free0"]
                or other["free1"] < point["free1"]
            )
            for other in feasible
        )
    ]


def best_split_at_budget(
    tiers: tuple[tuple, tuple],
    budget: int,
    quantum: int = 4,
    commit_bytes: int = 1,
) -> tuple[EpochInstance, Solution] | None:
    """Minimum-cost feasible free-space split with f0 + f1 <= budget."""
    winner: tuple[tuple[int, int, int, int], EpochInstance, Solution] | None = None
    for f0 in range(budget + 1):
        for f1 in range(budget - f0 + 1):
            instance = EpochInstance(tiers, (f0, f1), quantum, commit_bytes)
            solution = solve_normal_form(instance)
            if not solution.feasible:
                continue
            assert solution.cost is not None
            score = (solution.cost, f0 + f1, f0, f1)
            if winner is None or score < winner[0]:
                winner = (score, instance, solution)
    if winner is None:
        return None
    return winner[1], winner[2]


def final_fit_free_lower_bound(tiers: tuple[tuple, tuple]) -> tuple[int, int]:
    """Componentwise initial-free lower bound implied by the final layout."""

    occupied = [sum(seg.occupied for seg in tier) for tier in tiers]
    live = [sum(seg.live for seg in tier) for tier in tiers]
    return (max(0, live[1] - occupied[0]), max(0, live[0] - occupied[1]))


def find_min_common_slack(
    tiers: tuple[tuple, tuple],
    quantum: int = 4,
    commit_bytes: int = 1,
    max_slack: int | None = None,
) -> tuple[int, EpochInstance, Solution]:
    """Find minimal common slack above the asymmetric final-fit lower bound.

    The tested reserve vectors are ``(base[0] + s, base[1] + s)``.  The two
    initial free-space values need not be equal; only the added slack ``s`` is
    common to both components.
    """

    base = final_fit_free_lower_bound(tiers)
    occupied = [sum(seg.occupied for seg in tier) for tier in tiers]
    live = [sum(seg.live for seg in tier) for tier in tiers]
    if max_slack is None:
        max_slack = max(live + occupied + [1]) + quantum
    for slack in range(max_slack + 1):
        instance = EpochInstance(
            tiers,
            (base[0] + slack, base[1] + slack),
            quantum,
            commit_bytes,
        )
        solution = solve_normal_form(instance)
        if solution.feasible:
            return slack, instance, solution
    raise SearchBudgetExceeded("balanced-slack search did not find a feasible reserve")


def confluence_audit(instance: EpochInstance) -> dict:
    """Finite check of the feasible-state closure under every legal batch.

    The general exchange proof is in ``proofs/recovery-epochs.md``.  This
    checker independently computes the full suffix-viability table and then
    tests every legal edge out of every nonterminal viable prefix state.
    The legacy ``viable_states`` field counts nonterminal viable prefix-state
    instances, excluding the terminal state even when final capacity fits.
    """
    n0, n1 = instance.lengths
    viable = [[False] * (n1 + 1) for _ in range(n0 + 1)]
    if min(instance.final_free()) >= 0:
        viable[n0][n1] = True
    for total in range(n0 + n1 - 1, -1, -1):
        for i in range(max(0, total - n1), min(n0, total) + 1):
            j = total - i
            free = instance.free_at(i, j)
            if min(free) < 0:
                continue
            for source in (0, 1):
                start = i if source == 0 else j
                limit = n0 if source == 0 else n1
                live = 0
                for end in range(start + 1, limit + 1):
                    live += instance.tiers[source][end - 1].live
                    if live > free[1 - source]:
                        break
                    ni, nj = (end, j) if source == 0 else (i, end)
                    if viable[ni][nj]:
                        viable[i][j] = True
                        break
                if viable[i][j]:
                    break
    viable_states = 0
    legal_edges = 0
    violations: list[dict] = []
    for i in range(n0 + 1):
        for j in range(n1 + 1):
            # Terminal states have no outgoing edges and are not counted.
            if not viable[i][j] or (i, j) == (n0, n1):
                continue
            viable_states += 1
            free = instance.free_at(i, j)
            for source in (0, 1):
                start = i if source == 0 else j
                limit = n0 if source == 0 else n1
                live = 0
                for end in range(start + 1, limit + 1):
                    live += instance.tiers[source][end - 1].live
                    if live > free[1 - source]:
                        break
                    legal_edges += 1
                    ni, nj = (end, j) if source == 0 else (i, end)
                    if not viable[ni][nj]:
                        violations.append(
                            {
                                "state": [i, j],
                                "source": source,
                                "end": end,
                                "successor": [ni, nj],
                            }
                        )
    return {
        "initial_feasible": viable[0][0],
        "viable_states": viable_states,  # Legacy key; nonterminal prefix-state count.
        "legal_edges_from_viable_states": legal_edges,
        "violations": violations,
    }
