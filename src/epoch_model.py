"""Recovery-epoch model for two finite ordered log tiers.

A recovery epoch copies the live payload of a non-empty prefix of one tier,
flushes it, atomically publishes one commit record, and only then reclaims the
source prefix.  Sizes and costs are non-negative integer allocation units.
The model is deliberately a byte-accounting/reference model, not a device or
filesystem emulator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Segment:
    """One immutable source segment.

    ``occupied`` is the source allocation that is released after commit.
    ``live`` is the retained payload copied to the other tier.  Fully dead
    segments (live == 0) are allowed because reclaim-only epochs matter under
    tight capacity. ``birth`` is used only by deterministic baseline policies.
    """

    occupied: int
    live: int
    birth: int = 0
    name: str = ""

    def __post_init__(self) -> None:
        for field_name in ("occupied", "live", "birth"):
            value = getattr(self, field_name)
            if type(value) is not int:  # bool is intentionally rejected.
                raise TypeError(f"{field_name} must be an integer")
        if self.occupied <= 0:
            raise ValueError("occupied must be positive")
        if not 0 <= self.live <= self.occupied:
            raise ValueError("require 0 <= live <= occupied")
        if self.birth < 0:
            raise ValueError("birth must be non-negative")


@dataclass(frozen=True, slots=True)
class Batch:
    """Half-open prefix interval [start, end) processed from one tier."""

    source: int
    start: int
    end: int

    def __post_init__(self) -> None:
        if type(self.source) is not int or self.source not in (0, 1):
            raise ValueError("source must be 0 or 1")
        if type(self.start) is not int or type(self.end) is not int:
            raise TypeError("batch bounds must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("batch must be a non-empty half-open interval")


@dataclass(frozen=True, slots=True)
class EpochInstance:
    """Two ordered tiers plus initial free space and write-cost parameters."""

    tiers: tuple[tuple[Segment, ...], tuple[Segment, ...]]
    free: tuple[int, int]
    quantum: int = 4
    commit_bytes: int = 1
    label: str = ""

    def __post_init__(self) -> None:
        if len(self.tiers) != 2:
            raise ValueError("exactly two tiers are required")
        normalized: list[tuple[Segment, ...]] = []
        for tier in self.tiers:
            normalized.append(tuple(tier))
            if any(not isinstance(seg, Segment) for seg in tier):
                raise TypeError("tiers must contain Segment objects")
        object.__setattr__(self, "tiers", (normalized[0], normalized[1]))
        if len(self.free) != 2 or any(type(x) is not int or x < 0 for x in self.free):
            raise ValueError("free must contain two non-negative integers")
        if type(self.quantum) is not int or self.quantum <= 0:
            raise ValueError("quantum must be a positive integer")
        if type(self.commit_bytes) is not int or self.commit_bytes < 0:
            raise ValueError("commit_bytes must be a non-negative integer")

    @property
    def lengths(self) -> tuple[int, int]:
        return (len(self.tiers[0]), len(self.tiers[1]))

    @property
    def total_live(self) -> int:
        return sum(seg.live for tier in self.tiers for seg in tier)

    @property
    def live_by_source(self) -> tuple[int, int]:
        return tuple(sum(seg.live for seg in tier) for tier in self.tiers)  # type: ignore[return-value]

    @property
    def occupied_by_source(self) -> tuple[int, int]:
        return tuple(sum(seg.occupied for seg in tier) for tier in self.tiers)  # type: ignore[return-value]

    def prefix_arrays(self) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
        occ: list[list[int]] = [[0], [0]]
        live: list[list[int]] = [[0], [0]]
        for source in (0, 1):
            for seg in self.tiers[source]:
                occ[source].append(occ[source][-1] + seg.occupied)
                live[source].append(live[source][-1] + seg.live)
        return tuple(occ[0]), tuple(occ[1]), tuple(live[0]), tuple(live[1])

    def free_at(self, i: int, j: int) -> tuple[int, int]:
        n0, n1 = self.lengths
        if not (0 <= i <= n0 and 0 <= j <= n1):
            raise ValueError("prefix indices outside the instance")
        o0, o1, l0, l1 = self.prefix_arrays()
        # Tier 0 gains reclaimed tier-0 occupancy and receives tier-1 live bytes.
        f0 = self.free[0] + o0[i] - l1[j]
        f1 = self.free[1] + o1[j] - l0[i]
        return f0, f1

    def final_free(self) -> tuple[int, int]:
        return self.free_at(*self.lengths)

    def final_fits(self) -> bool:
        return min(self.final_free()) >= 0


def round_up(value: int, quantum: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("value must be a non-negative integer")
    if type(quantum) is not int or quantum <= 0:
        raise ValueError("quantum must be a positive integer")
    if value == 0:
        return 0
    return ((value + quantum - 1) // quantum) * quantum


def batch_cost(live: int, quantum: int, commit_bytes: int) -> int:
    """Physical write units for one epoch: rounded payload plus one commit."""
    if commit_bytes < 0:
        raise ValueError("commit_bytes must be non-negative")
    return round_up(live, quantum) + commit_bytes


def batch_totals(instance: EpochInstance, batch: Batch) -> tuple[int, int]:
    tier = instance.tiers[batch.source]
    if batch.end > len(tier):
        raise ValueError("batch end outside source tier")
    chunk = tier[batch.start : batch.end]
    return sum(seg.occupied for seg in chunk), sum(seg.live for seg in chunk)


def replay(instance: EpochInstance, schedule: Iterable[Batch], require_complete: bool = True) -> dict:
    """Validate prefix order, shadow-space capacity, accounting, and cost."""
    next_index = [0, 0]
    free = list(instance.free)
    events: list[dict] = []
    total_cost = 0
    schedule_tuple = tuple(schedule)
    for epoch_index, batch in enumerate(schedule_tuple):
        source = batch.source
        target = 1 - source
        if batch.start != next_index[source]:
            raise ValueError(
                f"non-prefix batch at epoch {epoch_index}: expected start "
                f"{next_index[source]}, got {batch.start}"
            )
        occupied, live = batch_totals(instance, batch)
        if free[target] < live:
            raise ValueError(
                f"insufficient shadow space at epoch {epoch_index}: "
                f"target={target}, need={live}, free={free[target]}"
            )
        before = tuple(free)
        free[target] -= live
        shadow = tuple(free)
        # Reclamation is after payload durability and the atomic commit.
        free[source] += occupied
        next_index[source] = batch.end
        cost = batch_cost(live, instance.quantum, instance.commit_bytes)
        total_cost += cost
        events.append(
            {
                "epoch": epoch_index,
                "source": source,
                "start": batch.start,
                "end": batch.end,
                "occupied": occupied,
                "live": live,
                "before": before,
                "shadow": shadow,
                "after": tuple(free),
                "cost": cost,
            }
        )
    complete = tuple(next_index) == instance.lengths
    if require_complete and not complete:
        raise ValueError("schedule is not complete")
    expected = instance.free_at(*next_index)
    if tuple(free) != expected:
        raise AssertionError("incremental and prefix-identity free-space accounting disagree")
    live_total = instance.total_live
    return {
        "complete": complete,
        "processed": tuple(next_index),
        "free": tuple(free),
        "cost": total_cost,
        "write_amplification": None if live_total == 0 else total_cost / live_total,
        "events": events,
    }


def lower_bound(instance: EpochInstance) -> int:
    """Per-source one-epoch lower bound, valid for every complete schedule."""
    total = 0
    for source in (0, 1):
        if instance.tiers[source]:
            total += batch_cost(
                sum(seg.live for seg in instance.tiers[source]),
                instance.quantum,
                instance.commit_bytes,
            )
    return total


def one_epoch_per_source_orders(instance: EpochInstance) -> tuple[tuple[Batch, ...], ...]:
    """Return complete one-epoch-per-nonempty-source orders that are feasible."""
    batches = {
        source: Batch(source, 0, len(instance.tiers[source]))
        for source in (0, 1)
        if instance.tiers[source]
    }
    candidates: list[tuple[Batch, ...]] = []
    if not batches:
        return ((),)
    if len(batches) == 1:
        candidates.append(tuple(batches.values()))
    else:
        candidates.extend(((batches[0], batches[1]), (batches[1], batches[0])))
    feasible: list[tuple[Batch, ...]] = []
    for schedule in candidates:
        try:
            replay(instance, schedule)
        except ValueError:
            continue
        feasible.append(schedule)
    return tuple(feasible)


def serialize_instance(instance: EpochInstance) -> dict:
    return {
        "label": instance.label,
        "free": list(instance.free),
        "quantum": instance.quantum,
        "commit_bytes": instance.commit_bytes,
        "tiers": [
            [
                {
                    "occupied": seg.occupied,
                    "live": seg.live,
                    "birth": seg.birth,
                    "name": seg.name,
                }
                for seg in tier
            ]
            for tier in instance.tiers
        ],
    }


def deserialize_instance(payload: dict) -> EpochInstance:
    tiers: list[tuple[Segment, ...]] = []
    for tier in payload["tiers"]:
        tiers.append(tuple(Segment(**item) for item in tier))
    return EpochInstance(
        (tiers[0], tiers[1]),
        tuple(payload["free"]),
        int(payload["quantum"]),
        int(payload["commit_bytes"]),
        str(payload.get("label", "")),
    )


def serialize_schedule(schedule: Sequence[Batch]) -> list[dict]:
    return [
        {"source": batch.source, "start": batch.start, "end": batch.end}
        for batch in schedule
    ]


def deserialize_schedule(payload: Sequence[dict]) -> tuple[Batch, ...]:
    return tuple(Batch(int(x["source"]), int(x["start"]), int(x["end"])) for x in payload)
