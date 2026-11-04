"""SQLite persistence: invoices (runs), stage logs, audit events, ledger, inbox and settings."""
import csv
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATA_DIR, DB_PATH

SCHEMA_VERSION = "3"

_lock = threading.RLock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source TEXT NOT NULL,              -- email | upload
    source_ref TEXT,                   -- inbox message id
    sender_email TEXT,
    extraction_mode TEXT,              -- anthropic | gemini | mock
    status TEXT NOT NULL,              -- see STATUSES in pipeline.py
    decision TEXT,                     -- system recommendation: APPROVE | HOLD | REJECT
    approved_by TEXT,                  -- system | reviewer
    vendor_id TEXT,
    vendor_name TEXT,
    invoice_number TEXT,
    invoice_date TEXT,
    due_date TEXT,
    total REAL,
    currency TEXT,
    po_number TEXT,
    headline TEXT,
    result_json TEXT,
    rules_json TEXT,                   -- matching rules in force for this run
    duration_ms INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    error TEXT,
    error_detail TEXT
);
CREATE TABLE IF NOT EXISTS stages (
    run_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,              -- pending | running | waiting | pass | warn | fail | skipped | error
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER,
    summary TEXT,
    detail_json TEXT,
    PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    at TEXT NOT NULL,
    status TEXT,
    actor TEXT NOT NULL,               -- system | reviewer | user
    note TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    vendor_id TEXT NOT NULL,
    invoice_number TEXT,
    invoice_number_norm TEXT,
    invoice_date TEXT,
    po_number TEXT,
    net_amount REAL,
    tax_amount REAL,
    total REAL,
    currency TEXT,
    status TEXT NOT NULL,              -- paid | approved | pending_approval | needs_review | rejected
    paid_on TEXT,
    lines_json TEXT,                   -- [{"sku":..., "quantity":..., "net_amount":...}]
    file_hash TEXT,
    source TEXT NOT NULL,              -- history | run
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    from_name TEXT,
    from_email TEXT,
    subject TEXT,
    body TEXT,
    attachment TEXT,
    sample_file TEXT,
    run_id INTEGER
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def execute(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur


def query(sql, params=()):
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def normalize_invoice_number(num) -> str:
    """'INV-CN-0042', 'CN-42' and 'cn 42' all normalise to '42'."""
    if not num:
        return ""
    digits = "".join(ch for ch in str(num) if ch.isdigit()).lstrip("0")
    if digits:
        return digits
    return "".join(ch for ch in str(num).upper() if ch.isalnum())


def seed_history():
    with open(DATA_DIR / "invoice_history.csv") as f:
        for row in csv.DictReader(f):
            lines = []
            for part in filter(None, row["lines"].split("|")):
                sku, qty = part.split(":")
                lines.append({"sku": sku, "quantity": float(qty)})
            execute(
                """INSERT INTO ledger (vendor_id, invoice_number, invoice_number_norm, invoice_date, po_number,
                   net_amount, tax_amount, total, currency, status, paid_on, lines_json, source, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["vendor_id"], row["invoice_number"], normalize_invoice_number(row["invoice_number"]),
                 row["invoice_date"], row["po_number"], float(row["net_amount"]), float(row["tax_amount"]),
                 float(row["total"]), row["currency"], row["status"], row["paid_on"] or None,
                 json.dumps(lines), "history", now_iso()),
            )


def seed_inbox():
    for m in json.loads((DATA_DIR / "inbox.json").read_text()):
        execute("""INSERT INTO inbox (id, received_at, from_name, from_email, subject, body, attachment, sample_file)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (m["id"], m["received_at"], m["from_name"], m["from_email"], m["subject"], m["body"],
                 m["attachment"], m["sample_file"]))


def init_db():
    with _lock:
        _conn.executescript("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);")
        row = _conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not row or row[0] != SCHEMA_VERSION:
            # Demo app: on schema change start from a clean slate.
            _conn.executescript("""DROP TABLE IF EXISTS runs; DROP TABLE IF EXISTS stages; DROP TABLE IF EXISTS ledger;
                                   DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS inbox;""")
        _conn.executescript(SCHEMA)
        _conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        _conn.commit()
    if not query_one("SELECT 1 AS x FROM ledger LIMIT 1"):
        seed_history()
    if not query_one("SELECT 1 AS x FROM inbox LIMIT 1"):
        seed_inbox()


def reset_db():
    """Clear invoices, ledger and inbox back to the seeded state. Settings are kept."""
    with _lock:
        _conn.executescript("""DROP TABLE IF EXISTS runs; DROP TABLE IF EXISTS stages; DROP TABLE IF EXISTS ledger;
                               DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS inbox;""")
        _conn.commit()
    init_db()
