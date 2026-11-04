"""Reference data: vendor master and purchase orders (the 'procurement system')."""
import csv
import json
from collections import defaultdict

from . import db
from .config import DATA_DIR


def _read(name):
    with open(DATA_DIR / name) as f:
        return list(csv.DictReader(f))


def vendors():
    out = []
    for v in _read("vendors.csv"):
        v["aliases"] = [a for a in v["aliases"].split("|") if a]
        v["payment_terms_days"] = int(v["payment_terms_days"])
        out.append(v)
    return out


def vendor_by_id(vendor_id):
    return next((v for v in vendors() if v["vendor_id"] == vendor_id), None)


def purchase_orders():
    lines = defaultdict(list)
    for ln in _read("po_lines.csv"):
        qty, price = float(ln["quantity"]), float(ln["unit_price"])
        lines[ln["po_number"]].append({
            "line_no": int(ln["line_no"]), "sku": ln["sku"], "description": ln["description"],
            "quantity": qty, "unit_price": price, "amount": round(qty * price, 2),
        })
    out = []
    for po in _read("purchase_orders.csv"):
        po["lines"] = lines[po["po_number"]]
        po["total"] = round(sum(l["amount"] for l in po["lines"]), 2)
        out.append(po)
    return out


def po_by_number(po_number):
    return next((p for p in purchase_orders() if p["po_number"] == po_number), None)


def goods_receipts(po_number=None):
    rows = []
    for r in _read("goods_receipts.csv"):
        r["quantity_received"] = float(r["quantity_received"])
        if po_number is None or r["po_number"] == po_number:
            rows.append(r)
    return rows


def received_by_sku(po_number):
    out = defaultdict(float)
    for r in goods_receipts(po_number):
        out[r["sku"]] += r["quantity_received"]
    return dict(out)


# Invoices that commit PO budget: approved, paid, or approved by the system and awaiting sign-off.
COMMITTED = ("approved", "paid", "pending_approval")


def po_consumption(po_number, exclude_run_id=None):
    """Net amount and per-SKU quantity already billed against a PO."""
    rows = db.query(
        f"SELECT * FROM ledger WHERE po_number = ? AND status IN ({','.join('?' * len(COMMITTED))}) "
        "AND (run_id IS NULL OR run_id != ?)",
        (po_number, *COMMITTED, exclude_run_id or -1),
    )
    po = po_by_number(po_number)
    prices = {l["sku"]: l["unit_price"] for l in po["lines"]} if po else {}
    qty = defaultdict(float)
    amount = 0.0
    invoices = []
    for r in rows:
        line_list = json.loads(r["lines_json"] or "[]")
        for l in line_list:
            qty[l["sku"]] += l.get("quantity") or 0
        amount += r["net_amount"] if r["net_amount"] is not None else sum(
            (l.get("quantity") or 0) * prices.get(l["sku"], 0) for l in line_list)
        invoices.append({"invoice_number": r["invoice_number"], "net_amount": r["net_amount"],
                         "status": r["status"], "run_id": r["run_id"]})
    return {"net_amount": round(amount, 2), "quantity_by_sku": dict(qty), "invoices": invoices}


def purchase_orders_with_balance():
    out = []
    for po in purchase_orders():
        cons = po_consumption(po["po_number"])
        po = dict(po)
        po["billed"] = cons["net_amount"]
        po["remaining"] = round(po["total"] - cons["net_amount"], 2)
        po["invoices"] = cons["invoices"]
        received = received_by_sku(po["po_number"])
        for l in po["lines"]:
            l["billed_quantity"] = cons["quantity_by_sku"].get(l["sku"], 0)
            l["received_quantity"] = received.get(l["sku"], 0)
        po["receipts"] = sorted({r["grn_number"] for r in goods_receipts(po["po_number"])})
        vendor = vendor_by_id(po["vendor_id"])
        po["vendor_name"] = vendor["legal_name"] if vendor else po["vendor_id"]
        out.append(po)
    return out
