"""Exact comparisons against numeric enumeration and raw tuple search."""
import sys
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from epoch_model import EpochInstance, Segment, replay
from epoch_dp import (reserve_thresholds, best_split_at_budget, pareto_frontier,
                      find_min_common_slack, final_fit_free_lower_bound,
                      solve_normal_form, SearchBudgetExceeded)
from epoch_policies import maximum_prefix_start, two_start_maximum_prefix
from independent_audit import solve_raw
from destination_model import audit_destinations


def small_tiers():
    types = ((1, 0), (2, 2))
    sequences = [()] + [s for n in (1, 2) for s in product(types, repeat=n)]
    for raw0, raw1 in product(sequences, repeat=2):
        yield tuple(tuple(Segment(b, l) for b, l in raw) for raw in (raw0, raw1))


class CapacityEventTests(unittest.TestCase):
    def test_graph_cost_invariance_within_event_cells(self):
        for tiers in small_tiers():
            thresholds = reserve_thresholds(tiers)
            raw = tuple(tuple((s.occupied, s.live) for s in t) for t in tiers)
            for free in product(range(6), repeat=2):
                rounded = tuple(max(t for t in thresholds[s] if t <= free[s]) for s in (0, 1))
                for q, mu in ((1, 0), (3, 1)):
                    a = solve_raw(*raw, free, q, mu)
                    b = solve_raw(*raw, rounded, q, mu)
                    self.assertEqual((a.feasible, a.cost, a.epochs), (b.feasible, b.cost, b.epochs))
                for i, j in product(range(len(tiers[0]) + 1), range(len(tiers[1]) + 1)):
                    for source in (0, 1):
                        start = (i, j)[source]
                        for end in range(start + 1, len(tiers[source]) + 1):
                            live = sum(s.live for s in tiers[source][start:end])
                            guard = lambda f: live <= EpochInstance(tiers, f).free_at(i, j)[1 - source]
                            self.assertEqual(guard(free), guard(rounded))

    def test_budget_and_pareto_match_full_numeric_enumeration(self):
        for tiers in small_tiers():
            candidates = []
            for free in product(range(7), repeat=2):
                solution = solve_normal_form(EpochInstance(tiers, free, 3, 1))
                if solution.feasible:
                    candidates.append((solution.cost, sum(free), *free))
            for budget in range(7):
                expected = min((x for x in candidates if x[1] <= budget), default=None)
                actual = best_split_at_budget(tiers, budget, 3, 1)
                self.assertEqual(actual is None, expected is None)
                if actual:
                    model, solution = actual
                    self.assertEqual((solution.cost, sum(model.free), *model.free), expected)
            expected = {x[2:] for x in candidates if not any(
                y[2] <= x[2] and y[3] <= x[3] and y[2:] != x[2:] for y in candidates)}
            actual = pareto_frontier(tiers, (6, 6), 3, 1)
            self.assertEqual({(x['free0'], x['free1']) for x in actual}, expected)

    def test_common_slack_matches_unit_search_and_upper_bound(self):
        for tiers in small_tiers():
            base = final_fit_free_lower_bound(tiers)
            expected = next(s for s in range(9) if solve_normal_form(
                EpochInstance(tiers, (base[0] + s, base[1] + s), 3, 1)).feasible)
            slack, instance, solution = find_min_common_slack(tiers, 3, 1)
            self.assertEqual(slack, expected)
            self.assertEqual(instance.free, (base[0] + expected, base[1] + expected))
            self.assertEqual(solution.cost, solve_normal_form(instance).cost)
            self.assertEqual(find_min_common_slack(tiers, 3, 1, expected)[0], expected)
            if expected:
                with self.assertRaises(SearchBudgetExceeded):
                    find_min_common_slack(tiers, 3, 1, expected - 1)

    def test_large_integer_sizes_do_not_cause_unit_iteration(self):
        size = 10**12
        tiers = ((Segment(size, size),), (Segment(size, size),))
        self.assertEqual(reserve_thresholds(tiers), ((0, size), (0, size)))
        with patch('epoch_dp.solve_normal_form', wraps=solve_normal_form) as counted:
            instance, solution = best_split_at_budget(tiers, 2 * size + 7)
            self.assertLessEqual(counted.call_count, 4)
            self.assertEqual(instance.free, (0, size))
            self.assertTrue(solution.feasible)
        self.assertEqual(find_min_common_slack(tiers)[0], size)
        for bad in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                best_split_at_budget(tiers, bad)
            with self.assertRaises(ValueError):
                find_min_common_slack(tiers, max_slack=bad)


