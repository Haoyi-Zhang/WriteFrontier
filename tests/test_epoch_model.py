import sys
import unittest
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from epoch_dp import (
    brute_force_oracle,
    confluence_audit,
    scan_feasibility,
    solve_normal_form,
    solve_unrestricted,
)
from epoch_model import (
    Batch,
    EpochInstance,
    Segment,
    batch_cost,
    lower_bound,
    one_epoch_per_source_orders,
    replay,
    round_up,
)
from epoch_policies import all_policies
from epoch_recovery import check_corpus, check_schedule
from trace_model import (
    make_trace_instances,
    read_cloudphysics,
    read_twitter,
    segment_window,
)


class ValidationTests(unittest.TestCase):
    def test_segment_validation(self):
        Segment(1, 0)
        Segment(1, 1)
        for args in ((0, 0), (1, -1), (1, 2)):
            with self.assertRaises(ValueError):
                Segment(*args)
        with self.assertRaises(TypeError):
            Segment(True, 1)

    def test_rounding(self):
        self.assertEqual(round_up(0, 4), 0)
        self.assertEqual(round_up(1, 4), 4)
        self.assertEqual(round_up(4, 4), 4)
        self.assertEqual(round_up(5, 4), 8)
        self.assertEqual(batch_cost(0, 4, 1), 1)

    def test_prefix_identity_and_replay(self):
        tiers = (
            (Segment(3, 2), Segment(2, 0)),
            (Segment(4, 1),),
        )
        instance = EpochInstance(tiers, (1, 2), 4, 1)
        schedule = (Batch(0, 0, 1), Batch(1, 0, 1), Batch(0, 1, 2))
        out = replay(instance, schedule)
        self.assertEqual(out["free"], instance.final_free())
        self.assertEqual(out["cost"], 11)
        with self.assertRaises(ValueError):
            replay(instance, (Batch(0, 1, 2),), require_complete=False)


