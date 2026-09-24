#!/usr/bin/env python3
"""Validate the project-specific scholarly-reference audit.

The default mode validates the retained audit inventory without requiring the
paper tree.  Supplying --bib and --tex additionally checks that the audit,
BibTeX database, and manuscript citation closure agree exactly.

This is a structural and provenance check.  It does not replace reading the
papers or an independent literature review.
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

EXPECTED_COUNT = 71
CHECKED_DATE = "2026-09-16"
REQUIRED_COLUMNS = (
    "key",
    "entry_type",
    "year",
    "title",
    "venue",
    "canonical_locator",
    "locator_type",
    "scholarly",
    "cited_in_manuscript",
    "verification_basis",
    "checked_date",
    "notes",
)
ALLOWED_ENTRY_TYPES = {"article", "inproceedings", "book"}
ALLOWED_LOCATOR_TYPES = {"doi", "official_url", "isbn"}
ALLOWED_BASES = {
    "doi_and_publisher_record_rechecked",
    "official_scholarly_page_rechecked",
    "official_prepublication_page_rechecked",
    "publisher_book_record_rechecked",
}


@dataclass(frozen=True)
class BibEntry:
    entry_type: str
    key: str
    fields: dict[str, str]


def squash(value: str) -> str:
    return " ".join(value.split())


def split_entries(text: str) -> list[tuple[str, str]]:
    """Return (entry_type, body) pairs using brace-balanced parsing."""
    entries: list[tuple[str, str]] = []
    pos = 0
    while True:
        match = re.search(r"@([A-Za-z]+)\s*\{", text[pos:])
        if match is None:
            break
        entry_type = match.group(1).lower()
        open_pos = pos + match.end() - 1
        depth = 0
        quote = False
        escaped = False
        close_pos: int | None = None
        for index in range(open_pos, len(text)):
            char = text[index]
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                quote = not quote
                continue
            if quote:
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    close_pos = index
                    break
        if close_pos is None:
            raise ValueError(f"unterminated BibTeX entry starting at byte {open_pos}")
        entries.append((entry_type, text[open_pos + 1 : close_pos]))
        pos = close_pos + 1
    return entries


def parse_value(body: str, pos: int) -> tuple[str, int]:
    while pos < len(body) and body[pos].isspace():
        pos += 1
    if pos >= len(body):
        raise ValueError("missing BibTeX field value")
    opener = body[pos]
    if opener == "{":
        depth = 1
        start = pos + 1
        pos += 1
        escaped = False
        while pos < len(body):
            char = body[pos]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return body[start:pos], pos + 1
            pos += 1
        raise ValueError("unterminated braced BibTeX value")
    if opener == '"':
        start = pos + 1
        pos += 1
        escaped = False
        while pos < len(body):
            char = body[pos]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                return body[start:pos], pos + 1
            pos += 1
        raise ValueError("unterminated quoted BibTeX value")
    start = pos
    while pos < len(body) and body[pos] not in ",\n\r":
        pos += 1
    return body[start:pos].strip(), pos


def parse_bibtex(path: Path) -> dict[str, BibEntry]:
    parsed: dict[str, BibEntry] = {}
    for entry_type, body in split_entries(path.read_text(encoding="utf-8")):
        comma = body.find(",")
        if comma < 1:
            raise ValueError("BibTeX entry has no key/field separator")
        key = body[:comma].strip()
        if key in parsed:
            raise ValueError(f"duplicate BibTeX key: {key}")
        fields: dict[str, str] = {}
        pos = comma + 1
        while pos < len(body):
            while pos < len(body) and (body[pos].isspace() or body[pos] == ","):
                pos += 1
            if pos >= len(body):
                break
            match = re.match(r"([A-Za-z][A-Za-z0-9_-]*)\s*=", body[pos:])
            if match is None:
                excerpt = squash(body[pos : pos + 60])
                raise ValueError(f"cannot parse BibTeX field in {key}: {excerpt}")
            name = match.group(1).lower()
            pos += match.end()
            value, pos = parse_value(body, pos)
            if name in fields:
                raise ValueError(f"duplicate BibTeX field {name} in {key}")
            fields[name] = squash(value)
        parsed[key] = BibEntry(entry_type, key, fields)
    return parsed


def canonical_locator(entry: BibEntry) -> tuple[str, str]:
    fields = entry.fields
    present = [name for name in ("doi", "url", "isbn") if fields.get(name)]
    if len(present) != 1:
        raise ValueError(
            f"{entry.key}: expected exactly one of doi/url/isbn, found {present}"
        )
    kind = present[0]
    if kind == "doi":
        locator = fields[kind].strip()
        locator = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", locator, flags=re.I)
        return "doi", f"https://doi.org/{locator}"
    if kind == "isbn":
        return "isbn", f"isbn:{fields[kind].strip()}"
    return "official_url", fields[kind].strip().rstrip("/")


def venue(entry: BibEntry) -> str:
    return squash(
        entry.fields.get("journal")
        or entry.fields.get("booktitle")
        or entry.fields.get("publisher")
        or ""
    )


def citation_keys(paths: Iterable[Path]) -> set[str]:
    keys: set[str] = set()
    pattern = re.compile(r"\\cite[A-Za-z*]*\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}")
    for path in paths:
        text = re.sub(r"(?<!\\)%.*", "", path.read_text(encoding="utf-8"))
        for group in pattern.findall(text):
            keys.update(item.strip() for item in group.split(",") if item.strip())
    return keys


def load_audit(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError(
                f"audit columns differ: expected {REQUIRED_COLUMNS}, got {reader.fieldnames}"
            )
        rows = list(reader)
    if len(rows) != EXPECTED_COUNT:
        raise ValueError(f"expected {EXPECTED_COUNT} audit rows, found {len(rows)}")
    by_key: dict[str, dict[str, str]] = {}
    locators: set[str] = set()
    normalized_titles: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        key = row["key"].strip()
        if not key or key in by_key:
            raise ValueError(f"row {row_number}: blank or duplicate key {key!r}")
        entry_type = row["entry_type"].strip().lower()
        if entry_type not in ALLOWED_ENTRY_TYPES:
            raise ValueError(f"{key}: unsupported entry type {entry_type}")
        try:
            year = int(row["year"])
        except ValueError as exc:
            raise ValueError(f"{key}: nonnumeric year") from exc
        if not 1966 <= year <= 2027:
            raise ValueError(f"{key}: implausible year {year}")
        if not row["title"].strip() or not row["venue"].strip():
            raise ValueError(f"{key}: blank title or venue")
        title_token = re.sub(r"[{}\\\s]", "", row["title"]).casefold()
        if title_token in normalized_titles:
            raise ValueError(f"{key}: duplicate normalized title")
        normalized_titles.add(title_token)
        locator = row["canonical_locator"].strip().rstrip("/")
        locator_type = row["locator_type"].strip()
        if locator_type not in ALLOWED_LOCATOR_TYPES:
            raise ValueError(f"{key}: unsupported locator type {locator_type}")
        if locator_type == "doi" and not locator.startswith("https://doi.org/10."):
            raise ValueError(f"{key}: malformed DOI locator")
        if locator_type == "official_url" and not locator.startswith("https://"):
            raise ValueError(f"{key}: official URL must use HTTPS")
        if locator_type == "isbn" and not locator.startswith("isbn:"):
            raise ValueError(f"{key}: malformed ISBN locator")
        if "github.com" in locator.casefold():
            raise ValueError(f"{key}: repository URL is not a scholarly locator")
        if locator in locators:
            raise ValueError(f"{key}: duplicate canonical locator {locator}")
        locators.add(locator)
        if row["scholarly"].strip().lower() != "yes":
            raise ValueError(f"{key}: audit contains a nonscholarly bibliography item")
        if row["cited_in_manuscript"].strip().lower() != "yes":
            raise ValueError(f"{key}: audit contains an uncited bibliography item")
        if row["verification_basis"].strip() not in ALLOWED_BASES:
            raise ValueError(f"{key}: unsupported verification basis")
        if row["checked_date"].strip() != CHECKED_DATE:
            raise ValueError(f"{key}: stale or unexpected checked date")
        by_key[key] = {name: value.strip() for name, value in row.items()}
    return by_key


def compare_with_manuscript(
    audit: dict[str, dict[str, str]], bib_path: Path, tex_paths: list[Path]
) -> None:
    bib = parse_bibtex(bib_path)
    if len(bib) != EXPECTED_COUNT:
        raise ValueError(f"expected {EXPECTED_COUNT} BibTeX records, found {len(bib)}")
    if set(audit) != set(bib):
        raise ValueError(
            f"audit/BibTeX key mismatch: audit-only={sorted(set(audit)-set(bib))}, "
            f"bib-only={sorted(set(bib)-set(audit))}"
        )
    cited = citation_keys(tex_paths)
    if cited != set(bib):
        raise ValueError(
            f"citation closure mismatch: uncited={sorted(set(bib)-cited)}, "
            f"unknown={sorted(cited-set(bib))}"
        )
    seen_titles: set[str] = set()
    for key, entry in bib.items():
        if entry.entry_type not in ALLOWED_ENTRY_TYPES:
            raise ValueError(f"{key}: nonscholarly or unsupported BibTeX type")
        for required in ("author", "title", "year"):
            if not entry.fields.get(required):
                raise ValueError(f"{key}: missing required BibTeX field {required}")
        title_token = re.sub(r"[{}\\\s]", "", entry.fields["title"]).casefold()
        if title_token in seen_titles:
            raise ValueError(f"{key}: duplicate normalized BibTeX title")
        seen_titles.add(title_token)
        locator_type, locator = canonical_locator(entry)
        row = audit[key]
        expected = {
            "entry_type": entry.entry_type,
            "year": entry.fields["year"],
            "title": entry.fields["title"],
            "venue": venue(entry),
            "canonical_locator": locator,
            "locator_type": locator_type,
        }
        for field, value in expected.items():
            if squash(row[field]).rstrip("/") != squash(value).rstrip("/"):
                raise ValueError(
                    f"{key}: audit/BibTeX {field} mismatch: "
                    f"{row[field]!r} != {value!r}"
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path(__file__).resolve().with_name("reference-audit.csv"),
    )
    parser.add_argument("--bib", type=Path)
    parser.add_argument("--tex", type=Path, nargs="*")
    args = parser.parse_args()
    audit = load_audit(args.audit)
    if (args.bib is None) != (not args.tex):
        raise SystemExit("--bib and at least one --tex path must be supplied together")
    if args.bib is not None:
        compare_with_manuscript(audit, args.bib, args.tex)
    print(
        f"reference audit valid: {len(audit)} scholarly records; "
        f"manuscript closure={'checked' if args.bib else 'not requested'}"
    )


if __name__ == "__main__":
    main()
