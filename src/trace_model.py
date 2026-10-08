"""Deterministic conversion from a public block-request excerpt to episodes."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from epoch_model import EpochInstance, Segment
from epoch_dp import final_fit_free_lower_bound, find_min_common_slack


@dataclass(frozen=True, slots=True)
class Request:
    ordinal: int
    timestamp: int
    operation: str
    size_bytes: int
    object_id: str


@dataclass(frozen=True, slots=True)
class RawSegment:
    birth: int
    records: tuple[Request, ...]
    occupied_bytes: int
    live_bytes: int
    retained_allocation_bytes: int


def read_cloudphysics(path: str | Path, limit: int | None = None) -> list[Request]:
    rows: list[Request] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"version", "time", "op", "size", "lbn"}
        if set(reader.fieldnames or ()) != required:
            raise ValueError(f"unexpected trace header: {reader.fieldnames}")
        for ordinal, row in enumerate(reader):
            size = int(row["size"])
            if size <= 0:
                raise ValueError("request sizes must be positive")
            rows.append(
                Request(
                    ordinal=ordinal,
                    timestamp=int(row["time"]),
                    operation=row["op"],
                    size_bytes=size,
                    object_id=row["lbn"],
                )
            )
            if limit is not None and len(rows) >= limit:
                break
    if not rows:
        raise ValueError("trace excerpt is empty")
    return rows



def read_twitter(path: str | Path, limit: int | None = None) -> list[Request]:
    """Read the official Twitter cache-trace CSV format.

    Only mutating operations are converted into log records.  The retained
    size is key_size + value_size; reads are excluded rather than reclassified
    as writes.
    """
    writes = {"set", "add", "replace", "cas", "append", "prepend", "incr", "decr"}
    rows: list[Request] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        expected = ["time", "key", "key_size", "value_size", "client_id", "operation", "ttl"]
        if list(reader.fieldnames or ()) != expected:
            raise ValueError(f"unexpected Twitter trace header: {reader.fieldnames}")
        for source_ordinal, row in enumerate(reader):
            operation = row["operation"].lower()
            if operation not in writes:
                continue
            size = int(row["key_size"]) + int(row["value_size"])
            if size <= 0:
                raise ValueError("Twitter write sizes must be positive")
            rows.append(
                Request(
                    ordinal=len(rows),
                    timestamp=int(row["time"]),
                    operation=operation,
                    size_bytes=size,
                    object_id=row["key"],
                )
            )
            if limit is not None and len(rows) >= limit:
                break
    if not rows:
        raise ValueError("Twitter trace excerpt contains no mutating requests")
    return rows

def _seal_segments(requests: Sequence[Request], target_bytes: int) -> list[list[Request]]:
    if target_bytes <= 0:
        raise ValueError("target_bytes must be positive")
    segments: list[list[Request]] = []
    current: list[Request] = []
    current_bytes = 0
    for request in requests:
        if current and current_bytes + request.size_bytes > target_bytes:
            segments.append(current)
            current = []
            current_bytes = 0
        current.append(request)
        current_bytes += request.size_bytes
        if current_bytes >= target_bytes:
            segments.append(current)
            current = []
            current_bytes = 0
    if current:
        segments.append(current)
    return segments


def segment_window(
    requests: Sequence[Request],
    target_bytes: int = 131_072,
    allocation_unit: int = 512,
) -> tuple[tuple[Segment, ...], tuple[Segment, ...], list[RawSegment]]:
    """Seal a write/update stream and retain only each object's latest version.

    Every input record is treated as an update to object ``lbn``.  This is a
    controlled version-retention transformation; it is not a reconstruction of
    the original cache's admission, read/write, or hit semantics.
    """
    if allocation_unit <= 0:
        raise ValueError("allocation_unit must be positive")
    groups = _seal_segments(requests, target_bytes)
    latest: dict[str, int] = {}
    for request in requests:
        latest[request.object_id] = request.ordinal
    tiers: list[list[Segment]] = [[], []]
    raw: list[RawSegment] = []
    for birth, records in enumerate(groups):
        occupied_bytes = sum(r.size_bytes for r in records)
        live_bytes = sum(
            r.size_bytes for r in records if latest[r.object_id] == r.ordinal
        )
        occupied_units = (occupied_bytes + allocation_unit - 1) // allocation_unit
        live_units = (live_bytes + allocation_unit - 1) // allocation_unit if live_bytes else 0
        raw.append(
            RawSegment(
                birth=birth,
                records=tuple(records),
                occupied_bytes=occupied_bytes,
                live_bytes=live_bytes,
                retained_allocation_bytes=live_units * allocation_unit,
            )
        )
        source = birth % 2
        tiers[source].append(
            Segment(
                occupied_units,
                live_units,
                birth=birth,
                name=f"seg-{birth:03d}",
            )
        )
    return tuple(tiers[0]), tuple(tiers[1]), raw


def make_trace_instances(
    requests: Sequence[Request],
    window_rows: int = 100,
    target_bytes: int = 131_072,
    allocation_unit: int = 512,
    page_bytes: int = 4096,
    commit_bytes: int = 512,
    extra_slacks: Iterable[int] = (0, 8),
    *,
    dataset_id: str,
) -> list[dict]:
    """Build episodes labeled by dataset identity, window, and extra slack."""
    if window_rows <= 0:
        raise ValueError("window_rows must be positive")
    if page_bytes % allocation_unit or commit_bytes % allocation_unit:
        raise ValueError("page and commit sizes must be multiples of allocation_unit")
    quantum = page_bytes // allocation_unit
    commit_units = commit_bytes // allocation_unit
    records: list[dict] = []
    for window_index, start in enumerate(range(0, len(requests), window_rows)):
        window = requests[start : start + window_rows]
        if len(window) < max(10, window_rows // 2):
            break
        tiers0, tiers1, raw = segment_window(window, target_bytes, allocation_unit)
        final_fit_free = final_fit_free_lower_bound((tiers0, tiers1))
        slack, base_instance, base_solution = find_min_common_slack(
            (tiers0, tiers1), quantum=quantum, commit_bytes=commit_units
        )
        for extra in extra_slacks:
            instance = EpochInstance(
                (tiers0, tiers1),
                (base_instance.free[0] + extra, base_instance.free[1] + extra),
                quantum,
                commit_units,
                label=f"{dataset_id}-window-{window_index}-extra-{extra}",
            )
            records.append(
                {
                    "window_index": window_index,
                    "row_start": start,
                    "row_end": start + len(window),
                    "rows": len(window),
                    "unique_objects": len({r.object_id for r in window}),
                    "segments": len(raw),
                    "tier0_segments": len(tiers0),
                    "tier1_segments": len(tiers1),
                    "occupied_bytes": sum(r.occupied_bytes for r in raw),
                    "raw_live_bytes": sum(r.live_bytes for r in raw),
                    "retained_allocation_bytes": sum(
                        r.retained_allocation_bytes for r in raw
                    ),
                    "final_fit_free0_units": final_fit_free[0],
                    "final_fit_free1_units": final_fit_free[1],
                    "minimum_common_slack_units": slack,
                    "extra_slack_units": extra,
                    "instance": instance,
                }
            )
    if not records:
        raise ValueError("no complete trace window was formed")
    return records
