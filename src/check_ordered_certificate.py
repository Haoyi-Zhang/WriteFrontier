"""Independent checker for ordered-prefix blocking certificates.

This module intentionally imports none of the project's model, replay, scan, or
optimization code.  It reconstructs the two-tier instance from primitive JSON,
replays the partial prefix schedule, and verifies that the reached nonterminal
state has no legal oldest-segment move.
"""
from __future__ import annotations


class InvalidOrderedCertificate(ValueError):
    pass


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidOrderedCertificate(message)


def _mapping(value: object, required: set[str], optional: set[str], context: str) -> dict:
    _need(type(value) is dict, f"{context} must be an object")
    assert isinstance(value, dict)
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    _need(not missing, f"{context} missing fields: {missing}")
    _need(not extra, f"{context} unknown fields: {extra}")
    return value


def _integer(value: object, context: str, minimum: int | None = None) -> int:
    _need(type(value) is int, f"{context} must be an integer")
    assert isinstance(value, int) and not isinstance(value, bool)
    if minimum is not None:
        _need(value >= minimum, f"{context} must be at least {minimum}")
    return value


def _pair(value: object, context: str, *, allow_none: bool = False) -> tuple:
    _need(type(value) in (list, tuple) and len(value) == 2, f"{context} must have two entries")
    assert isinstance(value, (list, tuple))
    result = []
    for index, item in enumerate(value):
        if allow_none and item is None:
            result.append(None)
        else:
            result.append(_integer(item, f"{context}[{index}]", 0))
    return tuple(result)


def _instance(payload: object) -> dict:
    data = _mapping(
        payload,
        {"tiers", "free", "quantum", "commit_bytes"},
        {"label"},
        "instance",
    )
    raw_tiers = data["tiers"]
    _need(type(raw_tiers) in (list, tuple) and len(raw_tiers) == 2,
          "instance.tiers must contain exactly two tiers")
    tiers: list[tuple[tuple[int, int], ...]] = []
    assert isinstance(raw_tiers, (list, tuple))
    for source, raw_tier in enumerate(raw_tiers):
        _need(type(raw_tier) in (list, tuple), f"instance.tiers[{source}] must be an array")
        assert isinstance(raw_tier, (list, tuple))
        tier: list[tuple[int, int]] = []
        for index, raw_segment in enumerate(raw_tier):
            segment = _mapping(
                raw_segment,
                {"occupied", "live"},
                {"birth", "name"},
                f"instance.tiers[{source}][{index}]",
            )
            occupied = _integer(
                segment["occupied"], f"instance.tiers[{source}][{index}].occupied", 1
            )
            live = _integer(segment["live"], f"instance.tiers[{source}][{index}].live", 0)
            _need(live <= occupied, f"instance.tiers[{source}][{index}] has live > occupied")
            if "birth" in segment:
                _integer(segment["birth"], f"instance.tiers[{source}][{index}].birth", 0)
            if "name" in segment:
                _need(type(segment["name"]) is str,
                      f"instance.tiers[{source}][{index}].name must be a string")
            tier.append((occupied, live))
        tiers.append(tuple(tier))
    free = _pair(data["free"], "instance.free")
    _integer(data["quantum"], "instance.quantum", 1)
    _integer(data["commit_bytes"], "instance.commit_bytes", 0)
    if "label" in data:
        _need(type(data["label"]) is str, "instance.label must be a string")
    return {"tiers": (tiers[0], tiers[1]), "free": free}


def check_ordered_certificate(certificate: object) -> dict:
    cert = _mapping(
        certificate,
        {"kind", "instance", "partial_schedule", "reached_state", "free", "next_live"},
        set(),
        "certificate",
    )
    _need(cert["kind"] == "ordered-prefix-block", "unknown certificate kind")
    instance = _instance(cert["instance"])
    tiers = instance["tiers"]
    initial_free = instance["free"]

    raw_schedule = cert["partial_schedule"]
    _need(type(raw_schedule) in (list, tuple), "partial_schedule must be an array")
    assert isinstance(raw_schedule, (list, tuple))
    indices = [0, 0]
    free = [initial_free[0], initial_free[1]]
    for epoch, raw_batch in enumerate(raw_schedule):
        batch = _mapping(raw_batch, {"source", "start", "end"}, set(), f"partial_schedule[{epoch}]")
        source = _integer(batch["source"], f"partial_schedule[{epoch}].source")
        _need(source in (0, 1), f"partial_schedule[{epoch}].source must be 0 or 1")
        start = _integer(batch["start"], f"partial_schedule[{epoch}].start", 0)
        end = _integer(batch["end"], f"partial_schedule[{epoch}].end", 0)
        _need(end > start, f"partial_schedule[{epoch}] must be nonempty")
        _need(start == indices[source], f"partial_schedule[{epoch}] is not the next source prefix")
        _need(end <= len(tiers[source]), f"partial_schedule[{epoch}] ends outside its tier")
        occupied = sum(item[0] for item in tiers[source][start:end])
        live = sum(item[1] for item in tiers[source][start:end])
        target = 1 - source
        _need(live <= free[target], f"partial_schedule[{epoch}] exceeds target free space")
        free[target] -= live
        free[source] += occupied
        indices[source] = end

    reached_state = _pair(cert["reached_state"], "reached_state")
    claimed_free = _pair(cert["free"], "free")
    claimed_next = _pair(cert["next_live"], "next_live", allow_none=True)
    _need(tuple(indices) == reached_state, "reached_state does not match replayed path")
    _need(tuple(free) == claimed_free, "free does not match replayed path")

    # Independently recompute the closed-form prefix identity as a second check.
    i, j = indices
    identity_free = (
        initial_free[0]
        + sum(item[0] for item in tiers[0][:i])
        - sum(item[1] for item in tiers[1][:j]),
        initial_free[1]
        + sum(item[0] for item in tiers[1][:j])
        - sum(item[1] for item in tiers[0][:i]),
    )
    _need(tuple(free) == identity_free, "incremental free disagrees with prefix identity")

    lengths = (len(tiers[0]), len(tiers[1]))
    _need(tuple(indices) != lengths, "terminal state cannot be a blocking certificate")
    actual_next = (
        None if i == lengths[0] else tiers[0][i][1],
        None if j == lengths[1] else tiers[1][j][1],
    )
    _need(claimed_next == actual_next, "next_live does not match the reached state")

    legal = []
    for source in (0, 1):
        next_live = actual_next[source]
        legal.append(next_live is not None and next_live <= free[1 - source])
    _need(not any(legal), "reached state has a legal next oldest segment")
    return {
        "valid": True,
        "kind": cert["kind"],
        "replayed_batches": len(raw_schedule),
        "reached_state": list(indices),
        "free": list(free),
        "exhausted_sources": [source for source in (0, 1) if indices[source] == lengths[source]],
    }
