"""Selector validation and unchanged benign recovery controls."""
import csv
import json
import sys
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
from epoch_model import Batch, EpochInstance, Segment
from epoch_dp import solve_normal_form  # Used only to construct the test corpus.
from epoch_recovery import SUPPORTED_MUTATIONS, check_corpus, check_schedule


class RecoverySelectorTests(unittest.TestCase):
    def setUp(self):
        self.model = EpochInstance(((Segment(1, 1),), ()), (0, 1), 4, 1)
        self.schedule = (Batch(0, 0, 1),)

    def test_unknown_names_are_rejected_before_replay_or_schedule_consumption(self):
        def unconsumed():
            raise AssertionError("invalid selector consumed schedule")
            yield
        for value in ("publsh-before-flush", "", "unknown", "None"):
            with self.subTest(value=value), patch("epoch_recovery.replay") as replay:
                with self.assertRaises(ValueError):
                    check_schedule(self.model, unconsumed(), value)
                replay.assert_not_called()

    def test_non_string_types_are_rejected_before_simulation(self):
        class StringSubclass(str):
            pass
        for value in (True, False, 0, 1.5, b"publish-before-flush", [], {}, object(),
                      StringSubclass("publish-before-flush")):
            with self.subTest(value=repr(value)), patch("epoch_recovery._tokens") as tokens:
                with self.assertRaises(TypeError):
                    check_schedule(self.model, self.schedule, value)
                tokens.assert_not_called()

    def test_none_and_all_original_mutations(self):
        self.assertEqual(SUPPORTED_MUTATIONS, (
            "publish-before-flush", "reclaim-before-commit",
            "truncate-persisted-payload", "torn-commit-reclaim",
        ))
        self.assertEqual(check_schedule(self.model, self.schedule), {
            "mutation": None, "boundaries": 5, "failures": 0,
            "detected": False, "first_failure": None,
        })
        for mutation in SUPPORTED_MUTATIONS:
            with self.subTest(mutation=mutation):
                self.assertTrue(check_schedule(self.model, self.schedule, mutation)["detected"])
        early = check_schedule(self.model, self.schedule, "publish-before-flush")
        self.assertEqual((early["boundaries"], early["failures"]), (6, 2))

    def test_dead_payload_skip_and_metadata_controls_are_preserved(self):
        dead = EpochInstance(((Segment(1, 0),), ()), (0, 0), 4, 1)
        corpus = check_corpus(((self.model, self.schedule), (dead, self.schedule)))
        self.assertEqual(corpus.normal_failures, 0)
        self.assertEqual(corpus.mutation_runs, 7)
        self.assertEqual(corpus.mutation_runs_detected, 7)
        self.assertEqual(corpus.mutation_classes["truncate-persisted-payload"]["skipped"], 1)

    def test_all_retained_recovery_controls_match_original_results(self):
        with (HERE / "results/frontier/frontier-cases.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        types = ((1,0), (1,1), (2,0), (2,1), (2,2), (3,1), (3,2), (3,3))
        sequences = [s for n in (1,2) for s in product(types, repeat=n)]
        corpus = []
        for row in rows[::max(1, len(rows)//1024)][:1024]:
            pattern = int(row["pattern_id"])
            raw = sequences[pattern//72], sequences[pattern%72]
            tiers = tuple(tuple(Segment(b,l,2*i+s) for i,(b,l) in enumerate(t))
                          for s,t in enumerate(raw))
            model = EpochInstance(tiers, (int(row["f0"]), int(row["f1"])), 4, 1)
            corpus.append((model, solve_normal_form(model).schedule))
        result = check_corpus(corpus).as_dict()
        original = json.loads((HERE / "results/frontier/recovery-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(result, {key: original[key] for key in result})
        self.assertEqual((result["schedules"], result["normal_boundaries"], result["mutation_runs_detected"]),
                         (1024, 14461, 4088))


if __name__ == "__main__":
    unittest.main()
