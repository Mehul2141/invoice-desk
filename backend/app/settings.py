"""Matching rules and approval policy, editable from the UI and stored in the database.

Each run snapshots the settings it was evaluated under, so a decision can always be
explained against the rules that were in force at the time.
"""
import json

from . import db

DEFAULTS = {
    # Approval policy
    "approval_mode": "autonomous",      # autonomous | hitl
    "auto_approve_limit": 25000.0,      # autonomous mode: invoices above this total need a human (0 = no limit)
    # 2-way match: invoice vs PO
    "price_tolerance_pct": 2.0,         # unit price may exceed the PO price by this much
    "quantity_tolerance_pct": 0.0,      # cumulative billed quantity may exceed the ordered quantity by this much
    "amount_tolerance_pct": 2.0,        # cumulative billed amount may exceed the PO total by this %...
    "amount_tolerance_abs": 500.0,      # ...and by no more than this many dollars (whichever is lower)
    # 3-way match: invoice vs goods receipt
    "three_way_match": True,
    "receipt_tolerance_pct": 0.0,       # billed quantity may exceed the received quantity by this much
    # Other controls
    "duplicate_window_days": 10,
    "min_confidence_pct": 70,
}

LIMITS = {
    "auto_approve_limit": (0, 10_000_000),
    "price_tolerance_pct": (0, 100),
    "quantity_tolerance_pct": (0, 100),
    "amount_tolerance_pct": (0, 100),
    "amount_tolerance_abs": (0, 10_000_000),
    "receipt_tolerance_pct": (0, 100),
    "duplicate_window_days": (0, 365),
    "min_confidence_pct": (0, 100),
}


def get():
    stored = {r["key"]: json.loads(r["value"]) for r in db.query("SELECT key, value FROM settings")}
    return {k: stored.get(k, v) for k, v in DEFAULTS.items()}


def validate(changes):
    clean = {}
    for k, v in changes.items():
        if k not in DEFAULTS:
            raise ValueError(f"Unknown setting '{k}'")
        if k == "approval_mode":
            if v not in ("autonomous", "hitl"):
                raise ValueError("approval_mode must be 'autonomous' or 'hitl'")
        elif k == "three_way_match":
            v = bool(v)
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{k} must be a number")
            lo, hi = LIMITS[k]
            if not lo <= v <= hi:
                raise ValueError(f"{k} must be between {lo} and {hi}")
            if isinstance(DEFAULTS[k], int):
                v = int(v)
        clean[k] = v
    return clean


def update(changes):
    clean = validate(changes)
    for k, v in clean.items():
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v)))
    return get()


def restore_defaults():
    db.execute("DELETE FROM settings")
    return get()
