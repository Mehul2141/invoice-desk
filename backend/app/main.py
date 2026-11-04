import asyncio
import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, jobs, pipeline, refdata, settings
from .config import FRONTEND_DIST, SAMPLES_DIR, UPLOAD_DIR, llm_enabled, provider, provider_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Invoice Desk — AP automation")
db.init_db()


@app.on_event("startup")
def _startup():
    jobs.start()


def _queue(filename, path, source, source_ref=None, sender=None):
    run_id = pipeline.create_run(filename, path, source, source_ref, sender)
    jobs.enqueue(run_id)
    return run_id


def _run_payload(run_id):
    run = db.query_one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        return None
    run["result"] = json.loads(run.pop("result_json") or "null")
    run["rules"] = json.loads(run.pop("rules_json") or "null")
    run["status_label"] = pipeline.STATUSES.get(run["status"], run["status"])
    run["queue_position"] = jobs.queue_position(run_id) if run["status"] == "queued" else 0
    stages = db.query("SELECT * FROM stages WHERE run_id=? ORDER BY idx", (run_id,))
    for s in stages:
        s["detail"] = json.loads(s.pop("detail_json") or "null")
    run["stages"] = stages
    run["events"] = db.query("SELECT * FROM events WHERE run_id=? ORDER BY id", (run_id,))
    if run["source_ref"]:
        run["email"] = db.query_one("SELECT id, from_name, from_email, subject, received_at FROM inbox WHERE id=?",
                                    (run["source_ref"],))
    run.pop("file_path", None)
    return run


def _bad(e: Exception, code=400):
    raise HTTPException(code, str(e))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True, "llm_enabled": llm_enabled(), "provider": provider(),
            "model": provider_model() if llm_enabled() else None}


# ---------------------------------------------------------------------------
# Intake: AP inbox + manual upload
# ---------------------------------------------------------------------------

@app.get("/api/inbox")
def inbox():
    rows = db.query("""SELECT i.*, r.status AS run_status, r.headline AS run_headline FROM inbox i
                       LEFT JOIN runs r ON r.id = i.run_id ORDER BY i.received_at DESC""")
    for r in rows:
        r.pop("sample_file", None)
        r["run_status_label"] = pipeline.STATUSES.get(r["run_status"]) if r["run_status"] else None
    return rows


@app.get("/api/inbox/{msg_id}/attachment")
def inbox_attachment(msg_id: str):
    m = db.query_one("SELECT sample_file, attachment FROM inbox WHERE id=?", (msg_id,))
    if not m:
        raise HTTPException(404)
    return FileResponse(SAMPLES_DIR / m["sample_file"], media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{m["attachment"]}"'})


def _process_message(m):
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.pdf"
    shutil.copy(SAMPLES_DIR / m["sample_file"], dest)
    run_id = _queue(m["attachment"], dest, "email", m["id"], m["from_email"])
    db.execute("UPDATE inbox SET run_id=? WHERE id=?", (run_id, m["id"]))
    return run_id


@app.post("/api/inbox/{msg_id}/process")
def process_message(msg_id: str):
    m = db.query_one("SELECT * FROM inbox WHERE id=?", (msg_id,))
    if not m:
        raise HTTPException(404, "Message not found")
    if m["run_id"]:
        raise HTTPException(409, f"This email was already processed as invoice #{m['run_id']}.")
    return {"run_id": _process_message(m)}


@app.post("/api/inbox/process-all")
def process_all():
    new = db.query("SELECT * FROM inbox WHERE run_id IS NULL ORDER BY received_at")
    return {"run_ids": [_process_message(m) for m in new]}


@app.post("/api/runs")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF invoice.")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.pdf"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    if dest.read_bytes()[:5] != b"%PDF-":
        dest.unlink()
        raise HTTPException(400, "That file is not a valid PDF.")
    return {"run_id": _queue(file.filename, dest, "upload")}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@app.get("/api/runs")
def list_runs():
    rows = db.query(
        """SELECT id, created_at, updated_at, finished_at, filename, source, sender_email, extraction_mode, status,
                  decision, approved_by, vendor_id, vendor_name, invoice_number, invoice_date, due_date, total,
                  currency, po_number, headline, duration_ms, attempts, next_retry_at, error
           FROM runs ORDER BY id DESC""")
    for r in rows:
        r["status_label"] = pipeline.STATUSES.get(r["status"], r["status"])
    return rows


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = _run_payload(run_id)
    if not run:
        raise HTTPException(404)
    return run


@app.get("/api/runs/{run_id}/file")
def run_file(run_id: int):
    run = db.query_one("SELECT file_path FROM runs WHERE id=?", (run_id,))
    if not run or not Path(run["file_path"]).exists():
        raise HTTPException(404)
    return FileResponse(run["file_path"], media_type="application/pdf")


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: int):
    """Server-sent events: pushes a snapshot of the invoice whenever anything changes."""
    if not db.query_one("SELECT id FROM runs WHERE id=?", (run_id,)):
        raise HTTPException(404)

    async def gen():
        last = None
        while True:
            run = _run_payload(run_id)
            body = json.dumps(run, default=str)
            if body != last:
                last = body
                yield f"event: snapshot\ndata: {body}\n\n"
            if run["status"] not in pipeline.ACTIVE_STATUSES:
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.3)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Action(BaseModel):
    action: str  # approve | reject | mark_paid
    note: str = ""


