import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE))

from check_ordered_certificate import (
    InvalidOrderedCertificate,
    check_ordered_certificate,
)
from epoch_dp import make_blocking_certificate, scan_feasibility, solve_normal_form
from epoch_model import (
    Batch,
    EpochInstance,
    Segment,
    deserialize_instance,
    deserialize_schedule,
    serialize_instance,
    serialize_schedule,
)
from epoch_policies import gain_per_write, leveled_proxy, size_tiered_proxy
from epoch_recovery import check_corpus
from verify_results import validate_result_directory


class SerializationSchemaTests(unittest.TestCase):
    def setUp(self):
        self.instance = EpochInstance(
            (
                (Segment(3, 2, 0, "a"), Segment(1, 0, 2, "b")),
                (Segment(2, 1, 1, "c"),),
            ),
            (2, 3),
            4,
            1,
            "round-trip",
        )

    def test_instance_and_schedule_round_trip(self):
        self.assertEqual(deserialize_instance(serialize_instance(self.instance)), self.instance)
        schedule = (Batch(0, 0, 1), Batch(1, 0, 1), Batch(0, 1, 2))
        self.assertEqual(deserialize_schedule(serialize_schedule(schedule)), schedule)

    def test_exactly_two_tiers_are_required_before_construction(self):
        payload = serialize_instance(self.instance)
        payload["tiers"].append([{"occupied": 99, "live": 99}])
        with self.assertRaises(ValueError):
            deserialize_instance(payload)

    def test_bool_and_fractional_numbers_are_rejected_before_conversion(self):
        payload = serialize_instance(self.instance)
        payload["quantum"] = True
        with self.assertRaises(TypeError):
            deserialize_instance(payload)
        payload = serialize_instance(self.instance)
        payload["commit_bytes"] = 1.5
        with self.assertRaises(TypeError):
            deserialize_instance(payload)
        with self.assertRaises(TypeError):
            deserialize_schedule([{"source": False, "start": 0, "end": 1}])
        with self.assertRaises(TypeError):
            deserialize_schedule([{"source": 0, "start": 0.0, "end": 1}])


class PolicyScoringTests(unittest.TestCase):
    def test_leveled_prefers_occupied_before_live(self):
        # The occupied and live rankings deliberately disagree: source 0
        # reclaims more occupied bytes (10 > 9), while source 1 copies more
        # live bytes (9 > 1).  The implemented leveled score chooses source 0.
        instance = EpochInstance(
            ((Segment(10, 1, 5),), (Segment(9, 9, 0),)),
            (9, 9),
            4,
            1,
        )
        result = leveled_proxy(instance)
        self.assertEqual(result.schedule[0].source, 0)

    def test_size_tiered_uses_fanin_four(self):
        instance = EpochInstance(
            (tuple(Segment(2, 1, birth) for birth in range(5)), ()),
            (0, 8),
            4,
            1,
        )
        result = size_tiered_proxy(instance)
        self.assertEqual((result.schedule[0].start, result.schedule[0].end), (0, 4))

    def test_size_tiered_stops_at_twofold_size_boundary(self):
        instance = EpochInstance(
            ((Segment(2, 1, 0), Segment(4, 1, 1), Segment(9, 1, 2)), ()),
            (0, 8),
            4,
            1,
        )
        result = size_tiered_proxy(instance)
        self.assertEqual((result.schedule[0].start, result.schedule[0].end), (0, 2))

    def test_gain_per_write_tie_prefers_greater_occupied_gain(self):
        # q=1 and mu=0 make both prefixes reclaim two occupied bytes per
        # modeled write unit.  The documented tie-break selects the larger
        # occupied gain, hence the two-segment prefix.
        instance = EpochInstance(
            ((Segment(2, 1, 0), Segment(2, 1, 1)), ()),
            (0, 2),
            1,
            0,
        )
        result = gain_per_write(instance)
        self.assertEqual((result.schedule[0].start, result.schedule[0].end), (0, 2))


    def test_gain_per_write_distinguishes_close_cross_source_ratios(self):
        n = 2**54
        instance = EpochInstance(
            ((Segment(n, 1, 0),), (Segment(n + 1, 1, 1),)), (1, 1), 1, 0
        )
        self.assertEqual(gain_per_write(instance).schedule[0].source, 1)

    def test_gain_per_write_distinguishes_close_prefix_ratios(self):
        n = 2**54
        instance = EpochInstance(
            ((Segment(n + 1, 1), Segment(n - 1, 1)), ()), (0, 2), 1, 0
        )
        self.assertEqual(gain_per_write(instance).schedule[0].end, 1)

    def test_gain_per_write_handles_finite_large_integer_gain(self):
        instance = EpochInstance(
            ((Segment(10**400, 1),), (Segment(1, 1),)), (1, 1), 1, 0
        )
        self.assertEqual(gain_per_write(instance).schedule[0].source, 0)

    def test_gain_per_write_prioritizes_zero_cost_across_sources(self):
        instance = EpochInstance(
            ((Segment(1, 0, 1),), (Segment(100, 1, 0),)), (1, 1), 1, 0
        )
        self.assertEqual(gain_per_write(instance).schedule[0].source, 0)

    def test_gain_per_write_does_not_merge_zero_cost_with_paid_prefix(self):
        instance = EpochInstance(
            ((Segment(1, 0), Segment(100, 1)), ()), (0, 1), 1, 0
        )
        self.assertEqual(gain_per_write(instance).schedule[0].end, 1)

    def test_gain_per_write_zero_cost_ties_use_documented_order(self):
        instance = EpochInstance(
            ((Segment(1, 0, 2), Segment(2, 0, 3)), (Segment(1, 0, 1),)),
            (0, 0), 1, 0,
        )
        result = gain_per_write(instance)
        self.assertEqual(result.schedule[0].source, 1)
        self.assertEqual(result.schedule[1], Batch(0, 0, 2))


