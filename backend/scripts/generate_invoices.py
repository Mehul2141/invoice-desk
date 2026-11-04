"""Generate realistic sample invoice PDFs (clean + scanned) and a manifest.

Each sample also records its ground-truth extraction so the pipeline can run
in mock-extraction mode (no API key) for testing.

Usage: python scripts/generate_invoices.py
"""
import hashlib
import io
import json
import random
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)

BILL_TO = ["Harborview Manufacturing Inc.", "Accounts Payable", "1200 Lakeshore Drive",
           "Chicago, IL 60611", "ap@harborview-mfg.com"]


def money(x):
    return f"{x:,.2f}"


# ---------------------------------------------------------------------------
# Invoice specs
# ---------------------------------------------------------------------------

SAMPLES = [
    {
        "file": "01_happy_northwind.pdf",
        "title": "Happy path — clean invoice, explicit PO",
        "scenario": "happy_path",
        "expected": "APPROVE",
        "description": "Northwind office supplies. Clean text PDF, PO number in header, every line matches the PO, sales tax separated.",
        "style": "classic", "accent": (0.12, 0.30, 0.55),
        "vendor": ["Northwind Office Supplies Inc.", "455 W Fulton Market", "Chicago, IL 60661",
                   "billing@northwind-supplies.com", "EIN 84-2291047"],
        "invoice_number": "INV-NW-5512", "invoice_date": "2026-10-20", "due_date": "2026-11-19",
        "po_header": "PO-2026-1001", "po_notes": None,
        "lines": [("OFF-PAPER-A4", "Copy paper A4 80gsm (box of 5 reams)", 40, 32.50),
                  ("OFF-TONER-58A", "HP 58A black toner cartridge", 12, 89.00),
                  ("OFF-CHAIR-ERG", "Ergonomic mesh office chair", 6, 245.00)],
        "tax_rate": 0.0825, "tax_label": "Sales tax (IL 8.25%)", "tax_inclusive": False,
        "bank": ("Chase Bank", "441700219934", "021000021"),
        "terms": "Net 30", "notes": "Thank you for your business.",
    },
    {
        "file": "02_variance_brightline.pdf",
        "title": "Price variance inside tolerance",
        "scenario": "variance_in_tolerance",
        "expected": "APPROVE",
        "description": "Brightline IT. PO reference only appears in the notes. Support hours billed at $96.50 vs $95.00 on the PO (+1.6%) — inside the 2% tolerance, approved with a note.",
        "style": "modern", "accent": (0.05, 0.55, 0.45),
        "vendor": ["Brightline IT Services LLC", "88 Mission Street, Suite 400", "San Francisco, CA 94105",
                   "ar@brightline-it.com", "Tax ID: 27-5530918"],
        "invoice_number": "BL-2026-0318", "invoice_date": "2026-10-24", "due_date": "2026-11-23",
        "po_header": None, "po_notes": "Services rendered per your purchase order 2026-1002.",
        "lines": [("IT-LAPTOP-SVC", "Laptop setup and imaging", 25, 45.00),
                  ("IT-SUPPORT-HRS", "On-site IT support (hours)", 40, 96.50)],
        "tax_rate": 0.0, "tax_label": "Tax (services exempt)", "tax_inclusive": False,
        "bank": ("Wells Fargo", "662011884471", "121000248"),
        "terms": "Net 30", "notes": None,
    },
    {
        "file": "03_split_summit_part1.pdf",
        "title": "Edge case 1a — split invoice, first part",
        "scenario": "split_po_part1",
        "expected": "APPROVE",
        "description": "Summit Industrial bills part of PO-2026-1003 (bearings, belts, 20 of 100 seal kits). Partial billing is fine — approved, PO balance tracked.",
        "style": "industrial", "accent": (0.75, 0.38, 0.05),
        "vendor": ["Summit Industrial Parts Co.", "3100 Carnegie Ave", "Cleveland, OH 44115",
                   "invoices@summitparts.com", "Federal Tax ID 46-8810273"],
        "invoice_number": "SIP-88412", "invoice_date": "2026-10-10", "due_date": "2026-11-24",
        "po_header": "PO-2026-1003", "po_notes": "Partial shipment 1 of 2.",
        "lines": [("SIP-BRG-6204", "Ball bearing 6204-2RS", 500, 4.80),
                  ("SIP-BELT-B48", "V-belt B48", 200, 12.50),
                  ("SIP-SEAL-K12", "Hydraulic seal kit K12", 20, 51.00)],
        "tax_rate": 0.07, "tax_label": "Sales tax 7%", "tax_inclusive": False,
        "bank": ("Bank of America", "330177452280", "026009593"),
        "terms": "Net 45", "notes": None,
    },
    {
        "file": "04_split_summit_part2.pdf",
        "title": "Edge case 1b — split invoice over-bills the PO",
        "scenario": "split_po_overbill",
        "expected": "HOLD",
        "description": "Second Summit invoice bills all 100 seal kits again. Run 1a first: cumulative billing would be 120 of 100 kits and $1,020 over the PO — held for review.",
        "style": "industrial", "accent": (0.75, 0.38, 0.05),
        "vendor": ["Summit Industrial Parts Co.", "3100 Carnegie Ave", "Cleveland, OH 44115",
                   "invoices@summitparts.com", "Federal Tax ID 46-8810273"],
        "invoice_number": "SIP-88497", "invoice_date": "2026-10-27", "due_date": "2026-12-11",
        "po_header": "PO-2026-1003", "po_notes": "Final shipment 2 of 2.",
        "lines": [("SIP-SEAL-K12", "Hydraulic seal kit K12", 100, 51.00)],
        "tax_rate": 0.07, "tax_label": "Sales tax 7%", "tax_inclusive": False,
        "bank": ("Bank of America", "330177452280", "026009593"),
        "terms": "Net 45", "notes": None,
    },
    {
        "file": "05_duplicate_cloudnest_rescan.pdf",
        "title": "Edge case 2 — near-duplicate resubmission (scanned)",
        "scenario": "near_duplicate",
        "expected": "REJECT",
        "description": "CloudNest re-sends their October invoice as a scan with the number written 'CN-42' instead of 'INV-CN-0042'. Different file, different number format — same invoice, already paid on 2026-10-12.",
        "style": "minimal", "accent": (0.35, 0.25, 0.70), "scanned": True,
        "vendor": ["CloudNest Hosting Ltd.", "1501 4th Avenue", "Seattle, WA 98101",
                   "billing@cloudnest.io", "EIN 61-3392018"],
        "invoice_number": "CN-42", "invoice_date": "2026-10-05", "due_date": "2026-10-20",
        "po_header": "PO-2026-1004", "po_notes": None,
        "lines": [("CN-VM-STD", "Standard VM instance (per month)", 12, 140.00),
                  ("CN-STOR-TB", "Block storage per TB (per month)", 8, 45.00),
                  ("CN-SUP-PRM", "Premium support plan (per month)", 1, 450.00)],
        "tax_rate": 0.0, "tax_label": "Tax", "tax_inclusive": False,
        "bank": ("Citibank", "990233410076", "021000089"),
        "terms": "Net 15", "notes": "PAYMENT REMINDER - please remit at your earliest convenience.",
    },
    {
        "file": "06_bank_change_greenleaf.pdf",
        "title": "Edge case 3 — bank details changed (fraud signal)",
        "scenario": "bank_change",
        "expected": "HOLD",
        "description": "Greenleaf invoice matches its PO perfectly, but the remit-to bank account is new and differs from the vendor master. Classic payment-diversion pattern — held for verification.",
        "style": "classic", "accent": (0.15, 0.50, 0.20),
        "vendor": ["Greenleaf Facilities Management LLC", "700 Nicollet Mall", "Minneapolis, MN 55402",
                   "accounts@greenleaf-fm.com", "EIN 38-7720144"],
        "invoice_number": "GLF-10-2291", "invoice_date": "2026-10-28", "due_date": "2026-11-27",
        "po_header": "PO-2026-1005", "po_notes": None,
        "lines": [("GL-CLEAN-MO", "Office cleaning service - October", 1, 3200.00),
                  ("GL-HVAC-PM", "HVAC preventive maintenance", 1, 1450.00),
                  ("GL-WASTE", "Waste and recycling collection - October", 1, 380.00)],
        "tax_rate": 0.0, "tax_label": "Tax (services exempt)", "tax_inclusive": False,
        "bank": ("Metro Federal Credit Union", "882011456603", "271070801"),
        "terms": "Net 30",
        "notes": "IMPORTANT: We have changed banks. Please update your records and remit to the new account below effective immediately.",
    },
    {
        "file": "07_scanned_apex_no_po.pdf",
        "title": "Edge case 4 — scanned, no PO number, tax-inclusive",
        "scenario": "inferred_po",
        "expected": "APPROVE",
        "description": "Apex Logistics scanned invoice. No PO reference anywhere and prices include 13% HST. The process backs out tax and infers PO-2026-1006 from vendor + lines + amount (the other open Apex PO is a decoy).",
        "style": "modern", "accent": (0.55, 0.10, 0.15), "scanned": True,
        "vendor": ["Apex Logistics Corp.", "200 Bay Street, Suite 1800", "Toronto, ON M5J 2J2",
                   "ar@apexlogistics.ca", "Business No. 52-1187309"],
        "invoice_number": "APX-77031", "invoice_date": "2026-10-22", "due_date": "2026-11-21",
        "po_header": None, "po_notes": None,
        "lines": [("", "FTL Chicago IL -> Dallas TX (loads)", 3, 2429.50),
                  ("", "Liftgate delivery", 3, 141.25),
                  ("", "Fuel surcharge", 3, 203.40)],
        "tax_rate": 0.13, "tax_label": "HST 13% (included)", "tax_inclusive": True,
        "bank": ("PNC Bank", "778122095536", "043000096"),
        "terms": "Net 30", "notes": "All amounts include HST. Thank you for shipping with Apex.",
    },
    {
        "file": "08_blocked_vendor_quantum.pdf",
        "title": "Blocked vendor",
        "scenario": "blocked_vendor",
        "expected": "REJECT",
        "description": "Quantum Print is in the vendor master but blocked after a failed compliance review. Everything else is fine — rejected and routed to procurement.",
        "style": "minimal", "accent": (0.2, 0.2, 0.2),
        "vendor": ["Quantum Print & Signage Inc.", "45 Market Street", "Newark, NJ 07102",
                   "billing@quantumprint.com", "EIN 91-4402871"],
        "invoice_number": "QPS-3390", "invoice_date": "2026-10-18", "due_date": "2026-11-17",
        "po_header": "PO-2026-1008", "po_notes": None,
        "lines": [("QP-BANNER-3X8", "Vinyl trade show banner 3x8 ft", 20, 85.00)],
        "tax_rate": 0.06625, "tax_label": "NJ sales tax 6.625%", "tax_inclusive": False,
        "bank": ("TD Bank", "223488901123", "031101266"),
        "terms": "Net 30", "notes": None,
    },
    {
        "file": "09_receipt_short_northwind.pdf",
        "title": "3-way match — billed more than received",
        "scenario": "receipt_short",
        "expected": "HOLD",
        "description": "Northwind bills all 10 monitors on PO-2026-1010, but the warehouse goods receipt (GRN-7010) shows only 8 arrived. Matches the PO (2-way) but fails the 3-way match — held until the goods are received.",
        "style": "classic", "accent": (0.12, 0.30, 0.55),
        "vendor": ["Northwind Office Supplies Inc.", "455 W Fulton Market", "Chicago, IL 60661",
                   "billing@northwind-supplies.com", "EIN 84-2291047"],
        "invoice_number": "INV-NW-5561", "invoice_date": "2026-10-29", "due_date": "2026-11-28",
        "po_header": "PO-2026-1010", "po_notes": None,
        "lines": [("MON-27Q", "27-inch QHD monitor", 10, 189.00),
                  ("DOCK-USBC", "USB-C docking station", 10, 129.00)],
        "tax_rate": 0.0825, "tax_label": "Sales tax (IL 8.25%)", "tax_inclusive": False,
        "bank": ("Chase Bank", "441700219934", "021000021"),
        "terms": "Net 30", "notes": "Thank you for your business.",
    },
]