@app.post("/api/runs/{run_id}/action")
def run_action(run_id: int, body: Action):
    try:
        pipeline.human_action(run_id, body.action, body.note)
    except LookupError as e:
        _bad(e, 404)
    except ValueError as e:
        _bad(e)
    return _run_payload(run_id)


@app.post("/api/runs/{run_id}/reprocess")
def run_reprocess(run_id: int):
    try:
        pipeline.reprocess(run_id)
    except LookupError as e:
        _bad(e, 404)
    except ValueError as e:
        _bad(e)
    jobs.enqueue(run_id)
    return _run_payload(run_id)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return {"values": settings.get(), "defaults": settings.DEFAULTS}


@app.put("/api/settings")
def put_settings(changes: dict):
    try:
        return {"values": settings.update(changes), "defaults": settings.DEFAULTS}
    except ValueError as e:
        _bad(e)


@app.post("/api/settings/reset")
def reset_settings():
    return {"values": settings.restore_defaults(), "defaults": settings.DEFAULTS}


# ---------------------------------------------------------------------------
# Dashboard + reference data
# ---------------------------------------------------------------------------

@app.get("/api/stats")
def stats():
    runs = db.query("SELECT * FROM runs")
    by = {s: [r for r in runs if r["status"] == s] for s in pipeline.STATUSES}
    decided = [r for r in runs if r["decision"]]
    auto = [r for r in decided if r["approved_by"] == "system"]
    durations = [r["duration_ms"] for r in decided if r["duration_ms"]]
    total = lambda rows: round(sum(r["total"] or 0 for r in rows), 2)
    return {
        "received": len(runs),
        "counts": {s: len(v) for s, v in by.items()},
        "in_progress": sum(len(by[s]) for s in pipeline.ACTIVE_STATUSES),
        "decided": len(decided),
        "touchless": len(auto),
        "touchless_rate": round(len(auto) / len(decided) * 100) if decided else None,
        "awaiting_human": len(by["needs_review"]) + len(by["pending_approval"]),
        "value_approved": total(by["approved"] + by["paid"]),
        "value_paid": total(by["paid"]),
        "value_blocked": total(by["rejected"] + by["needs_review"]),
        "value_pending": total(by["pending_approval"]),
        "avg_duration_ms": int(sum(durations) / len(durations)) if durations else None,
    }


@app.get("/api/vendors")
def vendors():
    out = []
    for v in refdata.vendors():
        v = dict(v)
        v["bank_account"] = pipeline.mask(v["bank_account"])
        out.append(v)
    return out


@app.get("/api/purchase-orders")
def purchase_orders():
    return refdata.purchase_orders_with_balance()


@app.get("/api/goods-receipts")
def goods_receipts():
    return refdata.goods_receipts()


@app.get("/api/ledger")
def ledger():
    return db.query("SELECT * FROM ledger ORDER BY id DESC")


@app.post("/api/demo/reset")
def demo_reset():
    if db.query_one("SELECT id FROM runs WHERE status IN ('processing')"):
        raise HTTPException(409, "Wait for the invoice that is processing to finish before resetting.")
    db.reset_db()
    for f in UPLOAD_DIR.glob("*.pdf"):
        f.unlink()
    return {"ok": True}


# Serve the built frontend (production / single-process mode)
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        target = FRONTEND_DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
