"""Check the retained scientific points without importing a drawing backend."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from plots.draw_frontiers import reviewed_points


class RetainedFigureInputs(unittest.TestCase):
    def test_unit_frontier_is_the_exact_retained_domain(self):
        unit, _ = reviewed_points(ROOT / 'results/frontier')
        self.assertEqual(tuple(x for x, _ in unit), tuple(range(1, 17)))
        self.assertEqual(tuple(y for x, y in unit), tuple((128+x-1)//x+1 for x in range(1, 17)))

    def test_slack_points_keep_the_declared_denominator_and_range(self):
        _, slack = reviewed_points(ROOT / 'results/frontier')
        self.assertEqual(tuple(x for x, _ in slack), tuple(range(7)))
        self.assertTrue(all(a[1] <= b[1] for a, b in zip(slack, slack[1:])))
        self.assertEqual(slack[3][1], 100)


if __name__ == '__main__':
    unittest.main()
