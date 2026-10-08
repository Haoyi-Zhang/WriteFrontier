#!/usr/bin/env python3
"""Deterministic bounded campaign for recovery-epoch frontiers.

The campaign is split into four resumable exact-grid parts.  Each part is
independently replaceable.  Aggregation refuses missing/duplicate case IDs and
recomputes every table used by the paper.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import resource
import statistics
import random
import sys
import time
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Iterable, Sequence

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
sys.path.insert(0, str(SRC))

from epoch_dp import (  # noqa: E402
    SearchBudgetExceeded,
    brute_force_oracle,
    confluence_audit,
    make_blocking_certificate,
    scan_feasibility,
    solve_normal_form,
    solve_unrestricted,
)
from epoch_model import (  # noqa: E402
    Batch,
    EpochInstance,
    Segment,
    lower_bound,
    one_epoch_per_source_orders,
    replay,
    serialize_instance,
    serialize_schedule,
)
from epoch_policies import all_policies  # noqa: E402
from independent_audit import solve_raw  # noqa: E402
from epoch_recovery import check_corpus, check_schedule  # noqa: E402
from trace_model import make_trace_instances, read_cloudphysics, read_twitter  # noqa: E402

PARTS = 4
MAX_FREE = 6
QUANTUM = 4
COMMIT = 1
SEGMENT_TYPES: tuple[tuple[int, int], ...] = (
    (1, 0),
    (1, 1),
    (2, 0),
    (2, 1),
    (2, 2),
    (3, 1),
    (3, 2),
    (3, 3),
)
POLICIES = (
    "lru-tiered-proxy",
    "leveled-proxy",
    "size-tiered-proxy",
    "gain-per-write",
)
GRID_FIELDS = [
    "case_id",
    "pattern_id",
    "f0",
    "f1",
    "final_fit",
    "status",
    "cost",
    "lower_bound",
    "batches",
    "total_live",
    "solver_states",
    "solver_transitions",
    "oracle_status",
    "oracle_cost",
    "oracle_states",
    "oracle_transitions",
    "independent_status",
    "independent_cost",
    "independent_states",
    "independent_transitions",
    "scan_status",
    "scan_steps",
    "one_epoch_optimum",
]
for policy in POLICIES:
    GRID_FIELDS.extend((f"{policy}_status", f"{policy}_cost"))


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _swap_kib() -> int:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmSwap:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def enforce_resource_contract() -> None:
    """Apply the declared one-worker, memory, CPU, and no-swap contract."""
    if hasattr(os, "sched_getaffinity") and hasattr(os, "sched_setaffinity"):
        available = os.sched_getaffinity(0)
        if available:
            os.sched_setaffinity(0, {min(available)})
    three_gib = 3 * 1024**3
    soft_as, hard_as = resource.getrlimit(resource.RLIMIT_AS)
    new_hard_as = three_gib if hard_as in (-1, resource.RLIM_INFINITY) else min(hard_as, three_gib)
    resource.setrlimit(resource.RLIMIT_AS, (new_hard_as, new_hard_as))
    cpu_limit = 45 * 60
    soft_cpu, hard_cpu = resource.getrlimit(resource.RLIMIT_CPU)
    new_hard_cpu = cpu_limit if hard_cpu in (-1, resource.RLIM_INFINITY) else min(hard_cpu, cpu_limit)
    resource.setrlimit(resource.RLIMIT_CPU, (new_hard_cpu, new_hard_cpu))
    if _swap_kib() != 0:
        raise RuntimeError("no-swap contract violated before campaign start")


def _runtime(start_wall: float, start_cpu: float) -> dict:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "wall_seconds": round(time.perf_counter() - start_wall, 6),
        "cpu_seconds": round(time.process_time() - start_cpu, 6),
        "max_rss_kib": int(usage.ru_maxrss),
        "swap_kib": _swap_kib(),
    }


def _sequences() -> list[tuple[tuple[int, int], ...]]:
    result: list[tuple[tuple[int, int], ...]] = []
    for length in (1, 2):
        result.extend(tuple(items) for items in product(SEGMENT_TYPES, repeat=length))
    return result


SEQUENCES = _sequences()
PATTERN_COUNT = len(SEQUENCES) ** 2
TOTAL_CASES = PATTERN_COUNT * (MAX_FREE + 1) ** 2


def pattern_types(pattern_id: int) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    if not 0 <= pattern_id < PATTERN_COUNT:
        raise ValueError("pattern ID outside campaign")
    return SEQUENCES[pattern_id // len(SEQUENCES)], SEQUENCES[pattern_id % len(SEQUENCES)]


def pattern_tiers(pattern_id: int) -> tuple[tuple[Segment, ...], tuple[Segment, ...]]:
    raw0, raw1 = pattern_types(pattern_id)
    tier0 = tuple(
        Segment(occupied, live, birth=2 * i, name=f"p{pattern_id}-0-{i}")
        for i, (occupied, live) in enumerate(raw0)
    )
    tier1 = tuple(
        Segment(occupied, live, birth=2 * i + 1, name=f"p{pattern_id}-1-{i}")
        for i, (occupied, live) in enumerate(raw1)
    )
    return tier0, tier1


def case_id(pattern_id: int, f0: int, f1: int) -> int:
    return pattern_id * (MAX_FREE + 1) ** 2 + f0 * (MAX_FREE + 1) + f1


def _as_int(value: str) -> int | None:
    return None if value == "" else int(value)


def run_grid_part(part: int, out: Path) -> dict:
    if not 0 <= part < PARTS:
        raise ValueError("grid part outside range")
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    rows: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    solver_disagreements = 0
    brute_disagreements = 0
    brute_cases = 0
    independent_disagreements = 0
    normal_form_violations = 0
    scan_disagreements = 0
    for pattern_id in range(part, PATTERN_COUNT, PARTS):
        tiers = pattern_tiers(pattern_id)
        for f0 in range(MAX_FREE + 1):
            for f1 in range(MAX_FREE + 1):
                instance = EpochInstance(
                    tiers,
                    (f0, f1),
                    QUANTUM,
                    COMMIT,
                    label=f"pattern-{pattern_id}-free-{f0}-{f1}",
                )
                solution = solve_normal_form(instance)
                oracle = solve_unrestricted(instance)
                independent = solve_raw(
                    tuple((seg.occupied, seg.live) for seg in tiers[0]),
                    tuple((seg.occupied, seg.live) for seg in tiers[1]),
                    (f0, f1),
                    QUANTUM,
                    COMMIT,
                )
                scan = scan_feasibility(instance)
                if (solution.feasible, solution.cost) != (independent.feasible, independent.cost):
                    independent_disagreements += 1
                if solution.feasible != scan.feasible:
                    scan_disagreements += 1
                if (solution.status, solution.cost) != (oracle.status, oracle.cost):
                    solver_disagreements += 1
                if any(
                    solution.schedule[k].source == solution.schedule[k + 1].source
                    for k in range(max(0, len(solution.schedule) - 1))
                ):
                    normal_form_violations += 1
                # One exhaustive no-memo check per pattern at the maximal box corner.
                if f0 == MAX_FREE and f1 == MAX_FREE:
                    brute_cases += 1
                    brute = brute_force_oracle(instance)
                    if (solution.status, solution.cost) != (brute.status, brute.cost):
                        brute_disagreements += 1
                policy_results = {result.policy: result for result in all_policies(instance)}
                row: dict[str, object] = {
                    "case_id": case_id(pattern_id, f0, f1),
                    "pattern_id": pattern_id,
                    "f0": f0,
                    "f1": f1,
                    "final_fit": int(instance.final_fits()),
                    "status": solution.status,
                    "cost": "" if solution.cost is None else solution.cost,
                    "lower_bound": solution.lower_bound,
                    "batches": solution.batches,
                    "total_live": instance.total_live,
                    "solver_states": solution.states,
                    "solver_transitions": solution.transitions,
                    "oracle_status": oracle.status,
                    "oracle_cost": "" if oracle.cost is None else oracle.cost,
                    "oracle_states": oracle.states,
                    "oracle_transitions": oracle.transitions,
                    "independent_status": independent.status,
                    "independent_cost": "" if independent.cost is None else independent.cost,
                    "independent_states": independent.states,
                    "independent_transitions": independent.transitions,
                    "scan_status": scan.status,
                    "scan_steps": scan.steps,
                    "one_epoch_optimum": int(
                        solution.feasible
                        and solution.cost == solution.lower_bound
                        and bool(one_epoch_per_source_orders(instance))
                    ),
                }
                for policy in POLICIES:
                    result = policy_results[policy]
                    row[f"{policy}_status"] = result.status
                    row[f"{policy}_cost"] = "" if result.cost is None else result.cost
                rows.append(row)
                status_counts[solution.status] += 1
    rows.sort(key=lambda row: int(row["case_id"]))
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"grid-{part}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GRID_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "part": part,
        "patterns": len(range(part, PATTERN_COUNT, PARTS)),
        "cases": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "solver_disagreements": solver_disagreements,
        "brute_cases": brute_cases,
        "brute_disagreements": brute_disagreements,
        "independent_disagreements": independent_disagreements,
        "normal_form_violations": normal_form_violations,
        "scan_disagreements": scan_disagreements,
        "runtime": _runtime(start_wall, start_cpu),
    }
    _json(out / f"grid-{part}.json", summary)
    return summary


def _read_grid(out: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for part in range(PARTS):
        path = out / f"grid-{part}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing grid part: {path}")
        with path.open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    ids = [int(row["case_id"]) for row in rows]
    if len(ids) != TOTAL_CASES or len(set(ids)) != TOTAL_CASES:
        raise ValueError(
            f"incomplete or duplicate grid: got {len(ids)} rows and {len(set(ids))} unique IDs; "
            f"expected {TOTAL_CASES}"
        )
    if min(ids) != 0 or max(ids) != TOTAL_CASES - 1:
        raise ValueError("case ID range is incomplete")
    rows.sort(key=lambda row: int(row["case_id"]))
    return rows


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _frontier_choice(rows: Sequence[dict[str, str]]) -> dict[str, str]:
    feasible = [row for row in rows if row["status"] == "feasible"]
    if not feasible:
        raise ValueError("campaign pattern has no feasible point inside declared box")
    return min(
        feasible,
        key=lambda row: (
            int(row["f0"]) + int(row["f1"]),
            int(row["cost"]),
            int(row["f0"]),
            int(row["f1"]),
        ),
    )


def aggregate_grid(out: Path) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    rows = _read_grid(out)
    by_pattern: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_pattern[int(row["pattern_id"])].append(row)
    if len(by_pattern) != PATTERN_COUNT:
        raise ValueError("missing pattern IDs")
    confluence_states = 0
    confluence_edges = 0
    confluence_violations = 0
    confluence_status_disagreements = 0
    for row in rows:
        pattern = int(row["pattern_id"])
        instance = EpochInstance(
            pattern_tiers(pattern),
            (int(row["f0"]), int(row["f1"])),
            QUANTUM,
            COMMIT,
        )
        audit = confluence_audit(instance)
        # Sum nonterminal viable prefix-state instances, not terminal states.
        confluence_states += audit["viable_states"]
        confluence_edges += audit["legal_edges_from_viable_states"]
        confluence_violations += len(audit["violations"])
        confluence_status_disagreements += int(
            audit["initial_feasible"] != (row["status"] == "feasible")
        )
    feasible = [row for row in rows if row["status"] == "feasible"]
    final_fit_infeasible = [
        row
        for row in rows
        if row["final_fit"] == "1" and row["status"] != "feasible"
    ]
    unequal_optimum = [
        row
        for row in feasible
        if int(row["cost"]) > int(row["lower_bound"])
    ]
    selected = [_frontier_choice(by_pattern[pattern]) for pattern in range(PATTERN_COUNT)]
    frontier_path = out / "frontier-cases.csv"
    with frontier_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=GRID_FIELDS)
        writer.writeheader()
        writer.writerows(selected)

    baseline_rows: list[dict[str, object]] = []
    for policy in POLICIES:
        completed: list[tuple[int, int]] = []
        blocked = 0
        optimal = 0
        ratios: list[float] = []
        for row in selected:
            optimum = int(row["cost"])
            status = row[f"{policy}_status"]
            if status != "complete":
                blocked += 1
                continue
            cost = int(row[f"{policy}_cost"])
            completed.append((cost, optimum))
            ratios.append(cost / optimum)
            optimal += int(cost == optimum)
        baseline_rows.append(
            {
                "policy": policy,
                "frontier_instances": len(selected),
                "completed": len(completed),
                "blocked": blocked,
                "completion_rate": len(completed) / len(selected),
                "optimal_among_completed": optimal,
                "optimal_fraction_among_completed": (
                    optimal / len(completed) if completed else None
                ),
                "median_cost_over_opt": _quantile(ratios, 0.5),
                "p95_cost_over_opt": _quantile(ratios, 0.95),
                "max_cost_over_opt": max(ratios) if ratios else None,
            }
        )
    with (out / "baseline-summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(baseline_rows[0]))
        writer.writeheader()
        writer.writerows(baseline_rows)

    slack_records: list[dict[str, object]] = []
    per_delta: dict[int, list[tuple[float, float, bool]]] = defaultdict(list)
    for pattern, pattern_rows in sorted(by_pattern.items()):
        feasible_rows = [row for row in pattern_rows if row["status"] == "feasible"]
        rmin = min(int(row["f0"]) + int(row["f1"]) for row in feasible_rows)
        for delta in range(0, 7):
            admitted = [
                row
                for row in feasible_rows
                if int(row["f0"]) + int(row["f1"]) <= rmin + delta
            ]
            chosen = min(
                admitted,
                key=lambda row: (
                    int(row["cost"]),
                    int(row["f0"]) + int(row["f1"]),
                    int(row["f0"]),
                ),
            )
            cost = int(chosen["cost"])
            lb = int(chosen["lower_bound"])
            live = int(chosen["total_live"])
            tax = 1.0 if lb == 0 else cost / lb
            wa = math.nan if live == 0 else cost / live
            per_delta[delta].append((tax, wa, cost == lb))
    for delta in range(0, 7):
        values = per_delta[delta]
        taxes = [item[0] for item in values]
        was = [item[1] for item in values if not math.isnan(item[1])]
        slack_records.append(
            {
                "extra_total_reserve_units": delta,
                "patterns": len(values),
                "lower_bound_fraction": sum(item[2] for item in values) / len(values),
                "median_cost_over_lower_bound": _quantile(taxes, 0.5),
                "p95_cost_over_lower_bound": _quantile(taxes, 0.95),
                "max_cost_over_lower_bound": max(taxes),
                "median_physical_over_live": _quantile(was, 0.5),
                "p95_physical_over_live": _quantile(was, 0.95),
                "max_physical_over_live": max(was) if was else None,
            }
        )
    with (out / "slack-curve.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(slack_records[0]))
        writer.writeheader()
        writer.writerows(slack_records)

    # Objective and boundary witnesses are reconstructed, replayed, and stored.
    variation_tiers = (
        (Segment(1, 1, 0, "a"), Segment(1, 1, 2, "b")),
        (Segment(1, 1, 1, "c"), Segment(1, 1, 3, "d")),
    )
    variation = EpochInstance(variation_tiers, (2, 2), QUANTUM, COMMIT, "unequal-legal-costs")
    optimum = solve_normal_form(variation)
    segmented = (
        Batch(0, 0, 1),
        Batch(1, 0, 1),
        Batch(0, 1, 2),
        Batch(1, 1, 2),
    )
    segmented_replay = replay(variation, segmented)
    if not optimum.feasible or not optimum.cost or optimum.cost >= segmented_replay["cost"]:
        raise AssertionError("objective-variation witness failed")

    max_tax_row = max(
        unequal_optimum,
        key=lambda row: int(row["cost"]) / max(1, int(row["lower_bound"])),
    )
    max_tax_pattern = int(max_tax_row["pattern_id"])
    max_tax_instance = EpochInstance(
        pattern_tiers(max_tax_pattern),
        (int(max_tax_row["f0"]), int(max_tax_row["f1"])),
        QUANTUM,
        COMMIT,
        "max-grid-fragmentation-tax",
    )
    max_tax_solution = solve_normal_form(max_tax_instance)

    blocked_witness = None
    for row in selected:
        for policy in POLICIES:
            if row[f"{policy}_status"] == "blocked":
                blocked_witness = (row, policy)
                break
        if blocked_witness:
            break
    witness_payload = {
        "unequal_legal_costs": {
            "instance": serialize_instance(variation),
            "optimal": optimum.as_dict(),
            "more_fragmented_legal_schedule": serialize_schedule(segmented),
            "more_fragmented_cost": segmented_replay["cost"],
        },
        "max_grid_fragmentation_tax": {
            "instance": serialize_instance(max_tax_instance),
            "solution": max_tax_solution.as_dict(),
        },
        "blocked_policy": None,
    }

    # Preserve one independently checkable ordered-model obstruction.  This is
    # distinct from the arbitrary-selection closed-set certificates.
    blocking_row = min(final_fit_infeasible, key=lambda row: int(row["case_id"]))
    blocking_pattern = int(blocking_row["pattern_id"])
    blocking_instance = EpochInstance(
        pattern_tiers(blocking_pattern),
        (int(blocking_row["f0"]), int(blocking_row["f1"])),
        QUANTUM,
        COMMIT,
        "ordered-prefix-blocking-witness",
    )
    blocking_scan = scan_feasibility(blocking_instance)
    if blocking_scan.feasible:
        raise AssertionError("selected blocking witness became feasible")
    ordered_certificate = make_blocking_certificate(blocking_instance, blocking_scan)
    _json(out / "ordered-blocking-certificate.json", ordered_certificate)
    witness_payload["ordered_blocking_certificate"] = {
        "case_id": int(blocking_row["case_id"]),
        "file": "ordered-blocking-certificate.json",
    }
    if blocked_witness:
        row, policy = blocked_witness
        pid = int(row["pattern_id"])
        instance = EpochInstance(
            pattern_tiers(pid),
            (int(row["f0"]), int(row["f1"])),
            QUANTUM,
            COMMIT,
            "exact-feasible-policy-blocked",
        )
        result = {item.policy: item for item in all_policies(instance)}[policy]
        witness_payload["blocked_policy"] = {
            "policy": policy,
            "instance": serialize_instance(instance),
            "exact": solve_normal_form(instance).as_dict(),
            "policy_result": result.as_dict(),
        }
    _json(out / "witnesses.json", witness_payload)

    corner_rows = [
        row for row in rows
        if int(row["f0"]) == MAX_FREE and int(row["f1"]) == MAX_FREE
    ]
    if len(corner_rows) != PATTERN_COUNT:
        raise AssertionError("maximal reserve corner is incomplete")

    summary = {
        "domain": {
            "segment_types": [list(item) for item in SEGMENT_TYPES],
            "ordered_sequence_lengths": [1, 2],
            "patterns": PATTERN_COUNT,
            "free_space_box": [0, MAX_FREE],
            "cases": TOTAL_CASES,
            "quantum": QUANTUM,
            "commit_bytes": COMMIT,
        },
        "no_memo_audit": {
            "free": [MAX_FREE, MAX_FREE],
            "cases": len(corner_rows),
            "feasible_cases": sum(row["status"] == "feasible" for row in corner_rows),
            "optimum_at_lower_bound": sum(
                row["status"] == "feasible" and row["cost"] == row["lower_bound"]
                for row in corner_rows
            ),
            "description": (
                "one no-memory exhaustive search per ordered pattern at the "
                "maximal declared reserve corner; these are not minimal-reserve "
                "frontier points"
            ),
        },
        "feasible_cases": len(feasible),
        "infeasible_cases": TOTAL_CASES - len(feasible),
        "final_fit_but_infeasible": len(final_fit_infeasible),
        "feasible_with_fragmentation_tax": len(unequal_optimum),
        "solver_oracle_disagreements": sum(
            int(row["status"] != row["oracle_status"] or row["cost"] != row["oracle_cost"])
            for row in rows
        ),
        "independent_raw_disagreements": sum(
            int(
                (row["status"] == "feasible") != (row["independent_status"] == "feasible")
                or (row["status"] == "feasible" and row["cost"] != row["independent_cost"])
            )
            for row in rows
        ),
        "linear_scan_status_disagreements": sum(
            int((row["status"] == "feasible") != (row["scan_status"] == "feasible"))
            for row in rows
        ),
        "confluence_audit": {
            # Retain the legacy field name for the nonterminal instance count.
            "viable_states": confluence_states,
            "legal_edges_from_viable_states": confluence_edges,
            "violations": confluence_violations,
            "status_disagreements": confluence_status_disagreements,
        },
        "frontier_patterns": len(selected),
        "frontier_optimum_at_lower_bound": sum(
            int(row["cost"] == row["lower_bound"]) for row in selected
        ),
        "objective_variation_witness": {
            "optimal_cost": optimum.cost,
            "fragmented_legal_cost": segmented_replay["cost"],
        },
        "baseline_summary": baseline_rows,
        "slack_curve": slack_records,
        "runtime": _runtime(start_wall, start_cpu),
    }
    _json(out / "grid-summary.json", summary)
    return summary


def run_trace(out: Path) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    datasets = [
        {
            "name": "cloudphysics-prefix",
            "path": HERE / "inputs" / "cloudphysics-prefix.csv",
            "reader": read_cloudphysics,
            "target_bytes": 65_536,
            "allocation_unit": 512,
            "page_bytes": 4096,
            "commit_bytes": 512,
        },
        {
            "name": "twitter-cluster015-prefix",
            "path": HERE / "inputs" / "twitter-cluster015-prefix.csv",
            "reader": read_twitter,
            "target_bytes": 2_048,
            "allocation_unit": 64,
            "page_bytes": 4096,
            "commit_bytes": 64,
        },
    ]
    records: list[dict[str, object]] = []
    certificates: list[dict] = []
    for dataset in datasets:
        requests = dataset["reader"](dataset["path"])
        instances = make_trace_instances(
            requests,
            dataset_id=dataset["name"],
            window_rows=64,
            target_bytes=int(dataset["target_bytes"]),
            allocation_unit=int(dataset["allocation_unit"]),
            page_bytes=int(dataset["page_bytes"]),
            commit_bytes=int(dataset["commit_bytes"]),
            extra_slacks=(0, int(dataset["page_bytes"]) // int(dataset["allocation_unit"])),
        )
        for item in instances:
            instance: EpochInstance = item.pop("instance")
            exact = solve_normal_form(instance)
            if not exact.feasible:
                raise AssertionError("trace instance constructed from a feasible reserve became infeasible")
            policy_results = {result.policy: result for result in all_policies(instance)}
            exact_cost_bytes = exact.cost * int(dataset["allocation_unit"])
            raw_live_bytes = int(item["raw_live_bytes"])
            retained_allocation_bytes = int(item["retained_allocation_bytes"])
            row: dict[str, object] = {
                "dataset": dataset["name"],
                **item,
                "free0_units": instance.free[0],
                "free1_units": instance.free[1],
                "allocation_unit_bytes": dataset["allocation_unit"],
                "page_bytes": dataset["page_bytes"],
                "commit_bytes": dataset["commit_bytes"],
                "exact_cost_units": exact.cost,
                "exact_cost_bytes": exact_cost_bytes,
                "exact_batches": exact.batches,
                "lower_bound_units": exact.lower_bound,
                "exact_over_lower_bound": exact.cost / exact.lower_bound if exact.lower_bound else 1.0,
                "exact_physical_over_raw_live": (
                    None if raw_live_bytes == 0 else exact_cost_bytes / raw_live_bytes
                ),
                "exact_physical_over_retained_allocation": (
                    None
                    if retained_allocation_bytes == 0
                    else exact_cost_bytes / retained_allocation_bytes
                ),
            }
            for policy in POLICIES:
                result = policy_results[policy]
                row[f"{policy}_status"] = result.status
                row[f"{policy}_cost_units"] = result.cost
                row[f"{policy}_over_exact"] = (
                    None if result.cost is None else result.cost / exact.cost
                )
            records.append(row)
            certificates.append(
                {
                    "dataset": dataset["name"],
                    "window": item["window_index"],
                    "extra_slack_units": item["extra_slack_units"],
                    "instance": serialize_instance(instance),
                    "exact": exact.as_dict(),
                    "policies": [result.as_dict() for result in policy_results.values()],
                }
            )
    fields = list(records[0])
    with (out / "trace-results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    _json(out / "trace-certificates.json", certificates)
    summary = {
        "rows": len(records),
        "datasets": {
            name: sum(record["dataset"] == name for record in records)
            for name in sorted({str(record["dataset"]) for record in records})
        },
        "policy_blocked_counts": {
            policy: sum(record[f"{policy}_status"] != "complete" for record in records)
            for policy in POLICIES
        },
        "runtime": _runtime(start_wall, start_cpu),
    }
    _json(out / "trace-summary.json", summary)
    return summary


def run_recovery(out: Path) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    frontier_path = out / "frontier-cases.csv"
    if not frontier_path.exists():
        raise FileNotFoundError("aggregate the exact grid before recovery checks")
    with frontier_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    corpus: list[tuple[EpochInstance, tuple[Batch, ...]]] = []
    # Deterministic spread across all pattern IDs, bounded to 1,024 schedules.
    stride = max(1, len(rows) // 1024)
    for row in rows[::stride][:1024]:
        pattern = int(row["pattern_id"])
        instance = EpochInstance(
            pattern_tiers(pattern),
            (int(row["f0"]), int(row["f1"])),
            QUANTUM,
            COMMIT,
            label=f"recovery-pattern-{pattern}",
        )
        solution = solve_normal_form(instance)
        if not solution.feasible:
            raise AssertionError("frontier recovery corpus includes an infeasible instance")
        corpus.append((instance, solution.schedule))
    summary = check_corpus(corpus)
    if summary.normal_failures:
        raise AssertionError("correct recovery protocol failed")
    if summary.mutation_runs_detected != summary.mutation_runs:
        raise AssertionError("a negative-control mutation escaped all crash boundaries")
    # Preserve one detailed representative for audit.
    example_instance, example_schedule = corpus[len(corpus) // 2]
    example = {
        "instance": serialize_instance(example_instance),
        "schedule": serialize_schedule(example_schedule),
        "normal": check_schedule(example_instance, example_schedule),
        "mutations": [
            check_schedule(example_instance, example_schedule, mutation)
            for mutation in (
                "publish-before-flush",
                "reclaim-before-commit",
                "truncate-persisted-payload",
                "torn-commit-reclaim",
            )
            if mutation != "truncate-persisted-payload" or example_instance.total_live > 0
        ],
    }
    payload = summary.as_dict()
    payload["example"] = example
    payload["runtime"] = _runtime(start_wall, start_cpu)
    _json(out / "recovery-summary.json", payload)
    return payload


def run_sensitivity(out: Path) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    with (out / "frontier-cases.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    stride = max(1, len(rows) // 1024)
    sample = rows[::stride][:1024]
    configurations = (
        (1, 0, "exact-byte-only"),
        (4, 0, "rounding-only"),
        (1, 1, "commit-only"),
        (4, 1, "rounding-plus-commit"),
        (8, 1, "larger-quantum"),
        (4, 2, "larger-commit"),
    )
    records: list[dict[str, object]] = []
    for quantum, commit, label in configurations:
        ratios: list[float] = []
        costs: list[int] = []
        at_lb = 0
        for row in sample:
            pattern = int(row["pattern_id"])
            instance = EpochInstance(
                pattern_tiers(pattern),
                (int(row["f0"]), int(row["f1"])),
                quantum,
                commit,
            )
            solution = solve_normal_form(instance)
            if not solution.feasible or solution.cost is None:
                raise AssertionError("cost parameters changed feasibility")
            lb = solution.lower_bound
            ratio = 1.0 if lb == 0 else solution.cost / lb
            ratios.append(ratio)
            costs.append(solution.cost)
            at_lb += int(solution.cost == lb)
        records.append(
            {
                "label": label,
                "quantum": quantum,
                "commit_bytes": commit,
                "instances": len(sample),
                "at_lower_bound_fraction": at_lb / len(sample),
                "median_cost_over_lower_bound": _quantile(ratios, 0.5),
                "p95_cost_over_lower_bound": _quantile(ratios, 0.95),
                "max_cost_over_lower_bound": max(ratios),
                "median_cost_units": _quantile([float(x) for x in costs], 0.5),
            }
        )
    with (out / "sensitivity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    payload = {"sample_instances": len(sample), "configurations": records, "runtime": _runtime(start_wall, start_cpu)}
    _json(out / "sensitivity.json", payload)
    return payload



def run_unit_exchange(out: Path) -> dict:
    """Validate the closed-form symmetric unit-exchange frontier."""
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    quantum = 32
    commit = 1
    records: list[dict[str, object]] = []
    disagreements = 0
    for n in (16, 32, 64, 128):
        tiers = (
            tuple(Segment(1, 1, 2 * i, f"u0-{i}") for i in range(n)),
            tuple(Segment(1, 1, 2 * i + 1, f"u1-{i}") for i in range(n)),
        )
        for reserve_each in range(1, min(n, quantum // 2) + 1):
            instance = EpochInstance(
                tiers,
                (reserve_each, reserve_each),
                quantum,
                commit,
                label=f"unit-exchange-n{n}-r{reserve_each}",
            )
            exact = solve_normal_form(instance)
            formula_batches = math.ceil(n / reserve_each) + 1
            formula_cost = formula_batches * (quantum + commit)
            disagreements += int(
                not exact.feasible
                or exact.batches != formula_batches
                or exact.cost != formula_cost
            )
            records.append(
                {
                    "segments_per_tier": n,
                    "reserve_each_tier": reserve_each,
                    "total_reserve": 2 * reserve_each,
                    "quantum": quantum,
                    "commit_bytes": commit,
                    "exact_batches": exact.batches,
                    "formula_batches": formula_batches,
                    "exact_cost": exact.cost,
                    "formula_cost": formula_cost,
                    "physical_over_live": exact.cost / (2 * n),
                    "cost_over_one_epoch_lower_bound": exact.cost / exact.lower_bound,
                }
            )
    with (out / "unit-exchange-frontier.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    payload = {
        "instances": len(records),
        "formula_disagreements": disagreements,
        "quantum": quantum,
        "commit_bytes": commit,
        "n_values": [16, 32, 64, 128],
        "reserve_each_range": [1, 16],
        "runtime": _runtime(start_wall, start_cpu),
    }
    if disagreements:
        raise AssertionError("unit-exchange closed form disagrees with exact solver")
    _json(out / "unit-exchange-summary.json", payload)
    return payload


def _merge_adjacent(schedule: Sequence[Batch]) -> tuple[Batch, ...]:
    merged: list[Batch] = []
    for batch in schedule:
        if merged and merged[-1].source == batch.source and merged[-1].end == batch.start:
            previous = merged.pop()
            merged.append(Batch(previous.source, previous.start, batch.end))
        else:
            merged.append(batch)
    return tuple(merged)


def run_independent_audit(out: Path, cases: int = 20_000) -> dict:
    """Run deterministic cross-implementation and metamorphic controls.

    The raw oracle imports no project model or solver code.  These randomized
    cases extend beyond the exhaustive two-segment campaign but remain a finite
    implementation audit rather than evidence for the handwritten proofs.
    """
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    seed = 20_260_916
    rng = random.Random(seed)
    raw_disagreements = 0
    unrestricted_disagreements = 0
    symmetry_disagreements = 0
    reserve_violations = 0
    scale_violations = 0
    merge_violations = 0
    feasible_cases = 0
    max_lengths = [0, 0]
    raw_states = 0
    raw_transitions = 0

    for case_index in range(cases):
        raw_tiers: list[tuple[tuple[int, int], ...]] = []
        tiers: list[tuple[Segment, ...]] = []
        birth = 0
        for source in (0, 1):
            raw: list[tuple[int, int]] = []
            modeled: list[Segment] = []
            length = rng.randint(0, 4)
            max_lengths[source] = max(max_lengths[source], length)
            for segment_index in range(length):
                occupied = rng.randint(1, 7)
                live = rng.randint(0, occupied)
                raw.append((occupied, live))
                modeled.append(
                    Segment(occupied, live, birth, f"audit-{case_index}-{source}-{segment_index}")
                )
                birth += 1
            raw_tiers.append(tuple(raw))
            tiers.append(tuple(modeled))
        free = (rng.randint(0, 12), rng.randint(0, 12))
        quantum = rng.randint(1, 12)
        commit = rng.randint(0, 5)
        instance = EpochInstance(
            (tiers[0], tiers[1]), free, quantum, commit, f"independent-audit-{case_index}"
        )
        exact = solve_normal_form(instance)
        unrestricted = solve_unrestricted(instance)
        raw = solve_raw(raw_tiers[0], raw_tiers[1], free, quantum, commit)
        raw_states += raw.states
        raw_transitions += raw.transitions
        feasible_cases += int(exact.feasible)
        raw_disagreements += int((exact.feasible, exact.cost) != (raw.feasible, raw.cost))
        unrestricted_disagreements += int(
            (exact.feasible, exact.cost) != (unrestricted.feasible, unrestricted.cost)
        )

        swapped = EpochInstance(
            (tiers[1], tiers[0]), (free[1], free[0]), quantum, commit, f"swap-{case_index}"
        )
        swapped_solution = solve_normal_form(swapped)
        symmetry_disagreements += int(
            (exact.feasible, exact.cost) != (swapped_solution.feasible, swapped_solution.cost)
        )

        larger = EpochInstance(
            (tiers[0], tiers[1]),
            (free[0] + rng.randint(0, 4), free[1] + rng.randint(0, 4)),
            quantum,
            commit,
            f"reserve-{case_index}",
        )
        larger_solution = solve_normal_form(larger)
        if exact.feasible:
            reserve_violations += int(
                not larger_solution.feasible
                or exact.cost is None
                or larger_solution.cost is None
                or larger_solution.cost > exact.cost
            )

        factor = rng.choice((2, 3, 5))
        scaled_tiers = tuple(
            tuple(
                Segment(seg.occupied * factor, seg.live * factor, seg.birth, seg.name)
                for seg in tier
            )
            for tier in tiers
        )
        scaled = EpochInstance(
            (scaled_tiers[0], scaled_tiers[1]),
            (free[0] * factor, free[1] * factor),
            quantum * factor,
            commit * factor,
            f"scale-{case_index}",
        )
        scaled_solution = solve_normal_form(scaled)
        expected_scaled_cost = None if exact.cost is None else exact.cost * factor
        scale_violations += int(
            (scaled_solution.feasible, scaled_solution.cost)
            != (exact.feasible, expected_scaled_cost)
        )

        scan = scan_feasibility(instance)
        if scan.feasible:
            merged = _merge_adjacent(scan.schedule)
            original_replay = replay(instance, scan.schedule)
            merged_replay = replay(instance, merged)
            merge_violations += int(
                merged_replay["free"] != original_replay["free"]
                or merged_replay["cost"] > original_replay["cost"]
            )

    payload = {
        "seed": seed,
        "cases": cases,
        "feasible_cases": feasible_cases,
        "sampling_schema": {
            "tiers": 2,
            "tier_length_each": [0, 4],
            "occupied_each": [1, 7],
            "live_each": [0, "occupied"],
            "free_each": [0, 12],
            "quantum": [1, 12],
            "commit_bytes": [0, 5],
            "birth_assignment": "sequential across source 0 then source 1",
            "sampling": "independent uniform integer draws under the listed bounds",
        },
        "maximum_generated_tier_lengths": max_lengths,
        "raw_oracle_total_states": raw_states,
        "raw_oracle_total_transitions": raw_transitions,
        "raw_oracle_disagreements": raw_disagreements,
        "unrestricted_solver_disagreements": unrestricted_disagreements,
        "tier_swap_symmetry_disagreements": symmetry_disagreements,
        "reserve_monotonicity_violations": reserve_violations,
        "scale_invariance_violations": scale_violations,
        "adjacent_merge_violations": merge_violations,
        "runtime": _runtime(start_wall, start_cpu),
    }
    if any(
        payload[key]
        for key in (
            "raw_oracle_disagreements",
            "unrestricted_solver_disagreements",
            "tier_swap_symmetry_disagreements",
            "reserve_monotonicity_violations",
            "scale_invariance_violations",
            "adjacent_merge_violations",
        )
    ):
        raise AssertionError("independent or metamorphic audit found a violation")
    _json(out / "independent-audit.json", payload)
    return payload


def finalize(out: Path) -> dict:
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    grid = json.loads((out / "grid-summary.json").read_text(encoding="utf-8"))
    trace = json.loads((out / "trace-summary.json").read_text(encoding="utf-8"))
    recovery = json.loads((out / "recovery-summary.json").read_text(encoding="utf-8"))
    sensitivity = json.loads((out / "sensitivity.json").read_text(encoding="utf-8"))
    unit_exchange = json.loads((out / "unit-exchange-summary.json").read_text(encoding="utf-8"))
    independent_audit = json.loads((out / "independent-audit.json").read_text(encoding="utf-8"))
    part_summaries = [
        json.loads((out / f"grid-{part}.json").read_text(encoding="utf-8"))
        for part in range(PARTS)
    ]
    payload = {
        "complete": True,
        "exact_grid": grid,
        "public_trace_mechanism_checks": trace,
        "recovery": {key: value for key, value in recovery.items() if key != "example"},
        "sensitivity": sensitivity,
        "unit_exchange_frontier": unit_exchange,
        "independent_audit": independent_audit,
        "runtime_subtotal": {
            "grid_parts_cpu_seconds": sum(item["runtime"]["cpu_seconds"] for item in part_summaries),
            "aggregate_cpu_seconds": grid["runtime"]["cpu_seconds"],
            "trace_cpu_seconds": trace["runtime"]["cpu_seconds"],
            "recovery_cpu_seconds": recovery["runtime"]["cpu_seconds"],
            "sensitivity_cpu_seconds": sensitivity["runtime"]["cpu_seconds"],
            "unit_exchange_cpu_seconds": unit_exchange["runtime"]["cpu_seconds"],
            "independent_audit_cpu_seconds": independent_audit["runtime"]["cpu_seconds"],
        },
        "finalize_runtime": _runtime(start_wall, start_cpu),
    }
    payload["runtime_subtotal"]["total_cpu_seconds"] = round(
        sum(payload["runtime_subtotal"].values()), 6
    )
    _json(out / "summary.json", payload)
    return payload


def run_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for part in range(PARTS):
        print(f"[grid {part}/{PARTS - 1}]", flush=True)
        run_grid_part(part, out)
    print("[aggregate]", flush=True)
    aggregate_grid(out)
    print("[trace]", flush=True)
    run_trace(out)
    print("[recovery]", flush=True)
    run_recovery(out)
    print("[sensitivity]", flush=True)
    run_sensitivity(out)
    print("[unit-exchange]", flush=True)
    run_unit_exchange(out)
    print("[independent-audit]", flush=True)
    run_independent_audit(out)
    print("[finalize]", flush=True)
    summary = finalize(out)
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results" / "frontier")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--grid-part", type=int)
    group.add_argument("--aggregate", action="store_true")
    group.add_argument("--trace", action="store_true")
    group.add_argument("--recovery", action="store_true")
    group.add_argument("--sensitivity", action="store_true")
    group.add_argument("--unit-exchange", action="store_true")
    group.add_argument("--independent-audit", action="store_true")
    group.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if __debug__ is False:
        raise SystemExit("optimized Python is unsupported: scientific assertions must remain enabled")
    enforce_resource_contract()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.all:
        run_all(args.out)
    elif args.grid_part is not None:
        print(json.dumps(run_grid_part(args.grid_part, args.out), indent=2, sort_keys=True))
    elif args.aggregate:
        print(json.dumps(aggregate_grid(args.out), indent=2, sort_keys=True))
    elif args.trace:
        print(json.dumps(run_trace(args.out), indent=2, sort_keys=True))
    elif args.recovery:
        print(json.dumps(run_recovery(args.out), indent=2, sort_keys=True))
    elif args.sensitivity:
        print(json.dumps(run_sensitivity(args.out), indent=2, sort_keys=True))
    elif args.unit_exchange:
        print(json.dumps(run_unit_exchange(args.out), indent=2, sort_keys=True))
    elif args.independent_audit:
        print(json.dumps(run_independent_audit(args.out), indent=2, sort_keys=True))
    elif args.finalize:
        print(json.dumps(finalize(args.out), indent=2, sort_keys=True))
    if _swap_kib() != 0:
        raise RuntimeError("no-swap contract violated during campaign")


if __name__ == "__main__":
    main()
