#!/usr/bin/env python3
"""Compare deterministic recovery-epoch scientific outputs.

Runtime and peak-memory measurements are intentionally excluded because they
are environment observations, not scientific outputs. CSV files and all other
JSON content are compared exactly after recursive removal of runtime fields.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

RUNTIME_KEYS = {"runtime", "runtime_subtotal", "finalize_runtime"}
EXPECTED = {
    *(f"grid-{part}.csv" for part in range(4)),
    *(f"grid-{part}.json" for part in range(4)),
    "grid-summary.json",
    "frontier-cases.csv",
    "baseline-summary.csv",
    "slack-curve.csv",
    "witnesses.json",
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
    actual = {item.name for item in path.iterdir() if item.is_file()}
    missing = sorted(EXPECTED - actual)
    if missing:
        raise ValueError(f"missing scientific outputs: {missing}")

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

    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    grid = summary["exact_grid"]
    recovery = summary["recovery"]
    unit = summary["unit_exchange_frontier"]
    independent = summary["independent_audit"]
    if not summary.get("complete"):
        raise ValueError("summary does not mark the campaign complete")
    if grid["domain"]["cases"] != 254_016:
        raise ValueError("summary grid size mismatch")
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
