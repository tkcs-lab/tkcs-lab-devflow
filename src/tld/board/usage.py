#!/usr/bin/env python3
"""Subscription usage readings for the board: settings, validation and the window view. No I/O, no command line.

    from tld.board import usage

`parse_plan(env)` reads TLD_BOARD_PLAN and TLD_BOARD_MAX_FACTOR. `validate(body, now)` checks the body of
`POST /api/usage` and returns the samples to store. `windows(rows, factor, now)` turns the stored raw samples
into the windows `GET /api/usage` shows; the plan and the factor are applied here, on read, never on write.
`utilization` is a fraction of the limit (0.26 is 26%). Python 3.11+, stdlib only.
"""
from __future__ import annotations

import math

KINDS = {"five_hour": 18000, "seven_day": 604800}  # window kind -> length in seconds
SOURCES = ("final", "scheduled")
MAX_BODY = 4096          # bytes of a POST /api/usage body
MAX_PER_WINDOW = 50      # samples kept per (kind, resets_at)
MAX_ROWS = 20000         # rows kept in all
RETENTION_DAYS = 120     # rows whose window ended longer ago are deleted
SLACK = 600              # seconds a window end may lie beyond now + the window length
MAX_UTILIZATION = 1.5
PLANS = ("standard", "max")
DEFAULT_FACTOR = 5.0
KEEP_WINDOWS = 60        # windows per kind in the view
IDLE_BELOW = 5.0         # peak in percent of Standard under which a window counts as idle

PLAN_ERROR = "TLD_BOARD_PLAN must be standard or max"
FACTOR_ERROR = "TLD_BOARD_MAX_FACTOR must be a number above 1 and at most 20"


def parse_plan(env) -> tuple[str | None, float]:
    """(plan, factor) from the environment. The plan is None when TLD_BOARD_PLAN is unset or empty; the factor
    is 5 when TLD_BOARD_MAX_FACTOR is unset or empty. Raises ValueError with the message the server prints."""
    plan = env.get("TLD_BOARD_PLAN") or None
    if plan is not None and plan not in PLANS:
        raise ValueError(PLAN_ERROR)
    text = env.get("TLD_BOARD_MAX_FACTOR")
    if not text:
        return plan, DEFAULT_FACTOR
    try:
        factor = float(text)
    except ValueError:
        raise ValueError(FACTOR_ERROR) from None
    if not 1 < factor <= 20:  # also false for nan
        raise ValueError(FACTOR_ERROR)
    return plan, factor


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(body: object, now: int) -> tuple[list[dict], str, list[str]]:
    """(samples, source, errors) of a POST /api/usage body. A sample is {"kind", "resets_at" (floored to the
    minute), "utilization"}. With errors the samples are empty."""
    if not isinstance(body, dict):
        return [], "", ["the body must be a JSON object"]
    errors: list[str] = []
    for key in body:
        if key not in KINDS and key != "source":
            errors.append(f"{key} is not allowed")
    source = body.get("source")
    if source not in SOURCES:
        errors.append("source must be one of " + ", ".join(SOURCES))
    samples: list[dict] = []
    present = [kind for kind in KINDS if kind in body]
    if not present and not errors:
        errors.append("at least one of " + ", ".join(KINDS) + " is required")
    for kind in present:
        window = body[kind]
        if not isinstance(window, dict):
            errors.append(f"{kind} must be an object")
            continue
        bad = False
        for key in window:
            if key not in ("utilization", "resets_at"):
                errors.append(f"{kind}.{key} is not allowed")
                bad = True
        utilization, resets_at = window.get("utilization"), window.get("resets_at")
        if not _number(utilization) or not 0 <= utilization <= MAX_UTILIZATION:
            errors.append(f"{kind}.utilization must be a number from 0 to {MAX_UTILIZATION}")
            bad = True
        latest = now + KINDS[kind] + SLACK
        if isinstance(resets_at, bool) or not isinstance(resets_at, int) or not now < resets_at <= latest:
            errors.append(f"{kind}.resets_at must be an integer after now and at most {KINDS[kind] + SLACK} "
                          "seconds from now")
            bad = True
        if not bad:
            samples.append({"kind": kind, "resets_at": resets_at // 60 * 60, "utilization": float(utilization)})
    if errors:
        return [], source if source in SOURCES else "", errors
    return samples, source, []


def _standard(utilization: float, plan: str, factor: float) -> float:
    """Percent of the Standard limit of one stored sample (the factor of the time it was taken)."""
    return round(utilization * 100 * (factor if plan == "max" else 1), 6)


def _window(kind: str, resets_at: int, rows: list[tuple], factor: float, now: int) -> dict:
    rows = sorted(rows, key=lambda row: row[2])  # by observed_at
    standard = [_standard(row[3], row[4], row[5]) for row in rows]
    peak = max(standard)
    over = peak > 100
    blocked = None
    if over:
        first = next(row[2] for row, pct in zip(rows, standard) if pct > 100)
        blocked = round((resets_at - first) / 3600, 1)
    return {
        "resets_at": resets_at, "start": resets_at - KINDS[kind], "samples": len(rows),
        "first_seen": rows[0][2], "last_seen": rows[-1][2], "plan": rows[-1][4],
        "peak_standard": round(peak, 1), "last_standard": round(standard[-1], 1),
        "peak_max": round(peak / factor, 1), "over": over, "blocked_hours": blocked,
        "idle": peak < IDLE_BELOW, "complete": resets_at <= now,
        "sources": sorted({row[6] for row in rows}),
    }


def windows(rows, factor: float, now: int) -> dict[str, list[dict]]:
    """The windows of each kind from stored rows (kind, resets_at, observed_at, utilization, plan, factor,
    source): oldest first, the newest KEEP_WINDOWS of each kind."""
    groups: dict[str, dict[int, list[tuple]]] = {kind: {} for kind in KINDS}
    for row in rows:
        if row[0] in groups:
            groups[row[0]].setdefault(row[1], []).append(tuple(row))
    return {kind: [_window(kind, resets_at, group[resets_at], factor, now) for resets_at in sorted(group)[-KEEP_WINDOWS:]]
            for kind, group in groups.items()}