def totals(s):
    line_amounts = [round(q * p, 2) for _, _, q, p in s["lines"]]
    gross_or_net = round(sum(line_amounts), 2)
    if s["tax_inclusive"]:
        total = gross_or_net
        tax = round(total - total / (1 + s["tax_rate"]), 2)
        subtotal = gross_or_net
    else:
        subtotal = gross_or_net
        tax = round(subtotal * s["tax_rate"], 2)
        total = round(subtotal + tax, 2)
    return line_amounts, subtotal, tax, total


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def draw_invoice(s, path):
    W, H = LETTER
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle(f"Invoice {s['invoice_number']}")
    acc = colors.Color(*s["accent"])
    style = s["style"]
    line_amounts, subtotal, tax, total = totals(s)
    m = 0.7 * inch

    # Header block — varies per style so layouts differ between vendors
    if style == "modern":
        c.setFillColor(acc)
        c.rect(0, H - 1.3 * inch, W, 1.3 * inch, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 20)
        c.drawString(m, H - 0.65 * inch, s["vendor"][0])
        c.setFont("Helvetica", 9)
        c.drawString(m, H - 0.9 * inch, "  ·  ".join(s["vendor"][1:3]))
        c.drawString(m, H - 1.08 * inch, "  ·  ".join(s["vendor"][3:]))
        c.setFont("Helvetica-Bold", 26)
        c.drawRightString(W - m, H - 0.75 * inch, "INVOICE")
        y = H - 1.7 * inch
    elif style == "industrial":
        c.setStrokeColor(acc)
        c.setLineWidth(3)
        c.line(m, H - 0.5 * inch, W - m, H - 0.5 * inch)
        c.setFillColor(colors.black)
        c.setFont("Courier-Bold", 16)
        c.drawString(m, H - 0.85 * inch, s["vendor"][0].upper())
        c.setFont("Courier", 9)
        for i, ln in enumerate(s["vendor"][1:]):
            c.drawString(m, H - 1.05 * inch - i * 11, ln)
        c.setFont("Courier-Bold", 18)
        c.setFillColor(acc)
        c.drawRightString(W - m, H - 0.85 * inch, "TAX INVOICE")
        y = H - 1.85 * inch
    elif style == "minimal":
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(m, H - 0.8 * inch, s["vendor"][0])
        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#555555"))
        for i, ln in enumerate(s["vendor"][1:]):
            c.drawString(m, H - 1.0 * inch - i * 10.5, ln)
        c.setFillColor(acc)
        c.setFont("Helvetica", 30)
        c.drawRightString(W - m, H - 0.9 * inch, "Invoice")
        y = H - 1.8 * inch
    else:  # classic
        c.setFillColor(acc)
        c.setFont("Times-Bold", 22)
        c.drawString(m, H - 0.85 * inch, s["vendor"][0])
        c.setFillColor(colors.black)
        c.setFont("Times-Roman", 10)
        for i, ln in enumerate(s["vendor"][1:]):
            c.drawString(m, H - 1.1 * inch - i * 12, ln)
        c.setFont("Times-Bold", 16)
        c.drawRightString(W - m, H - 0.85 * inch, "INVOICE")
        y = H - 1.9 * inch

    body_font = "Courier" if style == "industrial" else ("Times-Roman" if style == "classic" else "Helvetica")
    bold_font = "Courier-Bold" if style == "industrial" else ("Times-Bold" if style == "classic" else "Helvetica-Bold")

    # Bill-to + invoice meta
    c.setFillColor(colors.black)
    c.setFont(bold_font, 9.5)
    c.drawString(m, y, "BILL TO")
    c.setFont(body_font, 9.5)
    for i, ln in enumerate(BILL_TO):
        c.drawString(m, y - 13 - i * 12, ln)

    meta = [("Invoice No.", s["invoice_number"]), ("Invoice Date", s["invoice_date"]),
            ("Due Date", s["due_date"]), ("Terms", s["terms"])]
    if s["po_header"]:
        meta.insert(1, ("PO Number", s["po_header"]))
    mx = W - m - 2.6 * inch
    for i, (k, v) in enumerate(meta):
        c.setFont(bold_font, 9.5)
        c.drawString(mx, y - i * 14, k)
        c.setFont(body_font, 9.5)
        c.drawRightString(W - m, y - i * 14, v)

    # Line items table
    y -= 1.25 * inch
    cols = [m, m + 1.25 * inch, W - m - 2.6 * inch, W - m - 1.45 * inch, W - m]
    show_sku = any(sku for sku, *_ in s["lines"])
    c.setFillColor(acc if style != "minimal" else colors.HexColor("#EEEEEE"))
    c.rect(m, y - 4, W - 2 * m, 18, fill=1, stroke=0)
    c.setFillColor(colors.white if style != "minimal" else colors.black)
    c.setFont(bold_font, 9)
    if show_sku:
        c.drawString(cols[0] + 4, y + 1, "Item")
        c.drawString(cols[1], y + 1, "Description")
    else:
        c.drawString(cols[0] + 4, y + 1, "Description")
    c.drawRightString(cols[2] + 0.5 * inch, y + 1, "Qty")
    c.drawRightString(cols[3] + 0.3 * inch, y + 1, "Unit Price")
    c.drawRightString(cols[4] - 4, y + 1, "Amount")
    c.setFillColor(colors.black)
    c.setFont(body_font, 9)
    y -= 20
    for (sku, desc, q, p), amt in zip(s["lines"], line_amounts):
        if show_sku:
            c.drawString(cols[0] + 4, y, sku)
            c.drawString(cols[1], y, desc)
        else:
            c.drawString(cols[0] + 4, y, desc)
        c.drawRightString(cols[2] + 0.5 * inch, y, f"{q:g}")
        c.drawRightString(cols[3] + 0.3 * inch, y, money(p))
        c.drawRightString(cols[4] - 4, y, money(amt))
        c.setStrokeColor(colors.HexColor("#DDDDDD"))
        c.setLineWidth(0.5)
        c.line(m, y - 5, W - m, y - 5)
        y -= 18

    # Totals
    y -= 10
    tx = W - m - 2.6 * inch
    rows = []
    if s["tax_inclusive"]:
        rows = [("Total (USD)", money(total), True), (s["tax_label"], money(tax), False)]
    else:
        rows = [("Subtotal", money(subtotal), False), (s["tax_label"], money(tax), False),
                ("Total Due (USD)", money(total), True)]
    for label, val, strong in rows:
        c.setFont(bold_font if strong else body_font, 11 if strong else 9.5)
        c.drawString(tx, y, label)
        c.drawRightString(W - m, y, val)
        y -= 16

    # Notes, PO reference in notes, remit-to
    y -= 20
    c.setFont(bold_font, 9.5)
    c.drawString(m, y, "Notes")
    c.setFont(body_font, 9)
    note_lines = [n for n in [s.get("po_notes"), s.get("notes")] if n]
    if not note_lines:
        note_lines = ["—"]
    for n in note_lines:
        y -= 13
        c.drawString(m, y, n)

    y -= 30
    c.setFont(bold_font, 9.5)
    c.drawString(m, y, "Remit payment to")
    c.setFont(body_font, 9)
    bank, acct, routing = s["bank"]
    for i, ln in enumerate([f"Bank: {bank}", f"Account No.: {acct}", f"Routing (ABA): {routing}",
                            f"Account name: {s['vendor'][0]}"]):
        c.drawString(m, y - 13 - i * 12, ln)

    c.setFont(body_font, 7.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawCentredString(W / 2, 0.5 * inch, f"{s['vendor'][0]} · {s['vendor'][3]} · Please quote invoice number with payment")
    c.showPage()
    c.save()


def make_scanned(src: Path, dst: Path, seed: int):
    """Rasterise a PDF and add scanner artefacts, producing an image-only PDF."""
    rnd = random.Random(seed)
    doc = fitz.open(src)
    pages = []
    for page in doc:
        pix = page.get_pixmap(dpi=130)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        img = img.rotate(rnd.uniform(-1.4, 1.4), expand=False, fillcolor=245, resample=Image.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        px = img.load()
        w, h = img.size
        for _ in range(w * h // 60):
            x, y = rnd.randrange(w), rnd.randrange(h)
            px[x, y] = max(0, min(255, px[x, y] + rnd.randint(-70, 40)))
        # Slight grey cast like a photocopy
        img = img.point(lambda v: int(30 + v * 0.86))
        pages.append(img.convert("RGB"))
    doc.close()
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:], resolution=130)
    dst.write_bytes(buf.getvalue())


def ground_truth(s):
    line_amounts, subtotal, tax, total = totals(s)
    po = s["po_header"] or (("PO-" + s["po_notes"].split("order ")[1].rstrip(".")) if s.get("po_notes") and "order " in s["po_notes"] else None)
    return {
        "is_invoice": True,
        "vendor_name": s["vendor"][0],
        "vendor_address": ", ".join(s["vendor"][1:3]),
        "vendor_tax_id": s["vendor"][4].split()[-1],
        "vendor_email": s["vendor"][3],
        "invoice_number": s["invoice_number"],
        "invoice_date": s["invoice_date"],
        "due_date": s["due_date"],
        "currency": "USD",
        "po_reference": po,
        "line_items": [
            {"sku": sku or None, "description": d, "quantity": q, "unit_price": p, "amount": a}
            for (sku, d, q, p), a in zip(s["lines"], line_amounts)
        ],
        "subtotal": None if s["tax_inclusive"] else subtotal,
        "tax_amount": tax,
        "tax_rate": s["tax_rate"],
        "tax_inclusive": s["tax_inclusive"],
        "total": total,
        "bank_name": s["bank"][0],
        "bank_account": s["bank"][1],
        "routing_number": s["bank"][2],
        "payment_terms": s["terms"],
        "notes": " ".join(n for n in [s.get("po_notes"), s.get("notes")] if n) or None,
        "field_confidence": {"vendor_name": 0.98, "invoice_number": 0.97, "invoice_date": 0.97,
                             "po_reference": 0.95 if po else 0.0, "line_items": 0.95, "total": 0.98,
                             "bank_account": 0.95},
        "extraction_warnings": ["Document is a scanned image; text read visually."] if s.get("scanned") else [],
    }


def main():
    manifest = []
    for i, s in enumerate(SAMPLES):
        target = OUT / s["file"]
        if s.get("scanned"):
            tmp = OUT / f".clean_{s['file']}"
            draw_invoice(s, tmp)
            make_scanned(tmp, target, seed=i + 7)
            tmp.unlink()
        else:
            draw_invoice(s, target)
        sha = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest.append({
            "file": s["file"], "title": s["title"], "scenario": s["scenario"],
            "expected": s["expected"], "description": s["description"],
            "scanned": bool(s.get("scanned")), "sha256": sha,
            "ground_truth": ground_truth(s),
        })
        print(f"wrote {target.name}  ({'scanned' if s.get('scanned') else 'text'})")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"manifest: {len(manifest)} samples")


if __name__ == "__main__":
    main()
