"""Finite owned fixtures for audit-count scope and trace identity metadata."""
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from epoch_dp import confluence_audit, solve_normal_form
from epoch_model import EpochInstance, Segment, replay
from trace_model import Request, make_trace_instances


class ConfluenceCountTests(unittest.TestCase):
    def test_terminal_only_instance_has_no_counted_states(self):
        self.assertEqual(
            confluence_audit(EpochInstance(((), ()), (0, 0))),
            {
                "initial_feasible": True,
                "viable_states": 0,
                "legal_edges_from_viable_states": 0,
                "violations": [],
            },
        )

    def test_one_source_excludes_terminal_for_live_and_dead_payload(self):
        for live in (0, 1):
            with self.subTest(live=live):
                audit = confluence_audit(
                    EpochInstance(((Segment(1, live),), ()), (0, 1))
                )
                self.assertTrue(audit["initial_feasible"])
                self.assertEqual(audit["viable_states"], 1)
                self.assertEqual(audit["legal_edges_from_viable_states"], 1)
                self.assertEqual(audit["violations"], [])

    def test_two_sources_count_three_nonterminal_prefix_states(self):
        audit = confluence_audit(
            EpochInstance(((Segment(1, 1),), (Segment(1, 1),)), (1, 1))
        )
        self.assertTrue(audit["initial_feasible"])
        self.assertEqual(audit["viable_states"], 3)
        self.assertEqual(audit["legal_edges_from_viable_states"], 4)
        self.assertEqual(audit["violations"], [])

    def test_final_fit_does_not_add_terminal_to_infeasible_count(self):
        instance = EpochInstance(
            ((Segment(2, 2),), (Segment(2, 2),)), (1, 1)
        )
        self.assertTrue(instance.final_fits())
        audit = confluence_audit(instance)
        self.assertFalse(audit["initial_feasible"])
        self.assertEqual(audit["viable_states"], 0)
        self.assertEqual(audit["legal_edges_from_viable_states"], 0)
        self.assertEqual(audit["violations"], [])


class TraceIdentityTests(unittest.TestCase):
    @staticmethod
    def requests():
        # Two ten-row windows; repeated keys exercise dead-version retention.
        return tuple(Request(i, i, "set", 1, str(i % 4)) for i in range(20))

    def test_dataset_identity_is_required(self):
        with self.assertRaises(TypeError):
            make_trace_instances(self.requests(), window_rows=10)

    def test_both_datasets_have_unique_labels_without_numerical_changes(self):
        datasets = ("cloudphysics-prefix", "twitter-cluster015-prefix")
        records = {}
        labels = []
        for dataset in datasets:
            records[dataset] = make_trace_instances(
                self.requests(),
                window_rows=10,
                target_bytes=5,
                allocation_unit=1,
                page_bytes=4,
                commit_bytes=1,
                extra_slacks=(0, 4),
                dataset_id=dataset,
            )
            self.assertEqual(len(records[dataset]), 4)
            for record in records[dataset]:
                instance = record["instance"]
                expected = (
                    f"{dataset}-window-{record['window_index']}"
                    f"-extra-{record['extra_slack_units']}"
                )
                self.assertEqual(instance.label, expected)
                labels.append(instance.label)
        self.assertEqual(len(labels), 8)
        self.assertEqual(len(set(labels)), 8)
        for cloud, twitter in zip(records[datasets[0]], records[datasets[1]]):
            cloud_instance, twitter_instance = cloud["instance"], twitter["instance"]
            self.assertEqual(
                {**cloud, "instance": replace(cloud_instance, label="")},
                {**twitter, "instance": replace(twitter_instance, label="")},
            )
            cloud_solution = solve_normal_form(cloud_instance)
            twitter_solution = solve_normal_form(twitter_instance)
            self.assertTrue(cloud_solution.feasible)
            self.assertEqual(cloud_solution.as_dict(), twitter_solution.as_dict())
            self.assertEqual(
                replay(cloud_instance, cloud_solution.schedule),
                replay(twitter_instance, twitter_solution.schedule),
            )

    def test_retained_certificate_labels_match_both_dataset_ids(self):
        certificates = json.loads(
            (HERE / "results" / "frontier" / "trace-certificates.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(certificates), 8)
        self.assertEqual(
            {record["dataset"] for record in certificates},
            {"cloudphysics-prefix", "twitter-cluster015-prefix"},
        )
        labels = []
        for record in certificates:
            expected = (
                f"{record['dataset']}-window-{record['window']}"
                f"-extra-{record['extra_slack_units']}"
            )
            self.assertEqual(record["instance"]["label"], expected)
            labels.append(record["instance"]["label"])
        self.assertEqual(len(set(labels)), len(certificates))


if __name__ == "__main__":
    unittest.main()
