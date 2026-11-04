# Invoice Desk: user guide

Invoice Desk automates accounts-payable invoice processing. Vendor invoices arrive as PDFs (by email or upload). For each one, Invoice Desk:
1. reads it, including scanned copies
2. matches it to your purchase orders and goods receipts
3. checks it against your AP controls
4. approves it for payment, rejects it, or sends it to a person with a clear explanation

Every step is visible, and every decision is recorded.

> **How decisions are made:** AI is used only to *read* the invoice. Every approval decision is made by fixed rules that your finance team configures, so the same invoice always gets the same outcome and you can always see why.

---

## Contents

1. [Install and start](#1-install-and-start)
2. [A tour of the app](#2-a-tour-of-the-app)
3. [Processing invoices](#3-processing-invoices)
4. [Understanding the result](#4-understanding-the-result)
5. [Working the Approvals queue](#5-working-the-approvals-queue)
6. [Rules and approval policy](#6-rules-and-approval-policy)
7. [Try it with the sample invoices](#7-try-it-with-the-sample-invoices)
8. [When the AI service is busy](#8-when-the-ai-service-is-busy)
9. [Your reference data](#9-your-reference-data)
10. [FAQ and troubleshooting](#10-faq-and-troubleshooting)
11. [Scope of this version](#11-scope-of-this-version)

---

## 1. Install and start

### What you need
- **macOS or Linux.** On Windows, use WSL, or run the manual commands at the end of this section.
- **Python 3.9 or newer.** Check with `python3 --version`.
- **Node.js 18 or newer.** Check with `node --version`. Download from https://nodejs.org if needed.
- **An AI key for reading invoices.** Either:
  - a **Google Gemini API key**, free from https://aistudio.google.com → *Get API key*, or
  - an **Anthropic API key**, paid, from https://console.anthropic.com.

  Without a key, the app still runs in *demo mode*, but it can only read the bundled sample invoices.

### First-time setup
From the project folder:

```bash
./setup.sh
```

This installs the Python and JavaScript dependencies and creates `backend/.env`.

Then open `backend/.env` in a text editor and paste your key:

```
GEMINI_API_KEY=your-key-here
```

Keep this file private. It is excluded from version control.

### Start the app

```bash
./start.sh
```

Open **http://localhost:5173** in your browser.
- Keep the terminal window open while you use the app.
- Press **Ctrl+C** to stop it.

The bottom-left of the sidebar shows which AI service is reading invoices (for example *Gemini · gemini-3.5-flash*) and the current approval mode.

<details>
<summary>Manual commands (Windows, or if the scripts don't suit your setup)</summary>

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
cp .env.example .env                             # then add your key
.venv/bin/uvicorn app.main:app --port 8000       # Windows: .venv\Scripts\uvicorn app.main:app --port 8000

# frontend (second terminal)
cd frontend
npm install
npx vite --port 5173
```
</details>

---

## 2. A tour of the app

| Screen | What it's for |
|---|---|
| **Dashboard** | Your overview: invoices received, the *touchless rate* (share approved with no human touch), invoices awaiting a person, value approved, value stopped before payment, and average processing time. The **invoice lifecycle** strip shows how many invoices are in each status; click one to filter the list. Click any invoice to open it. |
| **AP inbox** | The accounts-payable mailbox. Each email shows its sender, subject and PDF attachment. Process invoices one at a time or all at once, or upload a PDF directly. |
| **Invoice page** | Everything about one invoice: its status, the decision and the reasons, the next action, the buttons available to you, each processing stage in detail, the original PDF, and the full **audit trail**. |
| **Approvals** | Your work queue: invoices that need a person, in three tabs (**Needs review**, **Pending approval**, **Failed**). |
| **Vendors, POs & GRNs** | The data invoices are checked against: purchase orders (with ordered, received and billed quantities and remaining balance), goods receipts, the approved-vendor list, and the invoice ledger. |
| **Rules & settings** | Your matching tolerances and approval policy. |

---

## 3. Processing invoices

### From the AP inbox
1. Open **AP inbox**. New emails have a blue dot.
2. Select an email to read it and preview the attached invoice.
3. Do one of the following:
   - Click **Process invoice** to process that email. The invoice page opens and you can watch it being processed live.
   - Click **Process all new** to queue every unprocessed email. Invoices are handled one at a time, oldest first, and each email shows its status as it updates.

### By upload
Click **Upload invoice** (top of the AP inbox) and choose a PDF. Typed and scanned invoices both work.

### What happens to each invoice
Each invoice goes through nine stages. You can watch them live and click any stage for the detail.

| # | Stage | What it checks |
|---|---|---|
| 1 | Ingest | Receives the file, records who sent it, and fingerprints it so a resubmitted copy can be recognised. |
| 2 | Read document | Is it a digital PDF or a scan? |
| 3 | Extract fields | AI reads the invoice into fields (vendor, invoice number, dates, PO reference, line items, tax, total, bank details), each with a confidence score. |
| 4 | Validate invoice | Do the lines add up to the subtotal, and the subtotal plus tax to the total? Are required fields present? Are the dates sensible? If prices include tax, the tax is separated out. |
| 5 | Match vendor | Is the sender an approved vendor (by tax ID or name)? Are they blocked? |
| 6 | Match purchase order | **2-way match.** Finds the PO from the reference on the invoice. If there is none, it identifies the most likely PO from the vendor, items and amount, and shows its reasoning. |
| 7 | Match goods receipt | **3-way match.** For goods, are the billed quantities covered by what your receiving team actually recorded as received? Services are matched 2-way only. |
| 8 | Business rules | Prices, quantities and amounts against your tolerances. Also checks for duplicates, a changed bank account, the sender's email domain, and payment terms. |
| 9 | Decision | Turns the checks into a recommendation and a status, and writes a plain-English explanation and the next action. |

---

## 4. Understanding the result

At the top of every finished invoice you'll see three things.

**1. The status.** This is where the invoice is in its journey:

| Status | Meaning | What you do |
|---|---|---|
| **Queued** | Waiting its turn. | Nothing. |
| **Processing** | Being read and checked. | Nothing. |
| **Waiting for AI** | The AI reading service is temporarily busy; it retries automatically ([section 8](#8-when-the-ai-service-is-busy)). | Nothing, or click **Retry now**. |
| **Approved** | Passed every control and is ready to pay. It is marked *auto-approved* or *approved by reviewer*. | **Mark as paid** after your payment run. |
| **Pending approval** | Passed every control, but your policy requires sign-off (human-in-the-loop mode, or above the auto-approval limit). | Approve or reject in **Approvals**. |
| **Needs review** | A control raised an exception, such as a price variance, over-billing, goods not received, or changed bank details. | Review in **Approvals**: override with a note, or reject. |
| **Rejected** | Will not be paid: a duplicate, a blocked or unknown vendor, or rejected by a reviewer. | Nothing. If rules changed, you can **Re-run with current rules**. |
| **Paid** | Settled. | — |
| **Failed** | Could not be read (see [section 8](#8-when-the-ai-service-is-busy)). Nothing was approved. | **Retry now**. |

**2. The system recommendation.** This is what the controls concluded:
- **Matched:** everything checked out.
- **Exception:** a person should look.
- **Reject:** a critical control failed.

The recommendation and the status can differ. For example, an invoice can be *Matched* but *Pending approval* if your policy requires sign-off.

**3. The explanation.**
- **Headline and summary:** in plain English.
- **Why:** every issue found. Minor notes, such as a price inside your tolerance, are shown in grey.
- **Next action:** what should happen next, for example *"Verify the bank change by phone using the number on file before paying."*
- **Draft email to vendor:** where the vendor needs to act. Nothing is ever sent automatically.

### More detail
- **Stage tabs:** click any stage for its full evidence. Examples:
  - the fields read, with confidence scores
  - the PO candidates and how each invoice line mapped to a PO line
  - the goods receipts, with ordered / received / billed quantities
  - the PO balance bar
  - the exact **rules that were applied** to this invoice
- **Invoice PDF:** the original document.
- **Audit trail:** every status change, with the time and who made it (*system*, *reviewer* or *user*), and any notes.

---

## 5. Working the Approvals queue

Open **Approvals**. Each card shows the reasons, the suggested next step, and the actions available.

| Tab | Actions |
|---|---|
| **Needs review** | **Override & approve** (a note is required, because you are overriding a control), **Reject** (note required), or **Re-run with current rules** (for example, after the missing goods receipt has been recorded or a tolerance has changed). |
| **Pending approval** | **Approve** (note optional) or **Reject** (note required). |
| **Failed** | **Retry now**. |

Approved invoices can then be marked **Paid** from the invoice page. Every action is recorded in the invoice's audit trail.

---

## 6. Rules and approval policy

Open **Rules & settings**. Click **Save changes** to apply.
- **New invoices** use the new rules straight away.
- **Existing invoices** keep the rules they were checked under. To re-check one, open it and click **Re-run with current rules**.
- **Restore defaults** returns every setting to its default.

### Approval policy
| Mode | Behaviour |
|---|---|
| **Autonomous** | Invoices that pass every control are approved for payment automatically, up to the **auto-approval limit** (default $25,000). Clean invoices above the limit go to *Pending approval*. Set the limit to 0 for no limit. |
| **Human-in-the-loop** | The system reads, matches and recommends, but every invoice waits in *Pending approval* for a person to sign off. |

In both modes:
- Invoices failing a **critical** control (a duplicate, or a blocked or unknown vendor) are rejected automatically.
- Any other exception goes to *Needs review*.

### Matching rules
| Setting | Default | Meaning |
|---|---|---|
| Unit price tolerance | 2% | An invoice unit price may be up to this much above the PO price. |
| Quantity tolerance | 0% | The total billed quantity (across all invoices on the PO) may exceed the ordered quantity by up to this much. |
| Amount tolerance (%) and (max $) | 2% / $500 | The total billed against a PO may exceed the PO value by this %, capped at this amount, whichever is lower. |
| Require a goods receipt (3-way match) | On | For goods POs, billed quantities must be covered by recorded goods receipts. Services POs are always 2-way. |
| Received quantity tolerance | 0% | The total billed may exceed the quantity received by up to this much. |
| Duplicate window | 10 days | Same vendor and same amount within this many days is flagged as a possible duplicate, even under a different invoice number. |
| Minimum reading confidence | 70% | If any key field was read with lower confidence, the invoice goes to review so someone can check it against the PDF. |

The settings page shows a live example of what your tolerances allow. For example: *"a $10,000 PO can be billed up to $10,200.00"*.

---

## 7. Try it with the sample invoices

The AP inbox comes with nine realistic vendor emails, so you can see each type of outcome. With the default settings you will see the following:

| Email | Result | What it demonstrates |
|---|---|---|
| Northwind **INV-NW-5512** | Approved (auto) | A clean invoice: PO number on the invoice, every line matches, goods fully received. |
| Brightline **BL-2026-0318** | Approved, with notes | The PO number appears only in the notes. The hourly rate is 1.6% above the PO, inside the 2% tolerance, so it's approved with a note rather than stopped. |
| Summit **SIP-88412** | Approved (auto) | Partial billing: the first of two shipments on one PO. |
| Summit **SIP-88497** | Needs review | The second shipment bills the full quantity again. Together the two invoices bill 120 of 100 kits ordered (and received), and run $1,020 over the PO. Each invoice looks fine on its own; the history catches it. |
| CloudNest **CN-42** (scanned reminder) | Rejected | A scanned "payment reminder" that is really invoice INV-CN-0042, already paid. It's recognised despite the different number format and the different file. |
| Greenleaf **GLF-10-2291** | Needs review | Matches its PO perfectly, but asks for payment to a **new bank account**, and the email came from a look-alike domain. This is the most common invoice-fraud pattern. Next action: verify by phone using the number on file. |
| Apex **APX-77031** (scanned) | Approved, with a note | A scanned invoice with no PO number and prices that include tax. The tax is separated out and the right PO is identified from the vendor's two open POs. |
| Quantum **QPS-3390** | Rejected | The vendor is blocked after a failed compliance review. |
| Northwind **INV-NW-5561** | Needs review | Bills 10 monitors, but the receiving team recorded only 8 (3-way match). |

**Things to try next:**
- In **Rules & settings**, switch to **Human-in-the-loop**, then process an invoice. It stops at *Pending approval* even though every control passes.
- Set **Received quantity tolerance** to 25%, open Northwind INV-NW-5561, and click **Re-run with current rules**. It now passes the 3-way match.
- Open Greenleaf in **Approvals**, then reject it with a note. Look at the **Audit trail**.
- Upload one of your own invoice PDFs. A vendor that isn't in the approved-vendor list is rejected as an unknown vendor, so add the vendor and a PO to the reference data first ([section 9](#9-your-reference-data)).

To start over, go to **Rules & settings → Demo tools → Reset demo data**. This clears all invoices, restores the PO ledger, and marks every inbox email as new. Your rules are kept.

The sample PDFs are also in the `demo-invoices/` folder if you want to try **Upload invoice**. An invoice that was already processed through the inbox will be rejected as a duplicate, which is correct.

---

## 8. When the AI service is busy

Free AI tiers limit how many requests you can make per minute, and are sometimes overloaded. Invoice Desk handles this for you:

- **One at a time:** invoices are processed one after another, not all at once, to stay within limits.
- **Backup models:** if the main model is busy, a backup model is tried. The *Extract fields* stage shows which model read the invoice.
- **Automatic retries:** if every model is busy, the invoice moves to **Waiting for AI** and retries automatically, waiting longer each time and never sooner than the provider asks. The invoice page shows a countdown, and you can click **Retry now** at any time.
- **Failed state:** after four attempts the invoice is marked **Failed** with a plain-English reason. Nothing is approved or paid. Click **Retry now** when the service is available.
- **Explanation fallback:** if only the explanation step is affected, a standard explanation is used instead. The decision is never affected.

---

## 9. Your reference data

The sample procurement data lives in `backend/data/`. These files are plain CSV/JSON, so you can edit them with a spreadsheet or text editor:

| File | Contents |
|---|---|
| `vendors.csv` | The approved-vendor list: name, aliases, tax ID, bank account on file, status (approved / blocked), payment terms, contact details. |
| `purchase_orders.csv` and `po_lines.csv` | Purchase orders and their lines. `match_type` is `3-way` for goods and `2-way` for services. |
| `goods_receipts.csv` | Goods receipts (GRNs): what was received against each PO, when, and by whom. |
| `invoice_history.csv` | Invoices already paid before Invoice Desk, used for duplicate detection and PO balances. |
| `inbox.json` | The sample AP-inbox emails. |

Changes to the CSV files are picked up immediately for new invoices.

---

## 10. FAQ and troubleshooting

**The page won't load.**
Make sure `./start.sh` is still running in a terminal, then open http://localhost:5173.

**The sidebar says "Backend unreachable".**
The backend isn't running. Restart with `./start.sh`.

**The sidebar says "Mock mode — no API key".**
No AI key was found. Add `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`) to `backend/.env` and restart.

**An invoice says the API key was rejected.**
Check the key in `backend/.env`, restart, then click **Retry now** on the invoice.

**Processing is slow.**
Free AI tiers vary. Expect roughly 10–60 seconds per invoice. Batches are processed one at a time.

**I uploaded a PDF and it was rejected as a duplicate.**
That exact invoice was already processed. This is the duplicate control working.

**I changed a rule but an invoice didn't change.**
Existing invoices keep the rules they were checked under, for auditability. Open the invoice and click **Re-run with current rules**.

**Can the AI approve something on its own judgement?**
No. The AI only reads the document. Approval is decided by the rules on the settings page and, depending on your policy, by a person.

**Which AI service is used?**
Set `LLM_PROVIDER` in `backend/.env`:
- `auto` (default): Claude if an Anthropic key is present, otherwise Gemini.
- `gemini` or `anthropic`: always that service.
- `mock`: offline demo mode, bundled samples only.

The Gemini model is set with `GEMINI_MODEL`, and its backups with `GEMINI_FALLBACK_MODELS`.

---

## 11. Scope of this version

This is a working prototype that runs on your own machine.
- The **AP inbox is simulated** with sample emails. Connecting a real mailbox (Microsoft 365, Gmail or IMAP) is a natural next step.
- **Approved invoices are not posted to an ERP**, and **no emails are sent.** Vendor emails are drafts for you to copy.
- **The data is sample data** stored in local files and a local database (`backend/storage/`).
- **Amounts are in USD.**
- **There are no user logins.** Actions are recorded as *reviewer* or *user*.
