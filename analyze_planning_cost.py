"""Derive planner costs from the retained file trials, never rerun their timers."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import statistics

from verify_file_io_measurements import METHODS, verify_saved

ROOT = Path(__file__).resolve().parent


def derive(rows, plans):
    cases = {plan['case_id'] for plan in plans}
    if len(cases) != 20 or len(plans) != 20 or len(rows) != 300:
        raise ValueError('expected 20 cases and 300 retained trials')
    expected = {(case, method, repeat) for case in cases for method in METHODS
                for repeat in range(5)}
    seen = set()
    for row in rows:
        key = row['case_id'], row['method'], row['repeat']
        if key not in expected or key in seen or type(row['repeat']) is not int:
            raise ValueError('missing, duplicate, or unknown trial identity')
        seen.add(key)
        for value in (row['planning_ns'], row['execute']['wall_ns']):
            if type(value) is not int or value < 0:
                raise ValueError('invalid retained timing')
    if seen != expected:
        raise ValueError('incomplete fixed trial matrix')
    tied = 0
    for case in cases:
        writes = {row['execute']['write_bytes'] for row in rows if row['case_id'] == case}
        if len(writes) == 1:
            tied += 1
    result = []
    for method in METHODS:
        selected = [row for row in rows if row['method'] == method]
        timings = sorted(row['planning_ns'] for row in selected)
        result.append({'method': method, 'trials': len(selected),
                       'planning_ms_median': statistics.median(timings) / 1e6,
                       'planning_ms_p95': timings[math.ceil(.95 * len(timings)) - 1] / 1e6,
                       'plan_execute_ms_median': statistics.median(
                           row['planning_ns'] + row['execute']['wall_ns']
                           for row in selected) / 1e6})
    return {'cases': len(cases), 'trials': len(rows),
            'cases_with_identical_file_bytes': tied, 'methods': result}


def table_tex(result):
    names = {'two-start': 'Two-start', 'coalesced-portfolio': 'Coalesced portfolio',
             'optimal': 'Exact DP'}
    lines = [r'\begin{tabular}{@{}lrrrr@{}}', r'\toprule',
             r'Method & Trials & Plan median (ms) & Plan P95 (ms) & Plan+execute median (ms) \\',
             r'\midrule']
    for row in result['methods']:
        lines.append(f"{names[row['method']]} & {row['trials']} & "
                     f"{row['planning_ms_median']:.3f} & {row['planning_ms_p95']:.3f} & "
                     f"{row['plan_execute_ms_median']:.3f}" + r' \\')
    return '\n'.join(lines + [r'\bottomrule', r'\end{tabular}']) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tex', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    # This verifies all semantic fields and the seven consumed source/input bindings.
    verify_saved()
    base = ROOT / 'results/file-io-calibration'
    rows = [json.loads(line) for line in (base / 'raw-trials.jsonl').read_text('utf-8').splitlines()]
    plans = json.loads((base / 'inputs-and-schedules.json').read_text('utf-8'))
    result = derive(rows, plans)
    if args.tex:
        text = table_tex(result)
        if args.check:
            if args.tex.read_text('utf-8') != text:
                raise ValueError('paper planner table differs from retained trials')
        else:
            args.tex.write_text(text, encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
