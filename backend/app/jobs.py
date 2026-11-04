"""Processing queue.

Invoices are processed one at a time by a single worker. That keeps the LLM call rate
inside free-tier limits when a whole inbox is processed at once. A scheduler re-queues
runs whose automatic retry (after a rate limit or overload) has come due.
"""
import logging
import queue
import threading
import time

from . import db

log = logging.getLogger("jobs")

_q: "queue.Queue[int]" = queue.Queue()
_started = False


def enqueue(run_id: int):
    _q.put(run_id)


def queue_position(run_id: int) -> int:
    """1-based position among queued runs (0 if not queued)."""
    queued = [r["id"] for r in db.query("SELECT id FROM runs WHERE status='queued' ORDER BY updated_at, id")]
    return queued.index(run_id) + 1 if run_id in queued else 0


def _worker():
    from . import pipeline
    while True:
        run_id = _q.get()
        try:
            run = db.query_one("SELECT status FROM runs WHERE id=?", (run_id,))
            if run and run["status"] == "queued":
                pipeline.run_pipeline(run_id)
        except Exception:
            log.exception("worker crashed on run %s", run_id)
        finally:
            _q.task_done()


def _scheduler():
    from . import pipeline
    while True:
        time.sleep(1)
        try:
            due = db.query("SELECT id FROM runs WHERE status='waiting_retry' AND next_retry_at <= ?", (db.now_iso(),))
            for r in due:
                pipeline.set_status(r["id"], "queued", "system", "Automatic retry")
                enqueue(r["id"])
        except Exception:
            log.exception("scheduler error")


def start():
    global _started
    if _started:
        return
    _started = True
    # Recover runs interrupted by a restart.
    from . import pipeline
    for r in db.query("SELECT id, status FROM runs WHERE status IN ('queued','processing') ORDER BY id"):
        if r["status"] == "processing":
            pipeline.set_status(r["id"], "queued", "system", "Re-queued after server restart")
        enqueue(r["id"])
    threading.Thread(target=_worker, daemon=True, name="invoice-worker").start()
    threading.Thread(target=_scheduler, daemon=True, name="retry-scheduler").start()
