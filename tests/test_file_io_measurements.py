import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_file_io_measurements import reconcile, verify_saved


class SavedFileMeasurements(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ROOT / 'results/file-io-calibration'
        cls.rows = [json.loads(x) for x in (root / 'raw-trials.jsonl').read_text('utf-8').splitlines()]
        cls.plans = json.loads((root / 'inputs-and-schedules.json').read_text('utf-8'))
        cls.summary = json.loads((root / 'summary.json').read_text('utf-8'))

    def test_saved_source_bound_packet(self):
        self.assertEqual(verify_saved()['trials'], 300)

    def test_missing_and_duplicate_trials(self):
        for rows in (self.rows[:-1], self.rows[:-1] + self.rows[:1]):
            with self.assertRaises(ValueError):
                reconcile(rows, self.plans, self.summary)

    def test_false_reopen_and_altered_bytes(self):
        for field in ('reopen', 'bytes', 'timing'):
            rows = copy.deepcopy(self.rows)
            if field == 'reopen':
                rows[0]['recovery']['complete'] = False
            elif field == 'bytes':
                rows[0]['execute']['write_bytes'] += 1
            else:
                rows[0]['planning_ns'] = float('nan')
            with self.assertRaises(ValueError):
                reconcile(rows, self.plans, self.summary)

    def test_altered_summary(self):
        record = copy.deepcopy(self.summary)
        record['per_case'][0]['policies']['optimal']['execute_ms_median'] += 1
        with self.assertRaises(ValueError):
            reconcile(self.rows, self.plans, record)


if __name__ == '__main__':
    unittest.main()
