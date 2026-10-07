"""Finite owned integer cases; independent explicit-capacity definition."""
from itertools import product
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from epoch_model import EpochInstance, Segment, replay
from epoch_dp import solve_normal_form, solve_unrestricted, SearchBudgetExceeded


def cases():
    types = ((1, 0), (1, 1), (2, 1), (2, 2))
    sequences = [()] + [tuple(seq) for n in (1, 2) for seq in product(types, repeat=n)]
    for raw0, raw1 in product(sequences, repeat=2):
        for free in product(range(3), repeat=2):
            for quantum, commit in ((1, 0), (4, 1)):
                yield (raw0, raw1), free, quantum, commit


def instance(data):
    tiers, free, quantum, commit = data
    return EpochInstance(tuple(tuple(Segment(b, l) for b, l in tier) for tier in tiers),
                         free, quantum, commit)


def definition(data):
    """Enumerate every legal schedule; no prefix identity, memo or core helper."""
    tiers, free, quantum, commit = data
    best = None
    def visit(indices, capacity, cost, epochs):
        nonlocal best
        if all(indices[s] == len(tiers[s]) for s in (0, 1)):
            score = (cost, epochs)
            if best is None or score < best:
                best = score
            return
        for s in (0, 1):
            occupied = live = 0
            for end in range(indices[s] + 1, len(tiers[s]) + 1):
                b, l = tiers[s][end - 1]
                occupied += b
                live += l
                if live > capacity[1 - s]:
                    break
                following, next_indices = list(capacity), list(indices)
                following[s] += occupied
                following[1 - s] -= live
                next_indices[s] = end
                rounded = 0 if live == 0 else ((live - 1) // quantum + 1) * quantum
                visit(tuple(next_indices), tuple(following), cost + rounded + commit, epochs + 1)
    visit((0, 0), free, 0, 0)
    return best


def direct_free(data, i, j):
    tiers, free, _, _ = data
    return (free[0] + sum(b for b, _ in tiers[0][:i]) - sum(l for _, l in tiers[1][:j]),
            free[1] + sum(b for b, _ in tiers[1][:j]) - sum(l for _, l in tiers[0][:i]))


class PreparedPrefixTests(unittest.TestCase):
    def test_complete_solutions_and_replay_against_schedule_definition(self):
        for data in cases():
            expected, model = definition(data), instance(data)
            for solve in (solve_normal_form, solve_unrestricted):
                solution = solve(model)
                self.assertEqual(solution.feasible, expected is not None)
                if expected is not None:
                    self.assertEqual((solution.cost, solution.batches), expected)
                    trace = replay(model, solution.schedule)
                    self.assertTrue(trace['complete'])
                    self.assertEqual(trace['cost'], expected[0])
                    for event in trace['events']:
                        self.assertGreaterEqual(min(event['shadow']), 0)

    def test_every_prefix_identity_including_unreachable_negative_states(self):
        for data in cases():
            model = instance(data)
            o0, o1, l0, l1 = model.prefix_arrays()
            for i, j in product(range(len(data[0][0]) + 1), range(len(data[0][1]) + 1)):
                expected = direct_free(data, i, j)
                self.assertEqual(model.free_at(i, j), expected)
                self.assertEqual((model.free[0] + o0[i] - l1[j], model.free[1] + o1[j] - l0[i]), expected)

    def test_dead_prefix_rounding_budget_and_input_controls(self):
        tiers = (((3, 0), (2, 2), (1, 1)), ((1, 1), (4, 0), (2, 1)))
        for free, q, mu in product(((0, 0), (1, 1), (2, 1), (3, 3)), (1, 3, 4), (0, 1)):
            data = tiers, free, q, mu
            expected, model = definition(data), instance(data)
            for solve in (solve_normal_form, solve_unrestricted):
                solution = solve(model)
                self.assertEqual(solution.feasible, expected is not None)
                if expected is not None:
                    self.assertEqual((solution.cost, solution.batches), expected)
        model = instance(((((1, 1),), ((1, 1),)), (1, 1), 4, 1))
        for solve in (solve_normal_form, solve_unrestricted):
            with self.assertRaises(SearchBudgetExceeded):
                solve(model, max_states=1)
        self.assertEqual(solve_normal_form(EpochInstance(((), ()), (0, 0)), max_states=0).cost, 0)
        with self.assertRaises(SearchBudgetExceeded):
            solve_unrestricted(EpochInstance(((), ()), (0, 0)), max_states=0)
        for bad in (True, 1.5):
            with self.assertRaises(TypeError):
                Segment(bad, 0)
        with self.assertRaises(ValueError):
            EpochInstance(((), ()), (0, 0), quantum=0)


if __name__ == '__main__':
    unittest.main()