class GreedyTests(unittest.TestCase):
    def test_two_starts_replay_and_preserve_feasibility(self):
        for tiers in small_tiers():
            for free in product(range(4), repeat=2):
                model = EpochInstance(tiers, free, 3, 1)
                exact = solve_normal_form(model)
                starts = [maximum_prefix_start(model, s) for s in (0, 1)]
                result = two_start_maximum_prefix(model)
                self.assertEqual(result.status == 'complete', exact.feasible)
                for start in starts:
                    self.assertEqual(start.status == 'complete', exact.feasible)
                if exact.feasible:
                    self.assertEqual(result.cost, min(x.cost for x in starts))
                    self.assertEqual(replay(model, result.schedule)['cost'], result.cost)
                    self.assertGreaterEqual(result.cost, exact.cost)
                    for event in replay(model, result.schedule)['events']:
                        end, source = event['end'], event['source']
                        if end < len(tiers[source]):
                            self.assertGreater(event['live'] + tiers[source][end].live,
                                               event['before'][1 - source])

    def test_start_validation(self):
        model = EpochInstance(((), ()), (0, 0))
        for bad in (-1, 2, True, 1.5):
            with self.assertRaises(ValueError):
                maximum_prefix_start(model, bad)

    def test_unit_family_matches_proven_epoch_count(self):
        for n in range(1, 11):
            for r in range(1, n + 1):
                tiers = ((Segment(1, 1),) * n,) * 2
                model = EpochInstance(tiers, (r, r), 2 * r, 1)
                greedy = two_start_maximum_prefix(model)
                expected = ((n + r - 1) // r + 1) * (2 * r + 1)
                self.assertEqual(greedy.cost, expected)
                self.assertEqual(solve_normal_form(model).cost, expected)

    def test_maximum_prefix_is_not_universally_cost_optimal(self):
        raw = (((19, 8), (4, 0), (20, 11), (16, 2), (7, 5),
                (17, 16), (30, 20), (24, 24), (24, 17)),
               ((23, 5), (20, 14), (4, 4), (14, 9), (11, 9), (25, 6), (18, 0)))
        tiers = tuple(tuple(Segment(b, l) for b, l in t) for t in raw)
        model = EpochInstance(tiers, (5, 5), 4, 0)
        self.assertEqual(two_start_maximum_prefix(model).cost, 160)
        self.assertEqual(solve_normal_form(model).cost, 156)
        self.assertEqual(solve_raw(*raw, model.free, 4, 0).cost, 156)


class DestinationTests(unittest.TestCase):
    def test_shared_destination_legal_choice_deadlock(self):
        result = audit_destinations((((1, 1),),) * 3, (2, 2, 1), (0, 0, 1))
        self.assertTrue(result['initial_feasible'])
        self.assertEqual(result['final_free'], [1, 0, 0])
        self.assertEqual(result['completion'], [[1, 0, 1], [2, 0, 1], [0, 0, 1]])
        self.assertIn({'state': [0, 0, 0], 'free': [0, 0, 1], 'batch': [0, 0, 1],
                       'successor': [1, 0, 0], 'successor_free': [1, 0, 0]}, result['violations'])

    def test_three_tier_cycle_is_confluent_on_finite_domain(self):
        types = ((1, 0), (1, 1), (2, 1), (2, 2))
        for raw in product(types, repeat=3):
            tiers = tuple((s,) for s in raw)
            for free in product(range(3), repeat=3):
                self.assertFalse(audit_destinations(tiers, (1, 2, 0), free)['violations'])

    def test_fifo_two_segment_cycle(self):
        for free in product(range(3), repeat=4):
            tiers = (((2, 2), (1, 0)), ((1, 1), (2, 1)),
                     ((1, 0), (1, 1)), ((2, 1), (2, 2)))
            self.assertFalse(audit_destinations(tiers, (1, 2, 3, 0), free)['violations'])


if __name__ == '__main__':
    unittest.main()
