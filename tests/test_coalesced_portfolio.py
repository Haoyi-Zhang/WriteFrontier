"""Benign owned fixtures for coalescing and an optimum-oblivious portfolio."""
import ast
import subprocess
import sys
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from epoch_model import Batch, EpochInstance, Segment, replay
from epoch_policies import (
    PolicyResult, all_policies, coalesce_adjacent_same_source,
    coalesced_policy_candidates, coalesced_portfolio, lru_tiered_proxy,
    select_replayed_portfolio, two_start_maximum_prefix,
)
from independent_audit import solve_raw  # Evaluation oracle, not policy dependency.


class CoalescingTests(unittest.TestCase):
    def test_pure_contiguous_coalescing_and_idempotence(self):
        original = [Batch(0, 0, 1), Batch(0, 1, 2), Batch(1, 0, 1),
                    Batch(0, 2, 3), Batch(0, 3, 4)]
        snapshot = list(original)
        merged = coalesce_adjacent_same_source(iter(original))
        self.assertEqual(merged, (Batch(0, 0, 2), Batch(1, 0, 1), Batch(0, 2, 4)))
        self.assertEqual(original, snapshot)
        self.assertEqual(coalesce_adjacent_same_source(merged), merged)
        self.assertEqual(coalesce_adjacent_same_source(()), ())

    def test_gaps_overlaps_and_non_batches_are_rejected(self):
        for end, start in ((1, 2), (2, 1)):
            with self.assertRaises(ValueError):
                coalesce_adjacent_same_source((Batch(0, 0, end), Batch(0, start, 3)))
        with self.assertRaises(TypeError):
            coalesce_adjacent_same_source(({"source": 0, "start": 0, "end": 1},))

    def test_owned_fifteen_to_ten_witness_preserves_raw_output(self):
        model = EpochInstance(
            ((Segment(1, 1, 0), Segment(1, 1, 2)), (Segment(1, 1, 10),)),
            (2, 2), 4, 1,
        )
        original = tuple(p.as_dict() for p in all_policies(model))
        raw = lru_tiered_proxy(model)
        self.assertEqual(raw.cost, 15)
        merged = coalesced_policy_candidates(model)[0]
        self.assertEqual(merged.policy, "coalesced-lru-tiered-proxy")
        self.assertEqual(merged.cost, 10)
        self.assertEqual(merged.schedule, (Batch(0, 0, 2), Batch(1, 0, 1)))
        self.assertEqual(original, tuple(p.as_dict() for p in all_policies(model)))
        self.assertEqual([p.policy for p in all_policies(model)],
                         ["lru-tiered-proxy", "leveled-proxy", "size-tiered-proxy", "gain-per-write"])

    def test_coalescing_is_a_distinct_fanin_variant(self):
        model = EpochInstance((tuple(Segment(1, 1) for _ in range(5)), ()), (0, 5), 4, 1)
        raw = all_policies(model)[2]
        merged = coalesced_policy_candidates(model)[2]
        self.assertEqual(raw.schedule, (Batch(0, 0, 4), Batch(0, 4, 5)))
        self.assertEqual(merged.schedule, (Batch(0, 0, 5),))
        self.assertLess(merged.cost, raw.cost)

    def test_empty_and_blocked_instances(self):
        result = coalesced_portfolio(EpochInstance(((), ()), (0, 0)))
        self.assertEqual((result.status, result.cost, result.schedule), ("complete", 0, ()))
        model = EpochInstance(((Segment(2, 2),), (Segment(2, 2),)), (1, 1))
        candidates = coalesced_policy_candidates(model)
        self.assertTrue(all(p.status == "blocked" and p.cost is None for p in candidates))
        self.assertEqual(coalesced_portfolio(model).status, "blocked")


