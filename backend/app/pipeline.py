"""The invoice pipeline: nine stages from PDF to decision, plus the invoice lifecycle around it.

The LLM only transcribes the document (stage 3) and writes the explanation (stage 9).
Every check and the decision itself are deterministic code in this file, evaluated
against the matching rules configured in Settings (snapshotted per run).

Invoice lifecycle (runs.status):
    queued → processing → approved | pending_approval | needs_review | rejected
                        ↘ waiting_retry → (auto) queued          ↘ failed
    pending_approval / needs_review → approved | rejected   (human)
    approved → paid                                           (payment run)
"""
import hashlib
import json
import logging
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from rapidfuzz import fuzz

from . import db, extract, refdata, settings
from .config import STAGE_MIN_MS, TODAY, llm_enabled, provider

log = logging.getLogger("pipeline")

STAGES = [
    ("ingest", "Ingest"),
    ("read", "Read document"),
    ("extract", "Extract fields"),
    ("validate", "Validate invoice"),
    ("vendor", "Match vendor"),
    ("po", "Match purchase order"),
    ("receipt", "Match goods receipt"),
    ("rules", "Business rules"),
    ("decision", "Decision"),
]

STATUSES = {
    "queued": "Queued",
    "processing": "Processing",
    "waiting_retry": "Waiting for AI",
    "failed": "Failed",
    "needs_review": "Needs review",
    "pending_approval": "Pending approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "paid": "Paid",
}
ACTIVE_STATUSES = ("queued", "processing", "waiting_retry")
LEDGER_STATUSES = ("needs_review", "pending_approval", "approved", "rejected", "paid")

MAX_ATTEMPTS = 4
RETRY_DELAYS_S = [20, 45, 90]

SEVERITY_RANK = {"critical": 3, "high": 2, "low": 1, "none": 0}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def digits(s):
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def mask(acct):
    d = digits(acct)
    return f"••••{d[-4:]}" if d else "—"


