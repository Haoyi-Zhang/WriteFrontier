"""Crash-prefix checker for recovery-epoch commit ordering.

The checker models durable payload extents and checksummed atomic commit
records.  It does not emulate sectors, controllers, filesystems, or power loss.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from epoch_model import Batch, EpochInstance, batch_totals, replay


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    schedules: int
    batches: int
    normal_boundaries: int
    normal_failures: int
    mutation_runs: int
    mutation_boundaries: int
    mutation_runs_detected: int
    mutation_failures: int
    all_dead_schedules: int
    mutation_classes: dict[str, dict[str, int]]

    def as_dict(self) -> dict:
        return {
            "schedules": self.schedules,
            "batches": self.batches,
            "normal_boundaries": self.normal_boundaries,
            "normal_failures": self.normal_failures,
            "mutation_runs": self.mutation_runs,
            "mutation_boundaries": self.mutation_boundaries,
            "mutation_runs_detected": self.mutation_runs_detected,
            "mutation_failures": self.mutation_failures,
            "all_dead_schedules": self.all_dead_schedules,
            "mutation_classes": self.mutation_classes,
        }


def _tokens(instance: EpochInstance) -> dict[tuple[int, int], tuple[str, ...]]:
    result: dict[tuple[int, int], tuple[str, ...]] = {}
    for source in (0, 1):
        for index, seg in enumerate(instance.tiers[source]):
            result[(source, index)] = tuple(
                f"s{source}-g{index}-u{unit}" for unit in range(seg.live)
            )
    return result


def _recovery_ok(
    expected: set[str],
    pointers: dict[tuple[int, int], str],
    durable: dict[str, tuple[str, ...]],
    commit_valid: bool = True,
    precommit_pointers: dict[tuple[int, int], str] | None = None,
) -> bool:
    selected = pointers if commit_valid or precommit_pointers is None else precommit_pointers
    recovered: list[str] = []
    try:
        for key in sorted(selected):
            recovered.extend(durable[selected[key]])
    except KeyError:
        return False
    return len(recovered) == len(set(recovered)) and set(recovered) == expected


def check_schedule(
    instance: EpochInstance,
    schedule: Iterable[Batch],
    mutation: str | None = None,
) -> dict:
    """Inspect every modeled crash boundary of one complete legal schedule."""
    schedule = tuple(schedule)
    replay(instance, schedule)
    token_map = _tokens(instance)
    durable: dict[str, tuple[str, ...]] = {}
    pointers: dict[tuple[int, int], str] = {}
    for key, values in token_map.items():
        extent = f"old-{key[0]}-{key[1]}"
        durable[extent] = values
        pointers[key] = extent
    expected = {token for values in token_map.values() for token in values}
    boundaries = 0
    failures = 0
    first_failure: str | None = None

    def checkpoint(label: str, commit_valid: bool = True, precommit=None) -> None:
        nonlocal boundaries, failures, first_failure
        boundaries += 1
        if not _recovery_ok(expected, pointers, durable, commit_valid, precommit):
            failures += 1
            if first_failure is None:
                first_failure = label

    checkpoint("initial")
    for epoch, batch in enumerate(schedule):
        keys = [(batch.source, index) for index in range(batch.start, batch.end)]
        new_extents = {key: f"new-{epoch}-{key[0]}-{key[1]}" for key in keys}
        volatile: dict[tuple[int, int], list[str]] = {key: [] for key in keys}
        precommit = dict(pointers)
        if mutation == "publish-before-flush":
            for key in keys:
                pointers[key] = new_extents[key]
            checkpoint(f"epoch {epoch}: premature commit")
        copied = 0
        for key in keys:
            for token in token_map[key]:
                volatile[key].append(token)
                copied += 1
                checkpoint(f"epoch {epoch}: volatile copy {copied}")
        persisted = {key: tuple(values) for key, values in volatile.items()}
        if mutation == "truncate-persisted-payload":
            for key in reversed(keys):
                if persisted[key]:
                    persisted[key] = persisted[key][:-1]
                    break
        for key in keys:
            durable[new_extents[key]] = persisted[key]
        checkpoint(f"epoch {epoch}: payload flush")
        if mutation == "reclaim-before-commit":
            for key in keys:
                durable.pop(precommit[key], None)
            checkpoint(f"epoch {epoch}: premature reclaim")
        if mutation == "torn-commit-reclaim":
            # A checksum failure makes recovery ignore the new mapping.
            for key in keys:
                pointers[key] = new_extents[key]
            checkpoint(f"epoch {epoch}: torn commit", commit_valid=False, precommit=precommit)
            for key in keys:
                durable.pop(precommit[key], None)
            checkpoint(
                f"epoch {epoch}: reclaim after torn commit",
                commit_valid=False,
                precommit=precommit,
            )
            # Continue with a valid commit so later epochs remain defined.
        for key in keys:
            pointers[key] = new_extents[key]
        checkpoint(f"epoch {epoch}: atomic valid commit")
        for key in keys:
            durable.pop(precommit[key], None)
        checkpoint(f"epoch {epoch}: source reclaim")
    return {
        "mutation": mutation,
        "boundaries": boundaries,
        "failures": failures,
        "detected": failures > 0,
        "first_failure": first_failure,
    }


def check_corpus(corpus: Iterable[tuple[EpochInstance, tuple[Batch, ...]]]) -> RecoverySummary:
    schedules = 0
    batches = 0
    normal_boundaries = normal_failures = 0
    mutation_runs = mutation_boundaries = mutation_runs_detected = mutation_failures = 0
    all_dead_schedules = 0
    mutations = (
        "publish-before-flush",
        "reclaim-before-commit",
        "truncate-persisted-payload",
        "torn-commit-reclaim",
    )
    mutation_classes = {
        mutation: {
            "runs": 0,
            "boundaries": 0,
            "detected_runs": 0,
            "failures": 0,
            "skipped": 0,
        }
        for mutation in mutations
    }
    for instance, schedule in corpus:
        schedules += 1
        batches += len(schedule)
        all_dead_schedules += int(instance.total_live == 0)
        normal = check_schedule(instance, schedule)
        normal_boundaries += normal["boundaries"]
        normal_failures += normal["failures"]
        for mutation in mutations:
            # Payload truncation is a retained-token loss mutation.  It has no
            # payload to truncate on an all-dead schedule, so those cases are
            # recorded as skipped rather than reclassified as metadata errors.
            if mutation == "truncate-persisted-payload" and instance.total_live == 0:
                mutation_classes[mutation]["skipped"] += 1
                continue
            out = check_schedule(instance, schedule, mutation)
            mutation_runs += 1
            mutation_boundaries += out["boundaries"]
            mutation_failures += out["failures"]
            mutation_runs_detected += int(out["detected"])
            mutation_classes[mutation]["runs"] += 1
            mutation_classes[mutation]["boundaries"] += out["boundaries"]
            mutation_classes[mutation]["failures"] += out["failures"]
            mutation_classes[mutation]["detected_runs"] += int(out["detected"])
    return RecoverySummary(
        schedules,
        batches,
        normal_boundaries,
        normal_failures,
        mutation_runs,
        mutation_boundaries,
        mutation_runs_detected,
        mutation_failures,
        all_dead_schedules,
        mutation_classes,
    )
