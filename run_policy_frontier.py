#!/usr/bin/env python3
"""Local deterministic modeled-cost comparison; no network or device access.

The two-start greedy and all four proxies see exactly the optimizer's frozen
input. The campaign reruns the 5,184 retained frontier inputs, adds longer
integer episodes, checks both DPs and the raw oracle, and retains every case.
Existing results/frontier files are read-only inputs to this separate campaign.
"""
import argparse
import csv
import gzip
import io
import json
import random
import sys
from collections import defaultdict
from fractions import Fraction
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'src'))
from epoch_model import EpochInstance, Segment, replay, serialize_instance, serialize_schedule
from epoch_dp import solve_normal_form, solve_unrestricted, find_min_common_slack, reserve_thresholds
from epoch_policies import all_policies, maximum_prefix_start, two_start_maximum_prefix
from independent_audit import solve_raw
from destination_model import audit_destinations
from trace_model import read_cloudphysics, read_twitter, make_trace_instances

SEED = 20261011
COSTS = ((1, 0), (4, 0), (1, 1), (4, 1), (8, 1), (4, 2))
LONG_COSTS = ((1, 0), (4096, 0), (1, 512), (4096, 512), (16384, 512), (4096, 1024))


def retained_frontiers():
    types = ((1, 0), (1, 1), (2, 0), (2, 1), (2, 2), (3, 1), (3, 2), (3, 3))
    sequences = [seq for n in (1, 2) for seq in product(types, repeat=n)]
    with (HERE / 'results/frontier/frontier-cases.csv').open(newline='', encoding='utf-8') as handle:
        for row in csv.DictReader(handle):
            pattern = int(row['pattern_id'])
            raw = (sequences[pattern // len(sequences)], sequences[pattern % len(sequences)])
            tiers = tuple(tuple(Segment(b, l, 2 * i + s) for i, (b, l) in enumerate(t))
                          for s, t in enumerate(raw))
            yield 'retained-frontier', str(pattern), EpochInstance(
                tiers, (int(row['f0']), int(row['f1'])), 4, 1), int(row['cost'])


def generated():
    rng = random.Random(SEED)
    for group, patterns, lengths, scale in (
        ('length-3-12', 256, (3, 12), 31), ('length-16-32', 128, (16, 32), 4096)
    ):
        for pattern in range(patterns):
            tiers = []
            for source in (0, 1):
                segments = []
                for i in range(rng.randint(*lengths)):
                    b = rng.randint(1, scale)
                    # Include all-live patterns, dead and mixed-live patterns.
                    live = b if pattern % 4 == 0 else (0 if pattern % 4 == 1 and i % 3 == 0
                                                      else rng.randint(0, b))
                    segments.append(Segment(b, live, 2 * i + source))
                tiers.append(tuple(segments))
            tiers = tuple(tiers)
            _, tight, _ = find_min_common_slack(tiers)
            extras = ((0, 0) if pattern % 3 == 0 else
                      (rng.randint(0, scale), rng.randint(0, scale)))
            free = tuple(tight.free[s] + extras[s] for s in (0, 1))
            # Raw prefixes up to 32 per source remain polynomially bounded.
            for q, mu in (COSTS if group == 'length-3-12' else LONG_COSTS):
                yield group, f'{pattern}-q{q}-mu{mu}', EpochInstance(tiers, free, q, mu), None


def public_excerpts():
    for dataset, requests, target, unit in (
        ('cloudphysics-prefix', read_cloudphysics(HERE / 'inputs/cloudphysics-prefix.csv'), 65536, 512),
        ('twitter-cluster015-prefix', read_twitter(HERE / 'inputs/twitter-cluster015-prefix.csv'), 2048, 64)
    ):
        for record in make_trace_instances(requests, window_rows=64, target_bytes=target,
                allocation_unit=unit, page_bytes=4096, commit_bytes=unit,
                extra_slacks=(0, 4096 // unit), dataset_id=dataset):
            model = record['instance']
            yield 'public-excerpt', model.label, model, None


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['domain'], row['policy'])].append(row)
    result = []
    for (domain, policy), records in sorted(grouped.items()):
        ratios = sorted(Fraction(r['cost'], r['opt_cost']) if r['opt_cost'] else Fraction(1)
                        for r in records)
        n = len(ratios)
        median = (ratios[(n - 1) // 2] + ratios[n // 2]) / 2
        result.append({'domain': domain, 'policy': policy, 'cases': n,
                       'optimal_cases': sum(r['cost'] == r['opt_cost'] for r in records),
                       'median': float(median), 'p95': float(ratios[(95 * n + 99) // 100 - 1]),
                       'max': float(ratios[-1]), 'max_exact': str(ratios[-1])})
    return result


def campaign(out):
    rows, witnesses, instances = [], [], []
    comparisons = defaultdict(int)
    threshold_counts = []
    for domain, case_id, model, historical in list(retained_frontiers()) + list(generated()) + list(public_excerpts()):
        exact = solve_normal_form(model)
        unrestricted = solve_unrestricted(model)
        raw = tuple(tuple((s.occupied, s.live) for s in t) for t in model.tiers)
        oracle = solve_raw(*raw, model.free, model.quantum, model.commit_bytes)
        assert exact.feasible and unrestricted.feasible and oracle.feasible
        assert exact.cost == unrestricted.cost == oracle.cost
        assert exact.batches == unrestricted.batches == oracle.epochs
        assert historical is None or historical == exact.cost
        comparisons[domain] += 1
        t0, t1 = reserve_thresholds(model.tiers)
        threshold_counts.append(len(t0) * len(t1))
        instances.append({'domain': domain, 'case_id': case_id, 'instance': serialize_instance(model)})
        greedy = two_start_maximum_prefix(model)
        for policy in (*all_policies(model), maximum_prefix_start(model, 0),
                       maximum_prefix_start(model, 1), greedy):
            assert policy.status == 'complete'
            assert replay(model, policy.schedule)['cost'] == policy.cost
            assert policy.cost >= exact.cost
            rows.append({'domain': domain, 'case_id': case_id, 'n0': model.lengths[0],
                         'n1': model.lengths[1], 'f0': model.free[0], 'f1': model.free[1],
                         'quantum': model.quantum, 'commit': model.commit_bytes,
                         'policy': policy.policy, 'cost': policy.cost, 'epochs': len(policy.schedule),
                         'opt_cost': exact.cost, 'opt_epochs': exact.batches})
        if greedy.cost > exact.cost and not any(w['domain'] == domain for w in witnesses):
            witnesses.append({'domain': domain, 'case_id': case_id, 'instance': serialize_instance(model),
                              'opt_cost': exact.cost, 'greedy_cost': greedy.cost,
                              'opt_schedule': serialize_schedule(exact.schedule),
                              'greedy_schedule': serialize_schedule(greedy.schedule)})
    shared = audit_destinations((((1, 1),),) * 3, (2, 2, 1), (0, 0, 1))
    cycle_states = cycle_edges = 0
    cycle_cases = 0
    for raw in product(((1, 0), (1, 1), (2, 1), (2, 2)), repeat=3):
        for free in product(range(3), repeat=3):
            result = audit_destinations(tuple((s,) for s in raw), (1, 2, 0), free)
            assert not result['violations']
            cycle_cases += 1
            cycle_states += result['viable_nonterminal_states']
            cycle_edges += result['legal_edges']
    summary = {'seed': SEED, 'cost_models': {'length-3-12': [list(x) for x in COSTS],
                                         'length-16-32': [list(x) for x in LONG_COSTS]},
               'comparisons': dict(comparisons), 'solver_disagreements': 0,
               'replay_disagreements': 0, 'policies': summarize(rows),
               'threshold_corner_counts': {'maximum': max(threshold_counts)},
               'destination_boundary': {'shared_destination_witness': shared,
                   'three_cycle_cases': cycle_cases, 'three_cycle_viable_states': cycle_states,
                   'three_cycle_legal_edges': cycle_edges, 'three_cycle_violations': 0}}
    out.mkdir(parents=True, exist_ok=True)
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    (out / 'policy-costs.csv.gz').write_bytes(gzip.compress(handle.getvalue().encode('utf-8'), mtime=0))
    for name, data in (('summary.json', summary), ('witnesses.json', witnesses),
                       ('instances.json', instances)):
        payload = (json.dumps(data, indent=2, sort_keys=True) + '\n').encode('utf-8')
        if name == 'instances.json':
            (out / (name + '.gz')).write_bytes(gzip.compress(payload, mtime=0))
        else:
            (out / name).write_bytes(payload)
    print(json.dumps({'comparisons': dict(comparisons), 'solver_disagreements': 0,
                      'greedy': [r for r in summary['policies'] if r['policy'] == 'two-start-maximum-prefix'],
                      'cycle_cases': cycle_cases, 'shared_destination_violations': len(shared['violations'])},
                     indent=2))


if __name__ == '__main__':
    if sys.flags.optimize:
        raise SystemExit('Run without -O: scientific assertions must remain enabled.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=HERE / 'results/policy-frontier')
    args = parser.parse_args()
    campaign(args.out)
