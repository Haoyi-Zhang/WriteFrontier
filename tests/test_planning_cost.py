"""Planner reporting uses complete identities and raw sums, not differences of medians."""
import copy
import json
from pathlib import Path
import statistics
import unittest

from analyze_planning_cost import derive, table_tex

ROOT = Path(__file__).resolve().parents[1] / 'results/file-io-calibration'


class PlanningCostTests(unittest.TestCase):
    def setUp(self):
        self.rows = [json.loads(line) for line in (ROOT / 'raw-trials.jsonl').read_text('utf-8').splitlines()]
        self.plans = json.loads((ROOT / 'inputs-and-schedules.json').read_text('utf-8'))

    def test_fixed_matrix_and_direct_raw_timing_aggregation(self):
        result = derive(self.rows, self.plans)
        self.assertEqual(result['cases_with_identical_file_bytes'], 20)
        for row in result['methods']:
            samples = [x for x in self.rows if x['method'] == row['method']]
            self.assertEqual(row['trials'], 100)
            self.assertEqual(row['plan_execute_ms_median'], statistics.median(
                x['planning_ns'] + x['execute']['wall_ns'] for x in samples) / 1e6)
        self.assertEqual(table_tex(result).count(' & '), 16)

    def test_missing_duplicate_unknown_and_negative_are_refused(self):
        for kind in ('missing', 'duplicate', 'unknown', 'negative'):
            rows = copy.deepcopy(self.rows)
            if kind == 'missing':
                rows.pop()
            elif kind == 'duplicate':
                rows[-1] = rows[0]
            elif kind == 'unknown':
                rows[0]['method'] = 'not-a-measured-method'
            else:
                rows[0]['planning_ns'] = -1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                derive(rows, self.plans)
