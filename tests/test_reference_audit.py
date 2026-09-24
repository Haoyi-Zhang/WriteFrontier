from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from validate_reference_audit import (  # noqa: E402
    REQUIRED_COLUMNS,
    load_audit,
    parse_bibtex,
)


class ReferenceAuditTests(unittest.TestCase):
    def test_standalone_inventory(self):
        audit = load_audit(ROOT / "reference-audit.csv")
        self.assertEqual(len(audit), 71)
        self.assertTrue(all(row["scholarly"] == "yes" for row in audit.values()))
        self.assertTrue(
            all(row["cited_in_manuscript"] == "yes" for row in audit.values())
        )

    def test_standalone_cli(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "validate_reference_audit.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("71 scholarly records", completed.stdout)

    def test_parser_handles_nested_braces(self):
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "sample.bib"
            sample.write_text(
                "@article{x, author={A. Author}, title={{Nested} Title}, "
                "journal={Venue}, year={2024}, doi={10.1/example}}\n",
                encoding="utf-8",
            )
            parsed = parse_bibtex(sample)
            self.assertEqual(parsed["x"].fields["title"], "{Nested} Title")

    def test_duplicate_locator_is_rejected(self):
        source = ROOT / "reference-audit.csv"
        with source.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        rows[1]["canonical_locator"] = rows[0]["canonical_locator"]
        with tempfile.TemporaryDirectory() as directory:
            altered = Path(directory) / "audit.csv"
            with altered.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "duplicate canonical locator"):
                load_audit(altered)


if __name__ == "__main__":
    unittest.main()