class ExactnessTests(unittest.TestCase):
    def test_unequal_legal_costs(self):
        tiers = (
            (Segment(1, 1, 0), Segment(1, 1, 2)),
            (Segment(1, 1, 1), Segment(1, 1, 3)),
        )
        instance = EpochInstance(tiers, (2, 2), 4, 1)
        exact = solve_normal_form(instance)
        fragmented = (
            Batch(0, 0, 1),
            Batch(1, 0, 1),
            Batch(0, 1, 2),
            Batch(1, 1, 2),
        )
        self.assertEqual(exact.cost, 10)
        self.assertEqual(replay(instance, fragmented)["cost"], 20)

    def test_three_exact_implementations_agree(self):
        types = ((1, 0), (1, 1), (2, 1), (2, 2))
        sequences = [tuple(x) for n in (1, 2) for x in product(types, repeat=n)]
        checked = 0
        for raw0 in sequences[::3]:
            for raw1 in sequences[::4]:
                tiers = (
                    tuple(Segment(b, l, 2 * i) for i, (b, l) in enumerate(raw0)),
                    tuple(Segment(b, l, 2 * i + 1) for i, (b, l) in enumerate(raw1)),
                )
                for free in ((0, 0), (1, 1), (2, 2), (4, 4)):
                    instance = EpochInstance(tiers, free, 4, 1)
                    normal = solve_normal_form(instance)
                    unrestricted = solve_unrestricted(instance)
                    brute = brute_force_oracle(instance)
                    self.assertEqual((normal.status, normal.cost), (unrestricted.status, unrestricted.cost))
                    self.assertEqual((normal.status, normal.cost), (brute.status, brute.cost))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_adjacent_same_source_merge(self):
        instance = EpochInstance(
            (
                (Segment(2, 1), Segment(3, 2)),
                (Segment(5, 3),),
            ),
            (3, 3),
            4,
            1,
        )
        split = (Batch(0, 0, 1), Batch(0, 1, 2), Batch(1, 0, 1))
        merged = (Batch(0, 0, 2), Batch(1, 0, 1))
        split_out = replay(instance, split)
        merged_out = replay(instance, merged)
        self.assertEqual(split_out["free"], merged_out["free"])
        self.assertLessEqual(merged_out["cost"], split_out["cost"])

    def test_one_epoch_basin_hits_lower_bound(self):
        instance = EpochInstance(
            ((Segment(3, 2), Segment(1, 1)), (Segment(2, 1),)),
            (1, 3),
            4,
            1,
        )
        self.assertTrue(one_epoch_per_source_orders(instance))
        exact = solve_normal_form(instance)
        self.assertEqual(exact.cost, lower_bound(instance))

    def test_feasible_states_are_closed_under_legal_batches(self):
        types = ((1, 0), (1, 1), (2, 1), (2, 2))
        for raw0 in product(types, repeat=2):
            for raw1 in product(types, repeat=2):
                tiers = (
                    tuple(Segment(b, l, 2 * i) for i, (b, l) in enumerate(raw0)),
                    tuple(Segment(b, l, 2 * i + 1) for i, (b, l) in enumerate(raw1)),
                )
                instance = EpochInstance(tiers, (2, 2), 4, 1)
                audit = confluence_audit(instance)
                self.assertFalse(audit["violations"])
                self.assertEqual(audit["initial_feasible"], solve_normal_form(instance).feasible)

    def test_linear_scan_matches_exact_and_certifies_blocking(self):
        types = ((1, 0), (1, 1), (2, 1), (2, 2))
        sequences = [tuple(x) for n in (1, 2) for x in product(types, repeat=n)]
        checked = 0
        for raw0 in sequences[::2]:
            for raw1 in sequences[::3]:
                tiers = (
                    tuple(Segment(b, l, 2 * i) for i, (b, l) in enumerate(raw0)),
                    tuple(Segment(b, l, 2 * i + 1) for i, (b, l) in enumerate(raw1)),
                )
                for free in product(range(4), repeat=2):
                    instance = EpochInstance(tiers, free, 4, 1)
                    scan = scan_feasibility(instance)
                    exact = solve_normal_form(instance)
                    self.assertEqual(scan.feasible, exact.feasible)
                    if scan.feasible:
                        self.assertTrue(replay(instance, scan.schedule)["complete"])
                    else:
                        self.assertIsNotNone(scan.blocking_state)
                        self.assertIsNotNone(scan.blocking_free)
                        self.assertIsNotNone(scan.next_live)
                        assert scan.blocking_free is not None and scan.next_live is not None
                        for source in (0, 1):
                            live = scan.next_live[source]
                            if live is not None:
                                self.assertGreater(live, scan.blocking_free[1 - source])
                    checked += 1
        self.assertGreater(checked, 1000)

    def test_reserve_dominance(self):
        tiers = (
            (Segment(2, 2), Segment(2, 1)),
            (Segment(3, 2), Segment(1, 0)),
        )
        base = EpochInstance(tiers, (2, 2), 4, 1)
        base_solution = solve_normal_form(base)
        self.assertTrue(base_solution.feasible)
        for extra0, extra1 in product(range(3), repeat=2):
            larger = EpochInstance(tiers, (2 + extra0, 2 + extra1), 4, 1)
            solution = solve_normal_form(larger)
            self.assertTrue(solution.feasible)
            self.assertLessEqual(solution.cost, base_solution.cost)
            replay(larger, base_solution.schedule)

    def test_policy_results_replay_when_complete(self):
        instance = EpochInstance(
            ((Segment(3, 2, 0), Segment(2, 1, 2)), (Segment(2, 1, 1), Segment(3, 2, 3))),
            (2, 2),
            4,
            1,
        )
        for result in all_policies(instance):
            if result.status == "complete":
                self.assertEqual(replay(instance, result.schedule)["cost"], result.cost)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.instance = EpochInstance(
            ((Segment(3, 2), Segment(2, 1)), (Segment(2, 1), Segment(3, 2))),
            (2, 2),
            4,
            1,
        )
        self.solution = solve_normal_form(self.instance)
        self.assertTrue(self.solution.feasible)

    def test_correct_protocol(self):
        out = check_schedule(self.instance, self.solution.schedule)
        self.assertEqual(out["failures"], 0)

    def test_negative_controls(self):
        for mutation in (
            "publish-before-flush",
            "reclaim-before-commit",
            "omit-last-token",
            "torn-commit-reclaim",
        ):
            with self.subTest(mutation=mutation):
                self.assertTrue(check_schedule(self.instance, self.solution.schedule, mutation)["detected"])

    def test_corpus_summary(self):
        summary = check_corpus([(self.instance, self.solution.schedule)])
        self.assertEqual(summary.normal_failures, 0)
        self.assertEqual(summary.mutation_runs, summary.mutation_runs_detected)


class TraceTests(unittest.TestCase):
    def test_public_excerpt_parsers(self):
        cloud = read_cloudphysics(HERE / "inputs" / "cloudphysics-prefix.csv")
        twitter = read_twitter(HERE / "inputs" / "twitter-cluster015-prefix.csv")
        self.assertEqual(len(cloud), 128)
        self.assertEqual(len(twitter), 128)
        self.assertEqual(cloud[0].size_bytes, 512)
        self.assertEqual(twitter[0].operation, "set")

    def test_segmentation_preserves_latest_versions(self):
        requests = read_cloudphysics(HERE / "inputs" / "cloudphysics-prefix.csv", limit=64)
        tier0, tier1, raw = segment_window(requests, target_bytes=65536, allocation_unit=512)
        self.assertGreaterEqual(len(raw), 2)
        self.assertEqual(sum(s.occupied for s in tier0 + tier1), sum((r.occupied_bytes + 511) // 512 for r in raw))
        self.assertLessEqual(sum(s.live for s in tier0 + tier1), sum(s.occupied for s in tier0 + tier1))

    def test_trace_instances_are_feasible(self):
        requests = read_twitter(HERE / "inputs" / "twitter-cluster015-prefix.csv")
        items = make_trace_instances(
            requests,
            window_rows=64,
            target_bytes=2048,
            allocation_unit=64,
            page_bytes=4096,
            commit_bytes=64,
            extra_slacks=(0,),
        )
        self.assertEqual(len(items), 2)
        for item in items:
            instance = item["instance"]
            self.assertTrue(solve_normal_form(instance).feasible)


if __name__ == "__main__":
    unittest.main()
