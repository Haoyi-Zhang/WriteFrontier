#!/usr/bin/env python3
"""Separate modeled-cost comparison on all 7,496 retained frozen inputs.

Policies select before evaluation solvers are called. Original result directories
and the raw-policy CSV/schema/counterexamples are read-only. No timing campaign,
network, device operations or production-storage interpretation is included.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from epoch_model import (
    EpochInstance, deserialize_instance, deserialize_schedule, replay, serialize_schedule,
)
from epoch_policies import (
    all_policies, coalesced_policy_candidates, coalesced_portfolio,
    maximum_prefix_start, select_replayed_portfolio, two_start_maximum_prefix,
)
# These are evaluation dependencies only; epoch_policies imports none of them.
from epoch_dp import solve_normal_form, solve_unrestricted
from independent_audit import solve_raw

DOMAIN_COUNTS = {
    "retained-frontier": 5184, "length-3-12": 1536,
    "length-16-32": 768, "public-excerpt": 8,
}
RAW_NAMES = (
    "lru-tiered-proxy", "leveled-proxy", "size-tiered-proxy", "gain-per-write",
    "maximum-prefix-start-0", "maximum-prefix-start-1", "two-start-maximum-prefix",
)
FILES = (
    "instances.json.gz", "coalesced-policy-costs.csv.gz",
    "residual-witnesses.json.gz", "summary.json",
)
FIELDS = (
    "domain", "case_id", "n0", "n1", "f0", "f1", "quantum", "commit",
    "policy", "selected_candidate", "cost", "epochs",
    "opt_cost", "min_epochs_at_opt_cost", "global_min_epochs", "cost_gap", "ratio_exact",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def output_directory(path):
    out = Path(path).resolve()
    require(out.parent == (HERE / "results").resolve()
            and out.name.startswith("coalesced-portfolio"),
            "output must be a results/coalesced-portfolio* sibling; original results are read-only")
    return out


def load_retained():
    source = HERE / "results/policy-frontier"
    input_bytes = (source / "instances.json.gz").read_bytes()
    cases = json.loads(gzip.decompress(input_bytes))
    require(type(cases) is list, "retained inputs must be an array")
    ids = []
    for case in cases:
        require(type(case) is dict and set(case) == {"domain", "case_id", "instance"},
                "unexpected retained case schema")
        require(type(case["domain"]) is str and type(case["case_id"]) is str,
                "domain and case ID must be strings")
        deserialize_instance(case["instance"])
        ids.append((case["domain"], case["case_id"]))
    require(len(set(ids)) == len(ids), "duplicate retained input")
    require(Counter(domain for domain, _ in ids) == Counter(DOMAIN_COUNTS),
            "expected exactly all 7,496 retained inputs")
    with gzip.open(source / "policy-costs.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    original = {}
    for row in raw_rows:
        key = row["domain"], row["case_id"], row["policy"]
        require(key not in original, "duplicate retained policy row")
        original[key] = row
    expected = {(domain, cid, policy) for domain, cid in ids for policy in RAW_NAMES}
    require(set(original) == expected, "retained raw-policy coverage is incomplete or unexpected")
    return cases, original, input_bytes


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["domain"], row["policy"]].append(row)
    summaries = []
    for (domain, policy), records in sorted(grouped.items()):
        ratios = sorted(Fraction(row["ratio_exact"]) for row in records)
        n = len(ratios)
        p95 = ratios[(95*n+99)//100 - 1]
        median = (ratios[(n-1)//2] + ratios[n//2])/2
        worst = min((row for row in records if Fraction(row["ratio_exact"]) == ratios[-1]),
                    key=lambda row: row["case_id"])
        summaries.append({
            "domain": domain, "policy": policy, "cases": n,
            "optimal_cases": sum(row["cost_gap"] == 0 for row in records),
            "median_exact": str(median), "p95_exact": str(p95), "max_exact": str(ratios[-1]),
            "median": float(median), "p95": float(p95), "max": float(ratios[-1]),
            "maximum_ratio_case_id": worst["case_id"],
        })
    return summaries


def render_table(summary):
    """Generate the small manuscript table on stdout, never write paper files."""
    labels = {
        "retained-frontier": "Small frontiers", "length-3-12": "3--12 per tier",
        "length-16-32": "16--32 per tier", "public-excerpt": "Public excerpts",
    }
    records = {(row["domain"], row["policy"]): row for row in summary["policies"]}
    lines = [
        r"\begin{tabular}{@{}lrrrr@{}}", r"\toprule",
        r"Episode domain & Two-start opt. & Coalesced opt. & P95 & Max\\",
        r"\midrule",
    ]
    for domain in DOMAIN_COUNTS:
        raw = records[domain, "two-start-maximum-prefix"]
        merged = records[domain, "coalesced-portfolio"]
        n = merged["cases"]
        lines.append(f"{labels[domain]} & {raw['optimal_cases']:,} / {n:,} & "
                     f"{merged['optimal_cases']:,} / {n:,} & "
                     f"{merged['p95']:.3f} & {merged['max']:.3f}" + r"\\")
    lines.extend((r"\bottomrule", r"\end{tabular}"))
    return "\n".join(lines) + "\n"


def read_outputs(path):
    """Read and validate every losslessly compressed input, row and gap witness."""
    out = output_directory(path)
    with gzip.open(out / "instances.json.gz", "rt", encoding="utf-8") as handle:
        cases = json.load(handle)
    with gzip.open(out / "coalesced-policy-costs.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        require(tuple(reader.fieldnames or ()) == FIELDS, "supplemental row schema mismatch")
        rows = list(reader)
    with gzip.open(out / "residual-witnesses.json.gz", "rt", encoding="utf-8") as handle:
        witnesses = json.load(handle)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    inputs = {(case["domain"], case["case_id"]): case["instance"] for case in cases}
    require(len(inputs) == len(cases) == 7496, "compressed input coverage mismatch")
    require(Counter(case["domain"] for case in cases) == Counter(DOMAIN_COUNTS),
            "compressed domain coverage mismatch")
    names = {"coalesced-" + name for name in (*RAW_NAMES[:4], RAW_NAMES[-1])}
    names.update(("replayed-raw-portfolio", "coalesced-portfolio"))
    keys = {(row["domain"], row["case_id"], row["policy"]) for row in rows}
    require(len(keys) == len(rows) == 7*7496
            and keys == {(d, c, p) for d, c in inputs for p in names},
            "compressed supplemental row coverage mismatch")
    residual_rows = {}
    for row in rows:
        cost, opt = int(row["cost"]), int(row["opt_cost"])
        require(cost >= opt and int(row["cost_gap"]) == cost-opt, "stored cost gap mismatch")
        require(opt != 0 or cost == 0, "nonzero stored cost at zero optimum")
        ratio = Fraction(cost, opt) if opt else Fraction(1)
        require(Fraction(row["ratio_exact"]) == ratio, "stored exact ratio mismatch")
        require(int(row["global_min_epochs"]) <= int(row["epochs"]),
                "stored schedule has fewer epochs than global minimum")
        if cost == opt:
            require(int(row["min_epochs_at_opt_cost"]) <= int(row["epochs"]),
                    "stored cost-optimal schedule has fewer epochs than conditioned minimum")
        if row["policy"] == "coalesced-portfolio" and cost > opt:
            residual_rows[row["domain"], row["case_id"]] = row
    witness_keys = {(w["domain"], w["case_id"]) for w in witnesses}
    require(len(witness_keys) == len(witnesses) == len(residual_rows)
            and witness_keys == set(residual_rows), "compressed residual coverage mismatch")
    for witness in witnesses:
        key = witness["domain"], witness["case_id"]
        row = residual_rows[key]
        require(witness["instance"] == inputs[key], "witness input differs from frozen input")
        model = deserialize_instance(witness["instance"])
        for schedule_key, cost_key in (("opt_schedule", "opt_cost"),
                                       ("portfolio_schedule", "portfolio_cost")):
            checked = replay(model, deserialize_schedule(witness[schedule_key]))
            require(checked["cost"] == witness[cost_key], "compressed witness replay mismatch")
        require(witness["portfolio_cost"] == int(row["cost"])
                and witness["ratio_exact"] == row["ratio_exact"]
                and witness["selected_candidate"] == row["selected_candidate"],
                "witness and row disagree")
    require(summary["cases"] == len(cases)
            and summary["verification"]["new_policy_rows_replayed"] == len(rows)
            and summary["residual_portfolio_cases"] == len(witnesses),
            "summary and compressed records disagree")
    return cases, rows, witnesses, summary


def campaign(path):
    out = output_directory(path)
    cases, original, input_bytes = load_retained()
    new_rows, evaluation_rows, residuals = [], [], []
    count_cache = {}
    count_metric_differences = Counter()
    for index, case in enumerate(cases):
        domain, cid = case["domain"], case["case_id"]
        model = deserialize_instance(case["instance"])
        raw = (*all_policies(model), maximum_prefix_start(model, 0),
               maximum_prefix_start(model, 1), two_start_maximum_prefix(model))
        merged = coalesced_policy_candidates(model)
        portfolio = coalesced_portfolio(model)
        raw_portfolio = select_replayed_portfolio(model, raw[:4] + (raw[-1],),
                                                 name="replayed-raw-portfolio")
        new = (*merged, raw_portfolio, portfolio)
        # Candidate selection is complete before any solver result is produced.
        exact = solve_normal_form(model)
        unrestricted = solve_unrestricted(model)
        primitive = tuple(tuple((seg.occupied, seg.live) for seg in tier) for tier in model.tiers)
        oracle = solve_raw(*primitive, model.free, model.quantum, model.commit_bytes)
        require(exact.feasible and unrestricted.feasible and oracle.feasible, "retained input became infeasible")
        require((exact.cost, exact.batches) == (unrestricted.cost, unrestricted.batches)
                == (oracle.cost, oracle.epochs), "evaluation solver disagreement")
        key = model.tiers, model.free
        if key not in count_cache:
            # With q=mu=1, every completion costs total_live + number of epochs.
            minimum = solve_normal_form(EpochInstance(model.tiers, model.free, 1, 1))
            require(minimum.feasible, "count objective changed feasibility")
            count_cache[key] = minimum.batches
        global_count = count_cache[key]
        count_metric_differences[domain] += int(global_count < exact.batches)
        selected = min(merged, key=lambda p: (replay(model, p.schedule)["cost"], len(p.schedule), p.policy))
        require((portfolio.cost, portfolio.schedule, portfolio.reason)
                == (selected.cost, selected.schedule, selected.policy), "portfolio selection disagreement")
        for policy in (*raw, *new):
            require(policy.status == "complete", "retained policy did not complete")
            checked = replay(model, policy.schedule)
            require(checked["cost"] == policy.cost and policy.cost >= exact.cost,
                    "policy cost/replay/optimum disagreement")
            require(exact.cost != 0 or policy.cost == 0, "nonzero policy cost at zero optimum")
            ratio = Fraction(policy.cost, exact.cost) if exact.cost else Fraction(1)
            row = dict(zip(FIELDS, (
                domain, cid, *model.lengths, *model.free, model.quantum, model.commit_bytes,
                policy.policy, policy.reason if "portfolio" in policy.policy else policy.policy,
                policy.cost, len(policy.schedule), exact.cost, exact.batches, global_count,
                policy.cost-exact.cost, str(ratio),
            )))
            evaluation_rows.append(row)
            if policy in new:
                new_rows.append(row)
            else:
                retained = original[domain, cid, policy.policy]
                require((int(retained["cost"]), int(retained["epochs"]),
                         int(retained["opt_cost"]), int(retained["opt_epochs"]))
                        == (policy.cost, len(policy.schedule), exact.cost, exact.batches),
                        "original raw policy output changed")
        if portfolio.cost > exact.cost:
            residuals.append({
                "domain": domain, "case_id": cid, "instance": case["instance"],
                "selected_candidate": portfolio.reason, "opt_cost": exact.cost,
                "min_epochs_at_opt_cost": exact.batches, "global_min_epochs": global_count,
                "portfolio_cost": portfolio.cost, "cost_gap": portfolio.cost-exact.cost,
                "ratio_exact": str(Fraction(portfolio.cost, exact.cost)),
                "opt_schedule": serialize_schedule(exact.schedule),
                "portfolio_schedule": serialize_schedule(portfolio.schedule),
            })
        if (index+1) % 1000 == 0:
            print(f"checked {index+1}/{len(cases)} retained inputs", flush=True)
    require(len(new_rows) == 7*7496, "new policy row count mismatch")
    summary = {
        "schema_version": 1, "inputs": DOMAIN_COUNTS, "cases": len(cases),
        "input_source": "results/policy-frontier/instances.json.gz",
        "raw_comparison_source": "results/policy-frontier/policy-costs.csv.gz",
        "candidate_set": ["coalesced-" + name for name in (*RAW_NAMES[:4], RAW_NAMES[-1])],
        "selection": "replayed cost, epochs, candidate name; no optimizer information",
        "ratio_denominator": "same frozen episode's exact minimum modeled migration cost",
        "epoch_metrics": {
            "min_epochs_at_opt_cost": "minimum epochs AMONG minimum-cost schedules",
            "global_min_epochs": "minimum epochs over all legal completions; q=1, mu=1 count solve",
            "costed_cases_where_metrics_differ": dict(sorted(count_metric_differences.items())),
        },
        "generated_pattern_counts": {"length-3-12": 256, "length-16-32": 128},
        "quantiles": "nearest-rank P95; zero-cost ratios equal one only when both costs are zero",
        "verification": {
            "three_solver_comparisons": 7496, "solver_disagreements": 0,
            "raw_policy_rows_reexecuted": 7*7496, "raw_policy_disagreements": 0,
            "new_policy_rows_replayed": len(new_rows), "replay_disagreements": 0,
        },
        "residual_portfolio_cases": len(residuals),
        "residual_cases_by_domain": dict(sorted(Counter(w["domain"] for w in residuals).items())),
        "policies": summarize(evaluation_rows),
        "scope": "Frozen ordered model only; no timing, native-storage, hardware or production benchmark.",
    }
    out.mkdir(parents=True, exist_ok=True)
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(new_rows)
    (out / "instances.json.gz").write_bytes(input_bytes)
    (out / "coalesced-policy-costs.csv.gz").write_bytes(
        gzip.compress(csv_buffer.getvalue().encode("utf-8"), mtime=0))
    payload = (json.dumps(residuals, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (out / "residual-witnesses.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    read_outputs(out)
    print(json.dumps({
        "cases": summary["cases"], "new_rows": len(new_rows),
        "residual_portfolio_cases": len(residuals),
        "portfolio": [row for row in summary["policies"] if row["policy"] == "coalesced-portfolio"],
    }, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results/coalesced-portfolio")
    parser.add_argument("--verify", type=Path, help="compare four deterministic files with another run")
    parser.add_argument("--print-table", action="store_true", help="print a table from existing output; no paper writes")
    parser.add_argument("--check-existing", action="store_true", help="read/replay compressed records without rerunning policies")
    args = parser.parse_args()
    if sys.flags.optimize:
        raise SystemExit("run without -O; scientific checks remain enabled")
    out = output_directory(args.out)
    if args.check_existing:
        cases, rows, witnesses, _ = read_outputs(out)
        print(f"read {len(cases)} inputs, {len(rows)} supplemental rows and {len(witnesses)} replayed residual witnesses")
        return
    if args.print_table:
        print(render_table(json.loads((out / "summary.json").read_text(encoding="utf-8"))), end="")
        return
    campaign(out)
    if args.verify is not None:
        reference = output_directory(args.verify)
        require(reference != out, "verification needs a distinct reproduction directory")
        for name in FILES:
            require((reference / name).read_bytes() == (out / name).read_bytes(),
                    f"reproduction mismatch: {name}")
        print("four deterministic scientific files reproduced byte-for-byte", flush=True)


if __name__ == "__main__":
    main()
