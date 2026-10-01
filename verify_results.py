#!/usr/bin/env python3
"""Compare deterministic recovery-epoch scientific outputs.

Runtime and peak-memory measurements are intentionally excluded because they
are environment observations, not scientific outputs. CSV files and all other
JSON content are compared exactly after recursive removal of runtime fields.

At the result-directory root, the scientific ``.csv`` and ``.json`` file set
must match ``EXPECTED`` exactly.  Human-readable ``.log``/``.txt`` files and
separate ``runtime/`` or ``logs/`` directories are auxiliary and are not part
of the scientific comparison; an extra top-level CSV or JSON is rejected.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from check_ordered_certificate import check_ordered_certificate

RUNTIME_KEYS = {"runtime", "runtime_subtotal", "finalize_runtime"}
AUXILIARY_FILE_SUFFIXES = {".log", ".txt"}
AUXILIARY_DIRECTORIES = {"runtime", "logs"}
EXPECTED = {
    *(f"grid-{part}.csv" for part in range(4)),
    *(f"grid-{part}.json" for part in range(4)),
    "grid-summary.json",
    "frontier-cases.csv",
    "baseline-summary.csv",
    "slack-curve.csv",
    "witnesses.json",
    "ordered-blocking-certificate.json",
    "trace-results.csv",
    "trace-certificates.json",
    "trace-summary.json",
    "recovery-summary.json",
    "sensitivity.csv",
    "sensitivity.json",
    "unit-exchange-frontier.csv",
    "unit-exchange-summary.json",
    "independent-audit.json",
    "summary.json",
}


def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: canonical(item)
            for key, item in sorted(value.items())
            if key not in RUNTIME_KEYS
        }
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def load_json(path: Path) -> Any:
    return canonical(json.loads(path.read_text(encoding="utf-8")))


def validate_result_directory(path: Path) -> dict[str, int]:
    actual_scientific: set[str] = set()
    unexpected_entries: list[str] = []
    for item in path.iterdir():
        if item.is_dir():
            if item.name not in AUXILIARY_DIRECTORIES:
                unexpected_entries.append(item.name + "/")
            continue
        suffix = item.suffix.lower()
        if suffix in {".csv", ".json"}:
            actual_scientific.add(item.name)
        elif suffix not in AUXILIARY_FILE_SUFFIXES:
            unexpected_entries.append(item.name)
    if unexpected_entries:
        raise ValueError(f"unexpected top-level non-scientific entries: {sorted(unexpected_entries)}")
    missing = sorted(EXPECTED - actual_scientific)
    if missing:
        raise ValueError(f"missing scientific outputs: {missing}")
    extra = sorted(actual_scientific - EXPECTED)
    if extra:
        raise ValueError(f"unexpected top-level scientific outputs: {extra}")

    check_ordered_certificate(load_json(path / "ordered-blocking-certificate.json"))

    rows: list[dict[str, str]] = []
    for part in range(4):
        with (path / f"grid-{part}.csv").open(newline="", encoding="utf-8") as handle:
            rows.extend(csv.DictReader(handle))
    case_ids = [int(row["case_id"]) for row in rows]
    if len(case_ids) != 254_016 or len(set(case_ids)) != 254_016:
        raise ValueError("exact grid is incomplete or contains duplicate case IDs")
    if min(case_ids) != 0 or max(case_ids) != 254_015:
        raise ValueError("exact grid case-ID range is incomplete")
    for row in rows:
        feasible = row["status"] == "feasible"
        oracle_feasible = row["oracle_status"] == "feasible"
        independent_feasible = row["independent_status"] == "feasible"
        scan_feasible = row["scan_status"] == "feasible"
        if feasible != oracle_feasible or feasible != independent_feasible or feasible != scan_feasible:
            raise ValueError(f"feasibility disagreement in case {row['case_id']}")
        if feasible and (
            row["cost"] != row["oracle_cost"]
            or row["cost"] != row["independent_cost"]
        ):
            raise ValueError(f"optimal-cost disagreement in case {row['case_id']}")

    with (path / "trace-results.csv").open(newline="", encoding="utf-8") as handle:
        trace_rows = list(csv.DictReader(handle))
    required_trace_fields = {
        "raw_live_bytes",
        "retained_allocation_bytes",
        "final_fit_free0_units",
        "final_fit_free1_units",
        "minimum_common_slack_units",
        "free0_units",
        "free1_units",
        "extra_slack_units",
        "exact_cost_bytes",
        "exact_physical_over_raw_live",
        "exact_physical_over_retained_allocation",
    }
    if trace_rows and not required_trace_fields.issubset(trace_rows[0]):
        raise ValueError("trace metric contract fields are incomplete")
    for row in trace_rows:
        raw = int(row["raw_live_bytes"])
        allocated = int(row["retained_allocation_bytes"])
        cost = int(row["exact_cost_bytes"])
        if allocated < raw:
            raise ValueError("retained allocation bytes are below raw live bytes")
        slack = int(row["minimum_common_slack_units"])
        extra_slack = int(row["extra_slack_units"])
        expected_free = (
            int(row["final_fit_free0_units"]) + slack + extra_slack,
            int(row["final_fit_free1_units"]) + slack + extra_slack,
        )
        if expected_free != (int(row["free0_units"]), int(row["free1_units"])):
            raise ValueError("trace free vector does not match final-fit base plus common slack")
        raw_ratio = None if raw == 0 else cost / raw
        allocation_ratio = None if allocated == 0 else cost / allocated
        if raw_ratio is not None and not math.isclose(
            float(row["exact_physical_over_raw_live"]), raw_ratio, rel_tol=1e-12
        ):
            raise ValueError("raw-live physical ratio is inconsistent")
        if allocation_ratio is not None and not math.isclose(
            float(row["exact_physical_over_retained_allocation"]),
            allocation_ratio,
            rel_tol=1e-12,
        ):
            raise ValueError("allocation-live physical ratio is inconsistent")
    twitter_tight = {
        int(row["window_index"]): row
        for row in trace_rows
        if row["dataset"] == "twitter-cluster015-prefix"
        and int(row["extra_slack_units"]) == 0
    }
    expected_twitter = {
        0: (7587, 7744, (26, 31)),
        1: (7600, 7680, (24, 32)),
    }
    for window, (raw, allocated, free) in expected_twitter.items():
        row = twitter_tight.get(window)
        if row is None:
            raise ValueError(f"missing Twitter window {window} tight-reserve row")
        observed = (
            int(row["raw_live_bytes"]),
            int(row["retained_allocation_bytes"]),
            (int(row["free0_units"]), int(row["free1_units"])),
        )
        if observed != (raw, allocated, free):
            raise ValueError(f"Twitter window {window} metric contract mismatch: {observed}")

    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    grid = summary["exact_grid"]
    recovery = summary["recovery"]
    unit = summary["unit_exchange_frontier"]
    independent = summary["independent_audit"]
    if not summary.get("complete"):
        raise ValueError("summary does not mark the campaign complete")
    if grid["domain"]["cases"] != 254_016:
        raise ValueError("summary grid size mismatch")
    no_memo = grid.get("no_memo_audit")
    if type(no_memo) is not dict or (
        no_memo.get("free") != [6, 6]
        or no_memo.get("cases") != 5_184
        or no_memo.get("feasible_cases") != 5_184
        or no_memo.get("optimum_at_lower_bound") != 5_184
    ):
        raise ValueError("no-memory audit is not the complete OPT=LB corner at (6,6)")
    if grid["solver_oracle_disagreements"] != 0:
        raise ValueError("normal-form and unrestricted solvers disagree")
    if grid["independent_raw_disagreements"] != 0:
        raise ValueError("independent raw oracle disagrees on the exact grid")
    if grid["linear_scan_status_disagreements"] != 0:
        raise ValueError("linear feasibility scan disagrees with exact search")
    if grid["confluence_audit"]["violations"] != 0:
        raise ValueError("confluence audit found a legal edge leaving viability")
    if grid["confluence_audit"]["status_disagreements"] != 0:
        raise ValueError("viability marking disagrees with the exact solver")
    if unit["formula_disagreements"] != 0:
        raise ValueError("closed-form unit-exchange frontier disagrees with the DP")
    if independent.get("seed") != 20_260_916:
        raise ValueError("independent-audit seed mismatch")
    schema = independent.get("sampling_schema")
    if type(schema) is not dict or schema.get("free_each") != [0, 12]:
        raise ValueError("independent-audit reserve domain mismatch")
    for key in (
        "raw_oracle_disagreements",
        "unrestricted_solver_disagreements",
        "tier_swap_symmetry_disagreements",
        "reserve_monotonicity_violations",
        "scale_invariance_violations",
        "adjacent_merge_violations",
    ):
        if independent[key] != 0:
            raise ValueError(f"independent audit failure: {key}")
    if recovery["normal_failures"] != 0:
        raise ValueError("the good recovery protocol has a failing crash prefix")
    if recovery["mutation_runs"] != recovery["mutation_runs_detected"]:
        raise ValueError("at least one negative-control recovery mutation escaped detection")
    expected_mutation_runs = {
        "publish-before-flush": (1024, 0),
        "reclaim-before-commit": (1024, 0),
        "truncate-persisted-payload": (1016, 8),
        "torn-commit-reclaim": (1024, 0),
    }
    if recovery.get("schedules") != 1024 or recovery.get("all_dead_schedules") != 8:
        raise ValueError("recovery corpus or all-dead count mismatch")
    classes = recovery.get("mutation_classes")
    if type(classes) is not dict:
        raise ValueError("recovery result lacks per-mutation counts")
    for name, (runs, skipped) in expected_mutation_runs.items():
        item = classes.get(name)
        if type(item) is not dict:
            raise ValueError(f"missing recovery mutation class: {name}")
        if item.get("runs") != runs or item.get("skipped") != skipped:
            raise ValueError(f"recovery mutation count mismatch: {name}")
        if item.get("detected_runs") != runs:
            raise ValueError(f"recovery mutation escaped detection: {name}")
    return {"grid_cases": len(rows), "scientific_files": len(EXPECTED)}


def verify(reference: Path, reproduced: Path) -> None:
    left = validate_result_directory(reference)
    right = validate_result_directory(reproduced)
    for name in sorted(EXPECTED):
        a = reference / name
        b = reproduced / name
        if name.endswith(".json"):
            if load_json(a) != load_json(b):
                raise ValueError(f"scientific JSON mismatch: {name}")
        elif a.read_bytes() != b.read_bytes():
            raise ValueError(f"scientific CSV mismatch: {name}")
    print(
        json.dumps(
            {
                "scientific_files_identical": left["scientific_files"],
                "grid_cases": left["grid_cases"],
                "runtime_compared": False,
                "reproduced_grid_cases": right["grid_cases"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("reproduced", type=Path)
    args = parser.parse_args()
    verify(args.reference, args.reproduced)


if __name__ == "__main__":
    main()
