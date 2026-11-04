# Invoice Desk: AP invoice processing, from PDF to decision

Invoice Desk takes vendor invoices (PDFs arriving by email or uploaded, typed or scanned) and turns each one into a clear, explained decision:
- **approved for payment**
- **sent to a person for review or approval**
- **rejected**

Every step is visible and every decision is audited.

**AI reads, rules decide.** An LLM (Google Gemini or Anthropic Claude) only *reads* the invoice into structured fields. Every check and every approval decision is made by deterministic rules that the finance team configures in the app.

📘 **[User guide](USER_GUIDE.md)** covers installation, a tour of every screen, statuses, rules, and a walkthrough with the included sample invoices.

## Quick start

Requires Python 3.9+ and Node.js 18+.

1. Install everything:
   ```bash
   ./setup.sh
   ```
2. Add `GEMINI_API_KEY` (free at https://aistudio.google.com) to `backend/.env`.
3. Start the app:
   ```bash
   ./start.sh
   ```
4. Open http://localhost:5173.

Without an API key the app runs in demo mode, which can read only the bundled sample invoices.

## What it does

- **AP inbox:** vendor emails with invoice attachments. Process one email or all new ones, or upload a PDF.
- **9-stage pipeline:** ingest → read → extract → validate → vendor match → **PO match (2-way)** → **goods-receipt match (3-way)** → business rules → decision. Every stage streams live and shows its evidence.
- **Controls:**
  - price, quantity and amount tolerances
  - cumulative PO balance across split invoices
  - received-quantity check
  - duplicate detection (including rescans and renumbered resubmissions)
  - changed bank details and look-alike sender domains
  - blocked or unknown vendors
  - arithmetic and tax checks
  - reading confidence
- **Configurable policy:** edit tolerances in the UI. Choose *Autonomous* (auto-approve clean invoices up to a limit) or *Human-in-the-loop* (every invoice needs sign-off). Each invoice records the rules it was evaluated under, and can be re-run under new rules.
- **Invoice lifecycle:** Queued → Processing → Approved / Pending approval / Needs review / Rejected → Paid, plus *Waiting for AI* and *Failed*. Every change is in the audit trail.
- **Resilient AI usage:**
  - one invoice at a time
  - backup models
  - automatic retries with backoff that respect the provider's limits
  - a clear *Failed* state with **Retry now**; nothing is ever approved on a failed read

## Project layout

| Path | Contents |
|---|---|
| `backend/app/pipeline.py` | Stages, matching, rules, decision and lifecycle |
| `backend/app/settings.py` | Matching rules and approval policy (stored in SQLite) |
| `backend/app/jobs.py` | Processing queue and retry scheduler |
| `backend/app/extract.py` | PDF reading and AI extraction (Gemini / Claude, structured JSON) |
| `backend/app/main.py` | REST API and live updates (server-sent events) |
| `backend/data/` | Sample procurement data: vendors, POs, goods receipts, paid-invoice history, inbox emails |
| `backend/samples/`, `demo-invoices/` | Sample invoice PDFs. Regenerate with `backend/.venv/bin/python backend/scripts/generate_invoices.py` |
| `frontend/src/` | React web app: dashboard, AP inbox, invoice page, approvals, reference data, settings |

**Tech stack:**
- **Backend:** Python, FastAPI, SQLite, pdfplumber / PyMuPDF.
- **Frontend:** React, Vite, Tailwind CSS.
- **AI:** Google Gemini or Anthropic Claude.