class OrderedCertificateTests(unittest.TestCase):
    def test_blocking_certificate_replays_and_checks(self):
        instance = EpochInstance(
            ((Segment(2, 2),), (Segment(2, 2),)),
            (1, 1),
            4,
            1,
            "blocked",
        )
        scan = scan_feasibility(instance)
        self.assertFalse(scan.feasible)
        certificate = make_blocking_certificate(instance, scan)
        out = check_ordered_certificate(certificate)
        self.assertTrue(out["valid"])
        self.assertEqual(out["reached_state"], [0, 0])

    def test_tampered_fields_are_rejected(self):
        instance = EpochInstance(
            ((Segment(2, 2),), (Segment(2, 2),)), (1, 1), 4, 1
        )
        certificate = make_blocking_certificate(instance)
        for field, replacement in (
            ("reached_state", [1, 0]),
            ("free", [2, 1]),
            ("next_live", [1, 2]),
        ):
            tampered = copy.deepcopy(certificate)
            tampered[field] = replacement
            with self.subTest(field=field), self.assertRaises(InvalidOrderedCertificate):
                check_ordered_certificate(tampered)

    def test_terminal_state_cannot_masquerade_as_blocking(self):
        instance = EpochInstance(((Segment(1, 0),), ()), (0, 0), 4, 1)
        certificate = {
            "kind": "ordered-prefix-block",
            "instance": serialize_instance(instance),
            "partial_schedule": serialize_schedule((Batch(0, 0, 1),)),
            "reached_state": [1, 0],
            "free": [1, 0],
            "next_live": [None, None],
        }
        with self.assertRaises(InvalidOrderedCertificate):
            check_ordered_certificate(certificate)

    def test_one_source_may_be_exhausted_at_a_real_block(self):
        instance = EpochInstance(((), (Segment(2, 2),)), (1, 0), 4, 1)
        certificate = make_blocking_certificate(instance)
        out = check_ordered_certificate(certificate)
        self.assertEqual(out["exhausted_sources"], [0])


class RecoveryClassCountTests(unittest.TestCase):
    def test_all_dead_schedule_skips_only_payload_truncation(self):
        live = EpochInstance(((Segment(1, 1),), ()), (0, 1), 4, 1)
        dead = EpochInstance(((Segment(1, 0),), ()), (0, 0), 4, 1)
        corpus = [
            (live, solve_normal_form(live).schedule),
            (dead, solve_normal_form(dead).schedule),
        ]
        summary = check_corpus(corpus)
        self.assertEqual(summary.all_dead_schedules, 1)
        self.assertEqual(summary.mutation_classes["publish-before-flush"]["runs"], 2)
        self.assertEqual(summary.mutation_classes["reclaim-before-commit"]["runs"], 2)
        self.assertEqual(summary.mutation_classes["torn-commit-reclaim"]["runs"], 2)
        self.assertEqual(
            summary.mutation_classes["truncate-persisted-payload"]["runs"], 1
        )
        self.assertEqual(
            summary.mutation_classes["truncate-persisted-payload"]["skipped"], 1
        )


class ResultDirectoryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.reference = HERE / "results" / "frontier"
        cls.scratch = Path(cls.tempdir.name) / "frontier"
        shutil.copytree(cls.reference, cls.scratch)

    @classmethod
    def tearDownClass(cls):
        cls.tempdir.cleanup()

    def test_normal_directory_and_auxiliary_runtime_logs(self):
        validate_result_directory(self.scratch)
        (self.scratch / "review.log").write_text("auxiliary log\n", encoding="utf-8")
        runtime = self.scratch / "runtime"
        runtime.mkdir(exist_ok=True)
        (runtime / "resource.json").write_text("{}\n", encoding="utf-8")
        validate_result_directory(self.scratch)

    def test_multiple_extra_top_level_csv_json_are_rejected(self):
        extra_json = self.scratch / "unexpected.json"
        extra_csv = self.scratch / "unexpected.csv"
        extra_json.write_text("{}\n", encoding="utf-8")
        extra_csv.write_text("x\n1\n", encoding="utf-8")
        try:
            with self.assertRaises(ValueError):
                validate_result_directory(self.scratch)
        finally:
            extra_json.unlink()
            extra_csv.unlink()

    def test_missing_scientific_file_is_rejected(self):
        target = self.scratch / "summary.json"
        backup = target.read_bytes()
        target.unlink()
        try:
            with self.assertRaises(ValueError):
                validate_result_directory(self.scratch)
        finally:
            target.write_bytes(backup)


if __name__ == "__main__":
    unittest.main()