def close(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def parse_date(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def similarity(a, b):
    a, b = (a or "").lower(), (b or "").lower()
    return (fuzz.token_set_ratio(a, b) + fuzz.token_sort_ratio(a, b)) / 200


def pct(v):
    return f"{v:g}%"


def check(id, label, status, message, severity="none", category=None, action=None, **evidence):
    return {"id": id, "label": label, "status": status, "severity": severity, "message": message,
            "category": category, "action": action, "evidence": evidence}


def stage_status(checks):
    if any(c["status"] == "fail" for c in checks):
        return "fail"
    if any(c["status"] == "warn" for c in checks):
        return "warn"
    return "pass"


# ---------------------------------------------------------------------------
# lifecycle bookkeeping
# ---------------------------------------------------------------------------

def set_status(run_id, status, actor, note=None):
    db.execute("UPDATE runs SET status=?, updated_at=? WHERE id=?", (status, db.now_iso(), run_id))
    db.execute("INSERT INTO events (run_id, at, status, actor, note) VALUES (?,?,?,?,?)",
               (run_id, db.now_iso(), status, actor, note))
    if status in LEDGER_STATUSES:
        paid_on = TODAY if status == "paid" else None
        db.execute("UPDATE ledger SET status=?, paid_on=COALESCE(?, paid_on) WHERE run_id=?", (status, paid_on, run_id))


def log_event(run_id, actor, note):
    db.execute("INSERT INTO events (run_id, at, status, actor, note) VALUES (?,?,?,?,?)",
               (run_id, db.now_iso(), None, actor, note))


def create_run(filename, file_path, source, source_ref=None, sender_email=None):
    data = Path(file_path).read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()
    now = db.now_iso()
    cur = db.execute(
        """INSERT INTO runs (created_at, updated_at, filename, file_path, file_hash, source, source_ref, sender_email,
                             status) VALUES (?,?,?,?,?,?,?,?,?)""",
        (now, now, filename, str(file_path), file_hash, source, source_ref, sender_email, "queued"),
    )
    run_id = cur.lastrowid
    for i, (key, name) in enumerate(STAGES):
        db.execute("INSERT INTO stages (run_id, idx, key, name, status) VALUES (?,?,?,?,?)",
                   (run_id, i, key, name, "pending"))
    how = f"Received by email from {sender_email}" if source == "email" else "Uploaded manually"
    db.execute("INSERT INTO events (run_id, at, status, actor, note) VALUES (?,?,?,?,?)",
               (run_id, now, "queued", "system", f"{how}: {filename}. Queued for processing."))
    return run_id


def reprocess(run_id, actor="user", note=None):
    """Re-run an invoice from scratch under the current matching rules."""
    run = db.query_one("SELECT status FROM runs WHERE id=?", (run_id,))
    if not run:
        raise LookupError("Invoice not found")
    if run["status"] not in ("failed", "waiting_retry", "needs_review", "pending_approval", "rejected"):
        raise ValueError(f"An invoice that is {STATUSES[run['status']].lower()} cannot be re-processed.")
    db.execute("DELETE FROM ledger WHERE run_id=?", (run_id,))
    db.execute("""UPDATE runs SET attempts=0, next_retry_at=NULL, error=NULL, error_detail=NULL, decision=NULL,
                  approved_by=NULL, result_json=NULL, headline=NULL WHERE id=?""", (run_id,))
    set_status(run_id, "queued", actor, note or "Re-processing requested with the current matching rules.")


def human_action(run_id, action, note):
    run = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        raise LookupError("Invoice not found")
    s, note = run["status"], (note or "").strip()
    if action == "approve":
        if s not in ("needs_review", "pending_approval"):
            raise ValueError(f"Only invoices needing review or pending approval can be approved (this one is {STATUSES[s].lower()}).")
        if s == "needs_review" and not note:
            raise ValueError("Approving an exception overrides the controls — a note explaining why is required.")
        db.execute("UPDATE runs SET approved_by='reviewer' WHERE id=?", (run_id,))
        set_status(run_id, "approved", "reviewer", note or "Approved by reviewer.")
    elif action == "reject":
        if s not in ("needs_review", "pending_approval"):
            raise ValueError(f"Only invoices needing review or pending approval can be rejected (this one is {STATUSES[s].lower()}).")
        if not note:
            raise ValueError("A note is required to reject an invoice.")
        set_status(run_id, "rejected", "reviewer", note)
    elif action == "mark_paid":
        if s != "approved":
            raise ValueError("Only approved invoices can be marked as paid.")
        set_status(run_id, "paid", "user", note or "Included in payment run.")
    else:
        raise ValueError(f"Unknown action '{action}'")


class StageRunner:
    def __init__(self, run_id):
        self.run_id = run_id
        self.idx = None
        self.t0 = None

    def reset(self):
        db.execute("""UPDATE stages SET status='pending', started_at=NULL, finished_at=NULL, duration_ms=NULL,
                      summary=NULL, detail_json=NULL WHERE run_id=?""", (self.run_id,))

    def start(self, key):
        self.idx = next(i for i, (k, _) in enumerate(STAGES) if k == key)
        self.t0 = time.monotonic()
        db.execute("UPDATE stages SET status='running', started_at=? WHERE run_id=? AND idx=?",
                   (db.now_iso(), self.run_id, self.idx))

    def finish(self, status, summary, detail):
        elapsed = (time.monotonic() - self.t0) * 1000
        if elapsed < STAGE_MIN_MS:
            time.sleep((STAGE_MIN_MS - elapsed) / 1000)
            elapsed = STAGE_MIN_MS
        db.execute(
            """UPDATE stages SET status=?, finished_at=?, duration_ms=?, summary=?, detail_json=?
               WHERE run_id=? AND idx=?""",
            (status, db.now_iso(), int(elapsed), summary, json.dumps(detail, default=str), self.run_id, self.idx),
        )

    def skip(self, key, reason):
        idx = next(i for i, (k, _) in enumerate(STAGES) if k == key)
        db.execute("UPDATE stages SET status='skipped', summary=? WHERE run_id=? AND idx=?", (reason, self.run_id, idx))

    def skip_rest(self, reason):
        db.execute("UPDATE stages SET status='skipped', summary=? WHERE run_id=? AND status IN ('pending','running')",
                   (reason, self.run_id))


# ---------------------------------------------------------------------------
# Stage 4: validate the invoice on its own terms
# ---------------------------------------------------------------------------

def validate(ex, rules):
    checks = []
    if not ex.get("is_invoice", True):
        checks.append(check("not_invoice", "Document type", "fail", "This document does not look like an invoice.",
                            "critical", "not_invoice", "Return to sender — not an invoice."))
        return checks, {}

    missing = [f for f in ("vendor_name", "invoice_number", "invoice_date", "total") if not ex.get(f)]
    if "invoice_number" in missing or "total" in missing:
        checks.append(check("required_fields", "Required fields", "fail",
                            f"Missing {', '.join(missing).replace('_', ' ')} — cannot be posted without it.",
                            "high", "missing_info", "Request a corrected invoice from the vendor.", missing=missing))
    elif missing:
        checks.append(check("required_fields", "Required fields", "warn",
                            f"Missing {', '.join(missing).replace('_', ' ')}.", "high", "missing_info",
                            "Request a corrected invoice from the vendor.", missing=missing))
    else:
        checks.append(check("required_fields", "Required fields", "pass",
                            "Vendor, invoice number, date and total all present."))

    lines = ex.get("line_items") or []
    bad_lines = [l["description"] for l in lines
                 if l.get("quantity") is not None and l.get("unit_price") is not None and l.get("amount") is not None
                 and not close(l["quantity"] * l["unit_price"], l["amount"], 0.02 + abs(l["amount"]) * 0.0005)]
    sum_lines = round(sum((l.get("amount") or 0) for l in lines), 2)
    total = ex.get("total")
    tax = ex.get("tax_amount") or 0.0
    inclusive = bool(ex.get("tax_inclusive"))
    subtotal = ex.get("subtotal")

    if inclusive:
        gross = total if total is not None else sum_lines
        net = round(gross - tax, 2)
        factor = net / gross if gross else 1.0
        math_ok = close(sum_lines, gross)
        math_msg = (f"Lines sum to {sum_lines:,.2f} = total {gross:,.2f} (tax-inclusive). "
                    f"Backed out {tax:,.2f} tax → net {net:,.2f}.")
    else:
        sub = subtotal if subtotal is not None else sum_lines
        net = round(sub, 2)
        factor = 1.0
        math_ok = close(sum_lines, sub) and (total is None or close(sub + tax, total))
        math_msg = f"Lines {sum_lines:,.2f} = subtotal {sub:,.2f}; + tax {tax:,.2f} = total {(total or 0):,.2f}."
    if bad_lines:
        checks.append(check("line_math", "Line arithmetic", "fail",
                            f"Quantity × unit price does not equal amount on: {', '.join(bad_lines)}.",
                            "high", "math", "Request a corrected invoice from the vendor."))
    if math_ok:
        checks.append(check("totals_math", "Totals reconcile", "pass", math_msg))
    else:
        checks.append(check("totals_math", "Totals reconcile", "fail", "Totals do not add up. " + math_msg,
                            "high", "math", "Request a corrected invoice from the vendor."))
    if inclusive:
        checks.append(check("tax_inclusive", "Tax treatment", "pass",
                            f"Prices include tax; matching against the PO uses net amounts (÷{1 / factor:.4f})."))

    inv_date, due = parse_date(ex.get("invoice_date")), parse_date(ex.get("due_date"))
    today = date.fromisoformat(TODAY)
    if inv_date and inv_date > today + timedelta(days=1):
        checks.append(check("dates", "Dates", "fail", f"Invoice is dated in the future ({inv_date}).", "high",
                            "dates", "Request a corrected invoice from the vendor."))
    elif inv_date and (today - inv_date).days > 180:
        checks.append(check("dates", "Dates", "warn", f"Invoice is {(today - inv_date).days} days old.", "high",
                            "dates", "AP clerk to confirm the invoice is still payable."))
    elif due and inv_date and due < inv_date:
        checks.append(check("dates", "Dates", "warn", "Due date is before invoice date.", "low", "dates"))
    elif inv_date:
        checks.append(check("dates", "Dates", "pass", f"Invoice date {inv_date}, due {due or 'not stated'}."))

    threshold = rules["min_confidence_pct"] / 100
    conf = ex.get("field_confidence") or {}
    shaky = [k for k, v in conf.items() if ex.get(k) not in (None, [], "") and v < threshold]
    if shaky:
        checks.append(check("confidence", "Reading confidence", "warn",
                            f"Low-confidence reading of {', '.join(shaky).replace('_', ' ')} (below "
                            f"{rules['min_confidence_pct']}%) — verify against the PDF.",
                            "high", "low_confidence", "AP clerk to verify the highlighted fields against the PDF.",
                            fields=shaky))
    else:
        checks.append(check("confidence", "Reading confidence", "pass",
                            f"All key fields read with ≥ {rules['min_confidence_pct']}% confidence."))

    normalized_lines = []
    for l in lines:
        unit, amt = l.get("unit_price"), l.get("amount")
        normalized_lines.append({
            "sku": l.get("sku"), "description": l.get("description"), "quantity": l.get("quantity"),
            "unit_price_net": round(unit * factor, 4) if unit is not None else None,
            "amount_net": round(amt * factor, 2) if amt is not None else None,
        })
    computed = {"sum_lines": sum_lines, "subtotal": subtotal, "tax": tax, "total": total, "net": net,
                "tax_inclusive": inclusive, "lines": normalized_lines}
    return checks, computed


# ---------------------------------------------------------------------------
# Stage 5: vendor
# ---------------------------------------------------------------------------

def match_vendor(ex):
    vendors = refdata.vendors()
    name = ex.get("vendor_name") or ""
    tax = digits(ex.get("vendor_tax_id"))
    scored = []
    for v in vendors:
        s = max(fuzz.token_sort_ratio(name.lower(), n.lower()) for n in [v["legal_name"], *v["aliases"]])
        scored.append((s, v))
    scored.sort(key=lambda x: -x[0])
    candidates = [{"vendor_id": v["vendor_id"], "name": v["legal_name"], "name_score": round(s)} for s, v in scored[:3]]

    checks = []
    by_tax = next((v for v in vendors if tax and digits(v["tax_id"]) == tax), None)
    best_score, best = scored[0] if scored else (0, None)
    vendor, method = None, None
    if by_tax:
        vendor, method = by_tax, "tax ID"
        name_score = next(s for s, v in scored if v is by_tax)
        if name_score < 70:
            checks.append(check("vendor_identity", "Vendor identity", "warn",
                                f"Tax ID matches {by_tax['legal_name']} but the name on the invoice is '{name}'.",
                                "high", "vendor_identity", "AP clerk to confirm the vendor's identity."))
        else:
            checks.append(check("vendor_identity", "Vendor identity", "pass",
                                f"Matched {by_tax['legal_name']} ({by_tax['vendor_id']}) by tax ID {by_tax['tax_id']}."))
    elif best and best_score >= 90:
        vendor, method = best, "name"
        checks.append(check("vendor_identity", "Vendor identity", "pass",
                            f"Matched {best['legal_name']} ({best['vendor_id']}) by name ({best_score:.0f}% similar)."
                            + ("" if tax else " No tax ID printed on the invoice.")))
    elif best and best_score >= 75:
        vendor, method = best, "probable name"
        checks.append(check("vendor_identity", "Vendor identity", "warn",
                            f"Probable match to {best['legal_name']} ({best_score:.0f}% name similarity), tax ID not confirmed.",
                            "high", "vendor_identity", "AP clerk to confirm the vendor's identity."))
    else:
        checks.append(check("vendor_identity", "Vendor identity", "fail",
                            f"'{name or 'Unknown'}' is not in the approved vendor master.", "critical",
                            "unknown_vendor", "Route to procurement for vendor onboarding; do not pay."))
        return checks, None, {"candidates": candidates}

    if vendor["status"] != "approved":
        checks.append(check("vendor_status", "Vendor status", "fail",
                            f"{vendor['legal_name']} is {vendor['status'].upper()}: {vendor['status_reason']}.",
                            "critical", "blocked_vendor", "Do not pay. Route to procurement to resolve vendor status."))
    else:
        checks.append(check("vendor_status", "Vendor status", "pass", "Vendor is approved for payment."))

    cur = (ex.get("currency") or "").upper()
    if cur and cur != vendor["currency"]:
        checks.append(check("currency", "Currency", "warn",
                            f"Invoice currency {cur} differs from vendor's contracted {vendor['currency']}.", "high",
                            "currency", "AP clerk to confirm currency with the buyer."))
    detail = {"vendor": {k: vendor[k] for k in ("vendor_id", "legal_name", "tax_id", "status", "payment_terms_days",
                                                "contact_email", "contact_phone", "bank_name")},
              "bank_account_masked": mask(vendor["bank_account"]), "method": method, "candidates": candidates}
    return checks, vendor, detail


# ---------------------------------------------------------------------------
# Stage 6: purchase order (2-way: invoice ↔ PO)
# ---------------------------------------------------------------------------

def map_lines(inv_lines, po):
    mapping = []
    for il in inv_lines:
        best, best_score = None, 0.0
        for pl in po["lines"]:
            if il.get("sku") and il["sku"].upper() == pl["sku"].upper():
                best, best_score = pl, 1.0
                break
            desc = similarity(il.get("description"), pl["description"])
            price = 0.0
            if il.get("unit_price_net") and pl["unit_price"]:
                price = max(0.0, 1 - abs(il["unit_price_net"] - pl["unit_price"]) / pl["unit_price"])
            score = 0.7 * desc + 0.3 * price
            if score > best_score:
                best, best_score = pl, score
        matched = best if best_score >= 0.55 else None
        mapping.append({"invoice": il, "po_line": matched, "score": round(best_score, 2)})
    return mapping


def score_po(inv_lines, net, po, run_id):
    remaining = po["total"] - refdata.po_consumption(po["po_number"], run_id)["net_amount"]
    line_sim = sum(max((similarity(il.get("description"), pl["description"]) for pl in po["lines"]), default=0)
                   for il in inv_lines) / max(1, len(inv_lines))
    amount_sim = max(0.0, 1 - abs(net - remaining) / max(remaining, net, 1)) if remaining > 0 else 0.0
    return round(0.6 * line_sim + 0.4 * amount_sim, 3), round(line_sim, 3), round(amount_sim, 3), round(remaining, 2)


def match_po(ex, computed, vendor, run_id):
    checks = []
    pos = refdata.purchase_orders()
    ref = ex.get("po_reference")
    ref_d = digits(ref)
    po, method, candidates = None, None, []

    if ref_d:
        po = next((p for p in pos if digits(p["po_number"]) == ref_d), None)
        if not po and len(ref_d) >= 4:
            hits = [p for p in pos if digits(p["po_number"]).endswith(ref_d)]
            po = hits[0] if len(hits) == 1 else None
        if po:
            method = "explicit reference"
            if po["vendor_id"] != vendor["vendor_id"]:
                checks.append(check("po_vendor", "PO belongs to vendor", "fail",
                                    f"{po['po_number']} was issued to a different vendor ({po['vendor_id']}).", "high",
                                    "po_mismatch", "AP clerk to confirm the correct PO with the buyer."))
            elif po["status"] != "open":
                checks.append(check("po_status", "PO status", "fail", f"{po['po_number']} is {po['status']}.", "high",
                                    "po_closed", "Ask the buyer whether to reopen the PO or reject the invoice."))
            else:
                checks.append(check("po_found", "PO reference", "pass",
                                    f"Invoice references '{ref}' → {po['po_number']} ({po['description']})."))
        else:
            checks.append(check("po_found", "PO reference", "warn",
                                f"Invoice references '{ref}', which does not exist. Trying to infer the PO instead.",
                                "high", "po_unknown", "AP clerk to confirm the PO with the buyer."))

    if not po:
        open_pos = [p for p in pos if p["vendor_id"] == vendor["vendor_id"] and p["status"] == "open"]
        for p in open_pos:
            score, ls, am, rem = score_po(computed["lines"], computed["net"], p, run_id)
            candidates.append({"po_number": p["po_number"], "description": p["description"], "score": score,
                               "line_similarity": ls, "amount_similarity": am, "remaining": rem})
        candidates.sort(key=lambda c: -c["score"])
        if not candidates:
            checks.append(check("po_found", "PO match", "fail",
                                f"No PO reference on the invoice and no open PO for {vendor['legal_name']}.", "high",
                                "no_po", "Ask the requester to raise a PO (or confirm non-PO spend)."))
        else:
            top = candidates[0]
            gap = top["score"] - (candidates[1]["score"] if len(candidates) > 1 else 0)
            if top["score"] >= 0.75 and gap >= 0.15:
                po = next(p for p in pos if p["po_number"] == top["po_number"])
                method = "inferred"
                others = f" (next best {candidates[1]['po_number']} at {candidates[1]['score']:.2f})" if len(candidates) > 1 else ""
                checks.append(check("po_found", "PO match", "warn",
                                    f"No PO number on invoice. Inferred {po['po_number']} from vendor, line items and "
                                    f"amount — confidence {top['score']:.2f}{others}.", "low", "po_inferred"))
            else:
                checks.append(check("po_found", "PO match", "fail",
                                    "No PO reference and no single open PO matches confidently: "
                                    + ", ".join(f"{c['po_number']} ({c['score']:.2f})" for c in candidates[:3]) + ".",
                                    "high", "po_ambiguous", "AP clerk to pick the correct PO."))

    detail = {"method": method, "reference_on_invoice": ref, "candidates": candidates}
    if not po:
        return checks, None, [], detail

    mapping = map_lines(computed["lines"], po)
    unmatched = [m["invoice"]["description"] for m in mapping if not m["po_line"]]
    if unmatched:
        checks.append(check("line_mapping", "Lines on PO", "fail",
                            f"Billed items not on {po['po_number']}: {', '.join(unmatched)}.", "high",
                            "line_not_on_po", "Ask the buyer to confirm or amend the PO."))
    else:
        checks.append(check("line_mapping", "Lines on PO", "pass",
                            f"All {len(mapping)} invoice line(s) map to lines on {po['po_number']}."))
    detail["po"] = {k: po[k] for k in ("po_number", "description", "issue_date", "status", "buyer", "total", "lines",
                                       "match_type")}
    detail["line_map"] = [{"invoice_description": m["invoice"]["description"],
                           "po_sku": m["po_line"]["sku"] if m["po_line"] else None,
                           "po_description": m["po_line"]["description"] if m["po_line"] else None,
                           "score": m["score"]} for m in mapping]
    return checks, po, mapping, detail


# ---------------------------------------------------------------------------
# Stage 7: goods receipt (3-way: invoice ↔ PO ↔ GRN)
# ---------------------------------------------------------------------------

def match_receipt(po, mapping, cons, rules):
    match_type = po.get("match_type", "3-way")
    receipts = refdata.goods_receipts(po["po_number"])
    received = refdata.received_by_sku(po["po_number"])
    detail = {"match_type": match_type, "three_way_enabled": rules["three_way_match"],
              "receipt_tolerance_pct": rules["receipt_tolerance_pct"], "receipts": receipts, "lines": []}

    if not rules["three_way_match"]:
        return [check("receipt", "Goods receipt", "pass",
                      "3-way matching is switched off in Settings — invoice matched to the PO only (2-way).")], detail
    if match_type == "2-way":
        return [check("receipt", "Goods receipt", "pass",
                      f"{po['po_number']} is a services PO — no goods receipt required (2-way match).")], detail

    tol = rules["receipt_tolerance_pct"] / 100
    short = []
    for m in mapping:
        pl, il = m["po_line"], m["invoice"]
        if not pl:
            continue
        before = cons["quantity_by_sku"].get(pl["sku"], 0)
        this = il.get("quantity") or 0
        rec = received.get(pl["sku"], 0)
        cum = before + this
        detail["lines"].append({"sku": pl["sku"], "description": pl["description"], "ordered": pl["quantity"],
                                "received": rec, "billed_before": before, "this_invoice": this, "cumulative": cum})
        if cum > rec * (1 + tol) + 1e-6:
            short.append(f"{pl['sku']}: billing {cum:g} in total (incl. {before:g} earlier) but only {rec:g} received")

    grns = ", ".join(sorted({r["grn_number"] for r in receipts}))
    if not receipts:
        return [check("receipt", "Goods receipt", "fail",
                      f"No goods receipt (GRN) recorded for {po['po_number']} — delivery not confirmed.", "high",
                      "receipt_missing",
                      f"Hold until the receiving team posts a goods receipt for {po['po_number']}, then re-run.")], detail
    if short:
        return [check("receipt", "Billed vs received", "fail",
                      "Billed for more than was received: " + "; ".join(short) + ".", "high", "receipt_mismatch",
                      "Pay only for goods received: ask the vendor for a corrected invoice or credit note, or wait "
                      "for the remaining goods receipt and re-run.")], detail
    tol_txt = f" (tolerance {pct(rules['receipt_tolerance_pct'])})" if rules["receipt_tolerance_pct"] else ""
    return [check("receipt", "Billed vs received", "pass",
                  f"All billed quantities are covered by goods receipts {grns}{tol_txt}.")], detail


# ---------------------------------------------------------------------------
# Stage 8: business rules
# ---------------------------------------------------------------------------

def business_rules(ex, computed, vendor, po, mapping, cons, run, rules):
    checks = []
    line_results = []
    balance = None
    run_id = run["id"]

    if po:
        price_tol = rules["price_tolerance_pct"] / 100
        qty_tol = rules["quantity_tolerance_pct"] / 100
        price_fail, price_warn, qty_fail = [], [], []
        for m in mapping:
            pl, il = m["po_line"], m["invoice"]
            if not pl:
                continue
            res = {"sku": pl["sku"], "description": pl["description"], "po_unit_price": pl["unit_price"],
                   "invoice_unit_price_net": il.get("unit_price_net"), "po_quantity": pl["quantity"],
                   "previously_billed": cons["quantity_by_sku"].get(pl["sku"], 0), "this_invoice": il.get("quantity")}
            if il.get("unit_price_net") is not None:
                var = (il["unit_price_net"] - pl["unit_price"]) / pl["unit_price"]
                res["price_variance_pct"] = round(var * 100, 2)
                if var > price_tol + 1e-9:
                    price_fail.append(f"{pl['sku']} +{var * 100:.1f}%")
                elif var > 0.0005:
                    price_warn.append(f"{pl['sku']} +{var * 100:.1f}%")
            total_qty = res["previously_billed"] + (il.get("quantity") or 0)
            res["cumulative_quantity"] = total_qty
            res["quantity_limit"] = round(pl["quantity"] * (1 + qty_tol), 4)
            if total_qty > pl["quantity"] * (1 + qty_tol) + 1e-6:
                qty_fail.append(f"{pl['sku']}: {total_qty:g} billed of {pl['quantity']:g} ordered")
            line_results.append(res)

        tol = f"±{pct(rules['price_tolerance_pct'])}"
        if price_fail:
            checks.append(check("price_variance", "Unit prices vs PO", "fail",
                                f"Price above PO beyond the {tol} tolerance: {', '.join(price_fail)}.", "high",
                                "price_variance", "Ask the vendor for a credit note or the buyer to approve the price."))
        elif price_warn:
            checks.append(check("price_variance", "Unit prices vs PO", "warn",
                                f"Price above PO but within the {tol} tolerance: {', '.join(price_warn)}.", "low",
                                "price_variance_ok"))
        else:
            checks.append(check("price_variance", "Unit prices vs PO", "pass", "All unit prices match the PO."))

        qty_txt = f" (tolerance {pct(rules['quantity_tolerance_pct'])})" if rules["quantity_tolerance_pct"] else ""
        if qty_fail:
            checks.append(check("quantity", "Quantities vs PO", "fail",
                                "Billing more than ordered" + qty_txt + ": " + "; ".join(qty_fail) + ".", "high",
                                "over_billing", "Request a credit note from the vendor or a PO amendment from the buyer."))
        else:
            checks.append(check("quantity", "Quantities vs PO", "pass",
                                f"Cumulative billed quantities are within ordered quantities{qty_txt}."))

        billed_before = cons["net_amount"]
        after = round(billed_before + computed["net"], 2)
        allowed_over = min(po["total"] * rules["amount_tolerance_pct"] / 100, rules["amount_tolerance_abs"])
        balance = {"po_total": po["total"], "billed_before": billed_before, "this_invoice": computed["net"],
                   "billed_after": after, "remaining_after": round(po["total"] - after, 2),
                   "allowed_over": round(allowed_over, 2), "previous_invoices": cons["invoices"]}
        tol_desc = (f"tolerance {pct(rules['amount_tolerance_pct'])} or ${rules['amount_tolerance_abs']:,.0f}, "
                    f"whichever is lower = ${allowed_over:,.2f}")
        if after > po["total"] + allowed_over + 0.005:
            over = round(after - po["total"], 2)
            checks.append(check("po_balance", "PO balance", "fail",
                                f"Exceeds remaining PO balance: ${billed_before:,.2f} already billed + "
                                f"${computed['net']:,.2f} now = ${after:,.2f} vs PO ${po['total']:,.2f} "
                                f"(over by ${over:,.2f}; {tol_desc}).", "high", "over_billing",
                                "Request a credit note from the vendor or a PO amendment from the buyer."))
        elif after > po["total"] + 0.005:
            checks.append(check("po_balance", "PO balance", "warn",
                                f"Over the PO by ${after - po['total']:,.2f}, inside the {tol_desc}.", "low",
                                "over_billing_ok"))
        else:
            partial = " Partial billing." if after < po["total"] - 0.01 else ""
            checks.append(check("po_balance", "PO balance", "pass",
                                f"${computed['net']:,.2f} net fits the PO; ${po['total'] - after:,.2f} remains "
                                f"after this invoice.{partial}"))

    # Duplicates against the ledger (history + earlier invoices)
    prior = db.query("SELECT * FROM ledger WHERE vendor_id=? AND status != 'rejected' AND (run_id IS NULL OR run_id != ?)",
                     (vendor["vendor_id"], run_id))
    norm = db.normalize_invoice_number(ex.get("invoice_number"))
    total = ex.get("total") or 0
    inv_date = parse_date(ex.get("invoice_date"))
    window = rules["duplicate_window_days"]
    dup = None
    for r in prior:
        if r["file_hash"] and r["file_hash"] == run["file_hash"]:
            dup = check("duplicate", "Duplicate check", "fail",
                        f"Exact same file was already submitted as {r['invoice_number']} "
                        f"({STATUSES.get(r['status'], r['status']).lower()}).",
                        "critical", "duplicate", "Do not pay — already in the system. No action needed from the vendor.",
                        prior_invoice=r["invoice_number"])
            break
    if not dup:
        for r in prior:
            if not norm or r["invoice_number_norm"] != norm:
                continue
            same_amount = r["total"] and abs(r["total"] - total) <= max(0.01 * r["total"], 0.05)
            when = f" on {r['paid_on']}" if r["paid_on"] else ""
            state = STATUSES.get(r["status"], r["status"]).lower()
            if same_amount:
                dup = check("duplicate", "Duplicate check", "fail",
                            f"Duplicate of {r['invoice_number']} dated {r['invoice_date']} for ${r['total']:,.2f}, "
                            f"already {state}{when}. '{ex.get('invoice_number')}' normalises to the same "
                            f"number and the amount matches.", "critical", "duplicate",
                            "Do not pay. Tell the vendor this invoice was already settled.",
                            prior_invoice=r["invoice_number"])
            else:
                dup = check("duplicate", "Duplicate check", "warn",
                            f"Invoice number matches {r['invoice_number']} ({state}) but the amount differs "
                            f"(${r['total']:,.2f} vs ${total:,.2f}).", "high", "possible_duplicate",
                            "AP clerk to compare with the earlier invoice.", prior_invoice=r["invoice_number"])
            break
    if not dup and inv_date and window:
        for r in prior:
            d = parse_date(r["invoice_date"])
            if d and abs((d - inv_date).days) <= window and r["total"] and abs(r["total"] - total) <= 0.005 * r["total"]:
                dup = check("duplicate", "Duplicate check", "warn",
                            f"Same vendor, same amount (${total:,.2f}) and within {window} days "
                            f"of {r['invoice_number']} — possible duplicate under a new number.", "high",
                            "possible_duplicate", "AP clerk to compare with the earlier invoice.",
                            prior_invoice=r["invoice_number"])
                break
    checks.append(dup or check("duplicate", "Duplicate check", "pass",
                               f"No earlier invoice from this vendor matches number '{ex.get('invoice_number')}' "
                               f"or amount within {window} days ({len(prior)} on file)."))

    # Bank details vs vendor master — the payment-diversion check
    inv_acct = digits(ex.get("bank_account"))
    if not inv_acct:
        checks.append(check("bank", "Bank details", "pass",
                            "No bank details on invoice — payment goes to the account on file."))
    elif inv_acct != digits(vendor["bank_account"]):
        checks.append(check("bank", "Bank details", "fail",
                            f"Remit-to account {mask(inv_acct)} at {ex.get('bank_name') or 'unknown bank'} does not match "
                            f"the vendor master ({mask(vendor['bank_account'])} at {vendor['bank_name']}). "
                            "Changed bank details are the most common invoice-fraud pattern.", "high",
                            "bank_change",
                            f"Do not pay or update bank details until verified by phone with {vendor['legal_name']} "
                            f"at the number on file ({vendor['contact_phone']}).",
                            invoice_account=mask(inv_acct), master_account=mask(vendor["bank_account"])))
    else:
        checks.append(check("bank", "Bank details", "pass",
                            f"Remit-to account matches vendor master ({mask(inv_acct)})."))

    # Sender domain vs vendor master (email intake only)
    sender = (run.get("sender_email") or "").lower()
    if sender and "@" in sender:
        dom = sender.split("@", 1)[1]
        vdom = (vendor.get("contact_email") or "").lower().split("@")[-1]
        if vdom and dom != vdom and not dom.endswith("." + vdom):
            checks.append(check("sender", "Sender domain", "warn",
                                f"Invoice was emailed from {dom}, not {vendor['legal_name']}'s registered domain {vdom}.",
                                "high", "sender_domain",
                                f"Treat as suspicious: confirm with {vendor['legal_name']} using the contact on file."))
        else:
            checks.append(check("sender", "Sender domain", "pass", f"Sent from the vendor's registered domain ({dom})."))

    inv_date, due = parse_date(ex.get("invoice_date")), parse_date(ex.get("due_date"))
    if inv_date and due:
        days = (due - inv_date).days
        if days < vendor["payment_terms_days"] - 3:
            checks.append(check("terms", "Payment terms", "warn",
                                f"Invoice asks for payment in {days} days; contracted terms are Net "
                                f"{vendor['payment_terms_days']}. Pay on contract terms.", "low", "terms"))
        else:
            checks.append(check("terms", "Payment terms", "pass",
                                f"Due in {days} days, consistent with Net {vendor['payment_terms_days']}."))

    return checks, {"lines": line_results, "po_balance": balance}


# ---------------------------------------------------------------------------
# Stage 9: decision
# ---------------------------------------------------------------------------

def decide(all_checks):
    issues = [c for c in all_checks if c["status"] in ("fail", "warn")]
    issues.sort(key=lambda c: (-SEVERITY_RANK[c["severity"]], 0 if c["status"] == "fail" else 1))
    if any(c["status"] == "fail" and c["severity"] == "critical" for c in issues):
        decision = "REJECT"
    elif any(c["severity"] in ("high", "critical") for c in issues):
        decision = "HOLD"
    else:
        decision = "APPROVE"
    return decision, issues


HEADLINE_PHRASES = {
    "duplicate": "duplicate of an invoice already in the system",
    "possible_duplicate": "possible duplicate of an earlier invoice",
    "bank_change": "remit-to bank account differs from the vendor master",
    "sender_domain": "sent from an unregistered email domain",
    "over_billing": "billing exceeds what the PO allows",
    "receipt_missing": "goods not yet received",
    "receipt_mismatch": "billed for more than was received",
    "blocked_vendor": "vendor is blocked for payment",
    "unknown_vendor": "vendor is not in the approved vendor master",
    "vendor_identity": "vendor identity needs confirmation",
    "price_variance": "unit price above PO tolerance",
    "missing_info": "required fields are missing",
    "math": "invoice totals do not add up",
    "po_ambiguous": "PO could not be determined",
    "no_po": "no matching purchase order",
    "po_unknown": "referenced PO does not exist",
    "po_mismatch": "PO belongs to a different vendor",
    "po_closed": "PO is closed",
    "line_not_on_po": "billed items are not on the PO",
    "low_confidence": "parts of the document could not be read reliably",
    "not_invoice": "document is not an invoice",
    "currency": "currency differs from contract",
    "dates": "invoice dates need checking",
}


def template_narrative(decision, issues, ex, vendor, po):
    inv = ex.get("invoice_number") or "(no number)"
    who = vendor["legal_name"] if vendor else (ex.get("vendor_name") or "Unknown vendor")
    blocking = [c for c in issues if c["severity"] in ("high", "critical")]
    notes = [c for c in issues if c["severity"] == "low"]
    if decision == "APPROVE":
        headline = f"Matched: {who} invoice {inv} passes every control against {po['po_number'] if po else 'its PO'}."
        explanation = (f"All checks passed for ${(ex.get('total') or 0):,.2f}."
                       + (" Notes: " + " ".join(c["message"] for c in notes) if notes else ""))
    else:
        verb = "Rejected" if decision == "REJECT" else "Exception"
        top = blocking[0] if blocking else None
        phrase = HEADLINE_PHRASES.get(top["category"], top["label"].lower()) if top else "needs review"
        headline = f"{verb}: {who} {inv} — {phrase}."
        explanation = " ".join(c["message"] for c in blocking[:3])
    vendor_email = None
    vendor_cats = {"duplicate", "missing_info", "math", "over_billing", "unknown_vendor", "receipt_mismatch"}
    if any(c["category"] in vendor_cats for c in blocking) and \
            not any(c["category"] in ("bank_change", "sender_domain") for c in blocking):
        reason = blocking[0]["message"]
        vendor_email = (f"Hello {who} billing team,\n\nRegarding invoice {inv}: {reason}\n\n"
                        f"Please review and reply with a corrected invoice or credit note as appropriate.\n\n"
                        f"Thank you,\nAccounts Payable, Harborview Manufacturing")
    return {"headline": headline, "explanation": explanation, "vendor_email": vendor_email}


def next_action(status, issues, ex, vendor, po, status_reason):
    for c in issues:
        if c["severity"] in ("high", "critical") and c.get("action"):
            return c["action"]
    pay = (f"schedule payment of ${(ex.get('total') or 0):,.2f} for {ex.get('due_date') or 'contract terms'} "
           f"to the account on file ({mask(vendor['bank_account'])})") if vendor else "schedule payment"
    if status == "pending_approval":
        return f"Approver to sign off ({status_reason}). Once approved: post against {po['po_number']} and {pay}."
    if status == "approved":
        return f"Post to ERP against {po['po_number']} and {pay}."
    return "AP clerk to review."


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

class _ShortCircuit(Exception):
    pass


def run_pipeline(run_id):
    run = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    attempt = (run["attempts"] or 0) + 1
    rules = settings.get()
    db.execute("""UPDATE runs SET attempts=?, started_at=?, next_retry_at=NULL, error=NULL, error_detail=NULL,
                  rules_json=? WHERE id=?""", (attempt, db.now_iso(), json.dumps(rules), run_id))
    set_status(run_id, "processing", "system",
               "Processing started" + (f" (attempt {attempt} of {MAX_ATTEMPTS})" if attempt > 1 else ""))
    db.execute("DELETE FROM ledger WHERE run_id=?", (run_id,))
    run = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    sr = StageRunner(run_id)
    sr.reset()
    t_start = time.monotonic()
    all_checks = []
    ex, computed, vendor, po, mapping, balance = {}, {}, None, None, [], None
    try:
        # 1. Ingest
        sr.start("ingest")
        path = Path(run["file_path"])
        prior_same_file = db.query("SELECT id, status FROM runs WHERE file_hash=? AND id<? ORDER BY id DESC",
                                   (run["file_hash"], run_id))
        ingest_detail = {"filename": run["filename"], "size_kb": round(path.stat().st_size / 1024, 1),
                         "sha256": run["file_hash"], "source": run["source"], "sender": run["sender_email"],
                         "previous_runs_of_same_file": prior_same_file}
        note = f" Same file submitted before (invoice #{prior_same_file[0]['id']})." if prior_same_file else ""
        via = f" from {run['sender_email']}" if run["sender_email"] else ""
        sr.finish("pass", f"Received {run['filename']}{via} ({ingest_detail['size_kb']} KB).{note}", ingest_detail)

        # 2. Read
        sr.start("read")
        doc = extract.read_document(path)
        sr.finish("pass" if not doc["is_scanned"] else "warn",
                  f"{doc['pages']} page(s). " + ("Scanned image — no text layer; the model reads it visually."
                                                 if doc["is_scanned"] else f"Text layer found ({doc['text_chars']} chars)."),
                  doc)

        # 3. Extract
        sr.start("extract")
        mode = provider()
        db.execute("UPDATE runs SET extraction_mode=? WHERE id=?", (mode, run_id))
        ex, usage = extract.extract(path, run["file_hash"])
        threshold = rules["min_confidence_pct"] / 100
        low = [k for k, v in (ex.get("field_confidence") or {}).items() if ex.get(k) not in (None, [], "") and v < threshold]
        sr.finish("warn" if low or ex.get("extraction_warnings") else "pass",
                  f"{ex.get('vendor_name') or 'Unknown vendor'} · {ex.get('invoice_number') or 'no invoice #'} · "
                  f"{len(ex.get('line_items') or [])} line(s) · total {ex.get('total')}",
                  {"fields": ex, "usage": usage, "mode": mode})
        db.execute("""UPDATE runs SET vendor_name=?, invoice_number=?, invoice_date=?, due_date=?, total=?, currency=?
                      WHERE id=?""",
                   (ex.get("vendor_name"), ex.get("invoice_number"), ex.get("invoice_date"), ex.get("due_date"),
                    ex.get("total"), ex.get("currency"), run_id))

        # 4. Validate
        sr.start("validate")
        v_checks, computed = validate(ex, rules)
        all_checks += v_checks
        sr.finish(stage_status(v_checks), _summ(v_checks), {"checks": v_checks, "computed": computed})
        if not computed:
            raise _ShortCircuit()

        # 5. Vendor
        sr.start("vendor")
        vn_checks, vendor, vn_detail = match_vendor(ex)
        all_checks += vn_checks
        sr.finish(stage_status(vn_checks), _summ(vn_checks), {"checks": vn_checks, **vn_detail})
        if not vendor:
            raise _ShortCircuit()
        db.execute("UPDATE runs SET vendor_id=?, vendor_name=? WHERE id=?",
                   (vendor["vendor_id"], vendor["legal_name"], run_id))

        # 6. PO
        sr.start("po")
        po_checks, po, mapping, po_detail = match_po(ex, computed, vendor, run_id)
        all_checks += po_checks
        sr.finish(stage_status(po_checks), _summ(po_checks), {"checks": po_checks, **po_detail})
        cons = refdata.po_consumption(po["po_number"], run_id) if po else {"net_amount": 0, "quantity_by_sku": {},
                                                                           "invoices": []}
        if po:
            db.execute("UPDATE runs SET po_number=? WHERE id=?", (po["po_number"], run_id))

        # 7. Goods receipt
        if po:
            sr.start("receipt")
            gr_checks, gr_detail = match_receipt(po, mapping, cons, rules)
            all_checks += gr_checks
            sr.finish(stage_status(gr_checks), _summ(gr_checks), {"checks": gr_checks, **gr_detail})
        else:
            sr.skip("receipt", "Skipped — no purchase order matched.")

        # 8. Rules
        sr.start("rules")
        r_checks, r_detail = business_rules(ex, computed, vendor, po, mapping, cons, run, rules)
        all_checks += r_checks
        balance = r_detail.get("po_balance")
        sr.finish(stage_status(r_checks), _summ(r_checks), {"checks": r_checks, "rules": rules, **r_detail})

        _decide_and_record(sr, run_id, run, ex, computed, vendor, po, mapping, all_checks, balance, rules, t_start)
    except _ShortCircuit:
        sr.skip_rest("Skipped — an earlier stage was decisive.")
        _decide_and_record(sr, run_id, run, ex, computed, vendor, None, [], all_checks, None, rules, t_start)
    except extract.TransientExtractionError as e:
        if attempt < MAX_ATTEMPTS:
            delay = int(min(120, max(e.retry_after or 0, RETRY_DELAYS_S[min(attempt, len(RETRY_DELAYS_S)) - 1])))
            retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(timespec="milliseconds")
            db.execute("""UPDATE stages SET status='waiting', finished_at=?, summary=?, detail_json=?
                          WHERE run_id=? AND idx=?""",
                       (db.now_iso(), f"{e} Retrying automatically in {delay}s (attempt {attempt + 1} of {MAX_ATTEMPTS}).",
                        json.dumps({"reason": str(e), "technical_detail": e.detail, "retry_at": retry_at,
                                    "attempt": attempt, "max_attempts": MAX_ATTEMPTS}), run_id, sr.idx))
            db.execute("""UPDATE runs SET error=?, error_detail=?, next_retry_at=?, duration_ms=? WHERE id=?""",
                       (str(e), e.detail, retry_at, int((time.monotonic() - t_start) * 1000), run_id))
            set_status(run_id, "waiting_retry", "system",
                       f"{e} Automatic retry in {delay}s (attempt {attempt + 1} of {MAX_ATTEMPTS}).")
        else:
            _fail_run(sr, run_id, f"{e} Gave up after {MAX_ATTEMPTS} attempts.", e.detail, t_start)
    except extract.ExtractionError as e:
        _fail_run(sr, run_id, str(e), e.detail, t_start)
    except Exception as e:  # keep the UI informative on unexpected failures
        log.error("run %s failed: %s", run_id, traceback.format_exc())
        _fail_run(sr, run_id, "Unexpected error while processing this invoice.", f"{type(e).__name__}: {e}", t_start)


def _summ(checks):
    bad = [c for c in checks if c["status"] in ("fail", "warn")]
    if not bad:
        return f"{len(checks)} check(s) passed."
    return bad[0]["message"]


def _fail_run(sr, run_id, message, detail, t_start):
    if sr.idx is not None:
        db.execute("UPDATE stages SET status='error', finished_at=?, summary=?, detail_json=? WHERE run_id=? AND idx=?",
                   (db.now_iso(), message, json.dumps({"reason": message, "technical_detail": detail}), run_id, sr.idx))
    sr.skip_rest("Skipped — processing stopped.")
    db.execute("UPDATE runs SET error=?, error_detail=?, finished_at=?, duration_ms=? WHERE id=?",
               (message, detail, db.now_iso(), int((time.monotonic() - t_start) * 1000), run_id))
    set_status(run_id, "failed", "system", message)


def _decide_and_record(sr, run_id, run, ex, computed, vendor, po, mapping, all_checks, balance, rules, t_start):
    sr.start("decision")
    decision, issues = decide(all_checks)

    # Approval policy: what happens to a clean invoice depends on Settings.
    total = ex.get("total") or 0
    limit = rules["auto_approve_limit"]
    if decision == "REJECT":
        status, status_reason = "rejected", "a critical control failed"
    elif decision == "HOLD":
        status, status_reason = "needs_review", "one or more controls raised an exception"
    elif rules["approval_mode"] == "hitl":
        status, status_reason = "pending_approval", "human-in-the-loop mode — every invoice needs sign-off"
    elif limit and total > limit:
        status, status_reason = "pending_approval", f"total ${total:,.2f} is above the ${limit:,.0f} auto-approval limit"
    else:
        status, status_reason = "approved", "all controls passed in autonomous mode"

    narrative = template_narrative(decision, issues, ex, vendor, po)
    narrative_source = "template"
    if llm_enabled():
        try:
            payload = {
                "system_recommendation": decision, "resulting_status": STATUSES[status], "status_reason": status_reason,
                "vendor": vendor["legal_name"] if vendor else ex.get("vendor_name"),
                "vendor_contact": vendor["contact_email"] if vendor else ex.get("vendor_email"),
                "invoice_number": ex.get("invoice_number"), "invoice_date": ex.get("invoice_date"),
                "total": ex.get("total"), "currency": ex.get("currency"),
                "po_number": po["po_number"] if po else None, "po_balance": balance,
                "checks": [{k: c[k] for k in ("label", "status", "severity", "message")} for c in all_checks],
            }
            used_model = None
            stage = db.query_one("SELECT detail_json FROM stages WHERE run_id=? AND key='extract'", (run_id,))
            if stage and stage["detail_json"]:
                used_model = (json.loads(stage["detail_json"]).get("usage") or {}).get("model")
            narrative = extract.narrate(payload, used_model)
            narrative_source = provider()
        except Exception as e:  # explanation is best-effort; the decision stands regardless
            log.warning("narrative fallback for run %s: %s", run_id, e)
    action = next_action(status, issues, ex, vendor, po, status_reason)

    if vendor:
        lines = [{"sku": m["po_line"]["sku"], "quantity": m["invoice"].get("quantity") or 0,
                  "net_amount": m["invoice"].get("amount_net")} for m in mapping if m["po_line"]]
        db.execute(
            """INSERT INTO ledger (run_id, vendor_id, invoice_number, invoice_number_norm, invoice_date, po_number,
               net_amount, tax_amount, total, currency, status, lines_json, file_hash, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, vendor["vendor_id"], ex.get("invoice_number"), db.normalize_invoice_number(ex.get("invoice_number")),
             ex.get("invoice_date"), po["po_number"] if po else None, computed.get("net"), computed.get("tax"),
             ex.get("total"), ex.get("currency"), status, json.dumps(lines), run["file_hash"], "run", db.now_iso()),
        )

    counts = {s: sum(1 for c in all_checks if c["status"] == s) for s in ("pass", "warn", "fail")}
    result = {
        "decision": decision, "status": status, "status_reason": status_reason,
        "headline": narrative["headline"], "explanation": narrative["explanation"],
        "vendor_email": narrative.get("vendor_email"), "narrative_source": narrative_source,
        "next_action": action, "reasons": issues, "checks": all_checks, "check_counts": counts,
        "po_balance": balance, "extraction": ex,
    }
    sr.finish({"APPROVE": "pass", "HOLD": "warn", "REJECT": "fail"}[decision], narrative["headline"], result)
    db.execute(
        """UPDATE runs SET decision=?, headline=?, result_json=?, finished_at=?, duration_ms=?, approved_by=?,
           error=NULL, error_detail=NULL WHERE id=?""",
        (decision, narrative["headline"], json.dumps(result, default=str), db.now_iso(),
         int((time.monotonic() - t_start) * 1000), "system" if status == "approved" else None, run_id),
    )
    notes = {
        "approved": "Auto-approved — all controls passed.",
        "pending_approval": f"Recommended for approval; awaiting sign-off ({status_reason}).",
        "needs_review": "Exception raised — " + (issues[0]["message"] if issues else "needs review"),
        "rejected": "Rejected automatically — " + (issues[0]["message"] if issues else "critical control failed"),
    }
    set_status(run_id, status, "system", notes[status])