class PortfolioTests(unittest.TestCase):
    def test_selection_uses_replay_not_claimed_cost_or_lower_bound(self):
        model = EpochInstance(((Segment(1, 1), Segment(1, 1)), ()), (0, 2), 4, 1)
        split, whole = (Batch(0, 0, 1), Batch(0, 1, 2)), (Batch(0, 0, 2),)
        candidates = (
            PolicyResult("a-split", "complete", split, -999, -999),
            PolicyResult("z-whole", "complete", whole, 999, 999),
            PolicyResult("b-whole", "complete", whole, 99999, 99999),
        )
        selected = select_replayed_portfolio(model, candidates)
        self.assertEqual((selected.cost, selected.schedule, selected.reason), (5, whole, "b-whole"))
        self.assertEqual(selected, select_replayed_portfolio(model, reversed(candidates)))

    def test_epoch_tie_break_precedes_name(self):
        model = EpochInstance(((Segment(1, 1), Segment(1, 1)), ()), (0, 2), 1, 0)
        split, whole = (Batch(0, 0, 1), Batch(0, 1, 2)), (Batch(0, 0, 2),)
        selected = select_replayed_portfolio(model, (
            PolicyResult("a-split", "complete", split, 2, 2),
            PolicyResult("z-whole", "complete", whole, 2, 2),
        ))
        self.assertEqual((selected.cost, selected.reason, len(selected.schedule)), (2, "z-whole", 1))

    def test_invalid_complete_candidate_cannot_earn_a_low_score(self):
        model = EpochInstance(((Segment(1, 1),), ()), (0, 1))
        with self.assertRaises(ValueError):
            select_replayed_portfolio(model, (PolicyResult("bad", "complete", (), 0, 0),))

    def test_wrapper_uses_only_replayed_candidates(self):
        model = EpochInstance(((Segment(1, 1),), ()), (0, 1))
        candidate = PolicyResult("candidate", "complete", (Batch(0, 0, 1),), -1, -1)
        with patch("epoch_policies.coalesced_policy_candidates", return_value=(candidate,)):
            result = coalesced_portfolio(model)
        self.assertEqual((result.cost, result.reason), (5, "candidate"))

    def test_complete_finite_owned_domain_and_original_policy_replay(self):
        types = ((1, 0), (2, 2))
        sequences = [()] + [s for n in (1, 2) for s in product(types, repeat=n)]
        checked = 0
        for raw0, raw1 in product(sequences, repeat=2):
            tiers = tuple(tuple(Segment(b, l, 2*i+s) for i, (b, l) in enumerate(t))
                          for s, t in enumerate((raw0, raw1)))
            for free in product(range(4), repeat=2):
                for q, mu in ((1, 0), (3, 0), (4, 1)):
                    model = EpochInstance(tiers, free, q, mu)
                    truth = solve_raw(raw0, raw1, free, q, mu)
                    original = (*all_policies(model), two_start_maximum_prefix(model))
                    merged = coalesced_policy_candidates(model)
                    selected = coalesced_portfolio(model)
                    self.assertEqual(selected.status == "complete", truth.feasible)
                    for a, b in zip(original, merged):
                        self.assertEqual((a.status, b.status), (selected.status, selected.status))
                        if truth.feasible:
                            self.assertEqual(replay(model, a.schedule)["cost"], a.cost)
                            self.assertEqual(replay(model, b.schedule)["cost"], b.cost)
                            self.assertLessEqual(b.cost, a.cost)
                            self.assertGreaterEqual(b.cost, truth.cost)
                    if truth.feasible:
                        winner = min(merged, key=lambda p: (replay(model, p.schedule)["cost"], len(p.schedule), p.policy))
                        self.assertEqual((selected.cost, selected.reason), (winner.cost, winner.policy))
                        self.assertEqual(replay(model, selected.schedule)["cost"], selected.cost)
                    checked += 1
        self.assertEqual(checked, 2352)

    def test_policy_import_tree_has_no_solver_or_oracle(self):
        # The model is the only project import used by the policy module.
        tree = ast.parse((HERE / "src/epoch_policies.py").read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append((node.module or "").split(".")[0])
        self.assertEqual(set(modules),
                         {"__future__", "dataclasses", "fractions", "typing", "epoch_model"})
        model_tree = ast.parse((HERE / "src/epoch_model.py").read_text(encoding="utf-8"))
        model_modules = {node.module for node in ast.walk(model_tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(model_modules, {"__future__", "dataclasses", "typing"})

    def test_real_policy_executes_when_oracle_imports_are_forbidden(self):
        code = """
import builtins
import sys
sys.path.insert(0, sys.argv[1])
original = builtins.__import__
forbidden = {"epoch_dp", "independent_audit", "oracle", "run_policy_frontier"}
def guarded(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError("policy attempted solver/oracle import: " + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from epoch_model import EpochInstance, Segment
from epoch_policies import coalesced_portfolio
model = EpochInstance(((Segment(1,1,0), Segment(1,1,2)), (Segment(1,1,10),)), (2,2), 4, 1)
result = coalesced_portfolio(model)
assert result.status == "complete" and result.cost == 10
assert not (forbidden & set(sys.modules))
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(HERE / "src")],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
