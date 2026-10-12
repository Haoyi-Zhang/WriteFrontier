"""Bounded runner write scope and precise supplemental metric schema."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import run_coalesced_portfolio as runner


class CoalescedRunnerTests(unittest.TestCase):
    def test_output_cannot_replace_original_results_or_paper(self):
        for relative in ("results/frontier", "results/policy-frontier",
                         "results/unordered-boundary", "src/coalesced-portfolio",
                         "../paper/coalesced-portfolio"):
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                runner.output_directory(HERE / relative)
        self.assertEqual(runner.output_directory(HERE / "results/coalesced-portfolio"),
                         (HERE / "results/coalesced-portfolio").resolve())

    def test_new_schema_conditions_epoch_count_without_renaming_old_files(self):
        self.assertIn("min_epochs_at_opt_cost", runner.FIELDS)
        self.assertIn("global_min_epochs", runner.FIELDS)
        self.assertNotIn("opt_epochs", runner.FIELDS)
        self.assertEqual(sum(runner.DOMAIN_COUNTS.values()), 7496)
        self.assertEqual(len(runner.RAW_NAMES), 7)

    def test_table_is_generated_from_supplied_values(self):
        records = []
        for domain, n in runner.DOMAIN_COUNTS.items():
            records.extend([
                {"domain": domain, "policy": "two-start-maximum-prefix", "optimal_cases": 1},
                {"domain": domain, "policy": "coalesced-portfolio", "optimal_cases": 2,
                 "cases": n, "p95": 1.25, "max": 1.5},
            ])
        rendered = runner.render_table({"policies": records})
        self.assertIn("2 / 768 & 1.250 & 1.500", rendered)
        self.assertIn("\\begin{tabular}", rendered)
        self.assertTrue(rendered.endswith("\\end{tabular}\n"))

    def test_lossless_reader_covers_all_retained_inputs_rows_and_residuals(self):
        cases, rows, witnesses, summary = runner.read_outputs(HERE / "results/coalesced-portfolio")
        self.assertEqual((len(cases), len(rows), len(witnesses)), (7496, 52472, 277))
        self.assertEqual(summary["epoch_metrics"]["costed_cases_where_metrics_differ"],
                         {"retained-frontier": 0, "public-excerpt": 0,
                          "length-3-12": 61, "length-16-32": 139})


if __name__ == "__main__":
    unittest.main()
