from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from epoch_dp import solve_normal_form  # noqa: E402
from epoch_model import EpochInstance, Segment  # noqa: E402
from independent_audit import solve_raw  # noqa: E402


class IndependentRawOracleTests(unittest.TestCase):
    def test_known_objective_witness(self):
        raw = solve_raw((((1, 1), (1, 1))), (((1, 1), (1, 1))), (2, 2), 4, 1)
        self.assertTrue(raw.feasible)
        self.assertEqual(raw.cost, 10)
        self.assertEqual(raw.epochs, 2)

    def test_validation_is_internal(self):
        with self.assertRaises(ValueError):
            solve_raw(((1, 2),), (), (0, 0), 4, 1)
        with self.assertRaises(ValueError):
            solve_raw(((1, 1),), (), (-1, 0), 4, 1)
        with self.assertRaises(ValueError):
            solve_raw(((1, 1),), (), (0, 0), 0, 1)

    def test_random_small_agreement(self):
        rng = random.Random(20260916)
        for case in range(500):
            raw_tiers = []
            tiers = []
            birth = 0
            for _source in (0, 1):
                raw = []
                modeled = []
                for _ in range(rng.randint(0, 4)):
                    occupied = rng.randint(1, 6)
                    live = rng.randint(0, occupied)
                    raw.append((occupied, live))
                    modeled.append(Segment(occupied, live, birth))
                    birth += 1
                raw_tiers.append(tuple(raw))
                tiers.append(tuple(modeled))
            free = (rng.randint(0, 10), rng.randint(0, 10))
            q = rng.randint(1, 10)
            mu = rng.randint(0, 4)
            independent = solve_raw(raw_tiers[0], raw_tiers[1], free, q, mu)
            exact = solve_normal_form(EpochInstance((tiers[0], tiers[1]), free, q, mu))
            with self.subTest(case=case):
                self.assertEqual(independent.feasible, exact.feasible)
                self.assertEqual(independent.cost, exact.cost)


if __name__ == "__main__":
    unittest.main()
