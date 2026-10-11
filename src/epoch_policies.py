"""Deterministic controlled policies for the ordered recovery-epoch model.

The names are intentionally reported as *proxies*: they isolate batching and
recency choices associated with LRU-tiered, leveled, and size-tiered designs;
they are not drop-in implementations of production caches or LSM engines.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from epoch_model import Batch, EpochInstance, batch_cost, batch_totals, lower_bound, replay


@dataclass(frozen=True, slots=True)
class PolicyResult:
    policy: str
    status: str
    schedule: tuple[Batch, ...]
    cost: int | None
    lower_bound: int
    reason: str = ""

    @property
    def ratio_to_lower_bound(self) -> float | None:
        if self.cost is None or self.lower_bound == 0:
            return None
        return self.cost / self.lower_bound

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "status": self.status,
            "schedule": [
                {"source": b.source, "start": b.start, "end": b.end}
                for b in self.schedule
            ],
            "cost": self.cost,
            "lower_bound": self.lower_bound,
            "ratio_to_lower_bound": self.ratio_to_lower_bound,
            "reason": self.reason,
        }


def _legal_prefixes(instance: EpochInstance, indices: tuple[int, int]) -> dict[int, list[tuple[int, int, int]]]:
    free = instance.free_at(*indices)
    legal: dict[int, list[tuple[int, int, int]]] = {0: [], 1: []}
    for source in (0, 1):
        start = indices[source]
        live = 0
        occupied = 0
        for end in range(start + 1, len(instance.tiers[source]) + 1):
            seg = instance.tiers[source][end - 1]
            live += seg.live
            occupied += seg.occupied
            if live > free[1 - source]:
                break
            legal[source].append((end, live, occupied))
    return legal


def _gain_score(instance: EpochInstance, live: int, occupied: int) -> tuple[bool, Fraction]:
    """Exact gain/write order, with positive gain at zero cost ranked first."""
    cost = batch_cost(live, instance.quantum, instance.commit_bytes)
    return cost == 0, Fraction(occupied, cost) if cost else Fraction(0)


def _run_policy(instance: EpochInstance, policy: str, fanin: int = 4) -> PolicyResult:
    indices = [0, 0]
    schedule: list[Batch] = []
    n = instance.lengths
    while tuple(indices) != n:
        legal = _legal_prefixes(instance, tuple(indices))
        candidates: list[tuple[tuple, Batch]] = []
        for source in (0, 1):
            options = legal[source]
            if not options:
                continue
            start = indices[source]
            head = instance.tiers[source][start]
            if policy == "lru-tiered-proxy":
                end, live, occupied = options[0]
                key = (head.birth, source)
            elif policy == "leveled-proxy":
                # For each source, consume its largest currently feasible
                # contiguous prefix.  Across sources, prefer reclaimed
                # occupied bytes, then copied live bytes, then birth/source.
                end, live, occupied = options[-1]
                key = (-occupied, -live, head.birth, source)
            elif policy == "size-tiered-proxy":
                # Admit at most ``fanin`` consecutive runs whose occupied
                # sizes are within a factor of two.  Use the largest admitted
                # prefix (or one segment if none larger is admitted), then
                # compare sources by oldest head, larger fan-in, and source.
                admitted = []
                for option in options:
                    end, live, occupied = option
                    count = end - start
                    if count > fanin:
                        break
                    sizes = [s.occupied for s in instance.tiers[source][start:end]]
                    if min(sizes) * 2 >= max(sizes):
                        admitted.append(option)
                end, live, occupied = admitted[-1] if admitted else options[0]
                key = (head.birth, -(end - start), source)
            elif policy == "gain-per-write":
                # Our scalable comparator: maximize immediately reclaimed bytes
                # per physical write.  Within one source, ties prefer greater
                # occupied gain and then the shorter prefix; across sources,
                # ties prefer the older head and then source 0.
                end, live, occupied = max(
                    options,
                    key=lambda item: (
                        *_gain_score(instance, item[1], item[2]),
                        item[2],
                        -item[0],
                    ),
                )
                zero_cost, ratio = _gain_score(instance, live, occupied)
                key = (-zero_cost, -ratio, head.birth, source)
            else:
                raise ValueError(f"unknown policy: {policy}")
            candidates.append((key, Batch(source, start, end)))
        if not candidates:
            return PolicyResult(
                policy,
                "blocked",
                tuple(schedule),
                None,
                lower_bound(instance),
                "no source has a legal non-empty prefix",
            )
        _, batch = min(candidates, key=lambda item: item[0])
        schedule.append(batch)
        indices[batch.source] = batch.end
    checked = replay(instance, schedule)
    return PolicyResult(
        policy,
        "complete",
        tuple(schedule),
        int(checked["cost"]),
        lower_bound(instance),
    )


def lru_tiered_proxy(instance: EpochInstance) -> PolicyResult:
    return _run_policy(instance, "lru-tiered-proxy")


def leveled_proxy(instance: EpochInstance) -> PolicyResult:
    return _run_policy(instance, "leveled-proxy")


def size_tiered_proxy(instance: EpochInstance, fanin: int = 4) -> PolicyResult:
    if type(fanin) is not int or fanin <= 0:
        raise ValueError("fanin must be a positive integer")
    return _run_policy(instance, "size-tiered-proxy", fanin=fanin)


def gain_per_write(instance: EpochInstance) -> PolicyResult:
    return _run_policy(instance, "gain-per-write")


def maximum_prefix_start(instance: EpochInstance, first_source: int) -> PolicyResult:
    """Alternate maximal feasible prefixes, preferring the declared start.

    If the preferred source is blocked or exhausted, try the other source.
    Each segment is examined at most once successfully and once as a blocked
    head per epoch. No optimizer, future requests, or extra retention data are
    consulted. Capacity is maintained incrementally and the result is replayed.
    """
    if type(first_source) is not int or first_source not in (0, 1):
        raise ValueError("first_source must be 0 or 1")
    indices = [0, 0]
    free = list(instance.free)
    preferred = first_source
    schedule: list[Batch] = []
    while tuple(indices) != instance.lengths:
        selected = None
        for source in (preferred, 1 - preferred):
            start = indices[source]
            end = start
            occupied = live = 0
            tier = instance.tiers[source]
            while end < len(tier) and live + tier[end].live <= free[1 - source]:
                occupied += tier[end].occupied
                live += tier[end].live
                end += 1
            if end > start:
                selected = source, start, end, occupied, live
                break
        if selected is None:
            return PolicyResult("maximum-prefix-start-" + str(first_source), "blocked",
                                tuple(schedule), None, lower_bound(instance),
                                "no source has a legal non-empty prefix")
        source, start, end, occupied, live = selected
        schedule.append(Batch(source, start, end))
        indices[source] = end
        free[source] += occupied
        free[1 - source] -= live
        preferred = 1 - source
    checked = replay(instance, schedule)
    return PolicyResult("maximum-prefix-start-" + str(first_source), "complete",
                        tuple(schedule), checked["cost"], lower_bound(instance))


def two_start_maximum_prefix(instance: EpochInstance) -> PolicyResult:
    """Run both start preferences under the same frozen input and retain cheaper.

    Cost, then epoch count, then source-0 preference break ties. This is an
    offline two-candidate baseline, not a claim of cost optimality.
    """
    candidates = [maximum_prefix_start(instance, source) for source in (0, 1)]
    complete = [(r, source) for source, r in enumerate(candidates)
                if r.status == "complete"]
    if not complete:
        r = candidates[0]
        return PolicyResult("two-start-maximum-prefix", r.status, r.schedule,
                            r.cost, r.lower_bound, r.reason)
    r, _ = min(complete, key=lambda item: (item[0].cost, len(item[0].schedule), item[1]))
    return PolicyResult("two-start-maximum-prefix", "complete", r.schedule,
                        r.cost, r.lower_bound)


def all_policies(instance: EpochInstance) -> tuple[PolicyResult, ...]:
    return (
        lru_tiered_proxy(instance),
        leveled_proxy(instance),
        size_tiered_proxy(instance),
        gain_per_write(instance),
    )
