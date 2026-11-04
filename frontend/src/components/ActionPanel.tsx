import { useState } from "react";
import { Banknote, Check, RotateCw, X } from "lucide-react";
import { api, type Run } from "../api";
import { Button, cx } from "./ui";

/** Human actions available for an invoice in its current status. */
export default function ActionPanel({ run, onDone, compact }: { run: Run; onDone: (r: Run) => void; compact?: boolean }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = async (fn: () => Promise<Run>) => {
    setBusy(true);
    setErr(null);
    try {
      onDone(await fn());
      setNote("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const s = run.status;
  const reviewing = s === "needs_review" || s === "pending_approval";
  const rerun = ["needs_review", "pending_approval", "rejected", "failed", "waiting_retry"].includes(s);
  if (!reviewing && !rerun && s !== "approved") return null;

  const title = {
    needs_review: "Exception — your decision",
    pending_approval: "Awaiting your approval",
    approved: "Payment",
    failed: "Processing failed",
    waiting_retry: "Waiting for the AI service",
    rejected: "Rejected",
  }[s as string];

  return (
    <div className={cx("rounded-lg border bg-white p-3",
      s === "needs_review" ? "border-amber-200" : s === "pending_approval" ? "border-violet-200" : "border-slate-200")}>
      {!compact && title && <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</div>}
      {reviewing && (
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
          placeholder={s === "needs_review"
            ? "Note (required) — e.g. 'Called vendor on file number; bank change confirmed by J. Smith'"
            : "Note (optional for approval, required to reject)"}
          className="mb-2 w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100" />
      )}
      {err && <p className="mb-2 text-xs text-rose-600">{err}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {rerun && (
          <Button variant="ghost" onClick={() => go(() => api.reprocess(run.id))} disabled={busy}
            className={s === "failed" || s === "waiting_retry" ? "!bg-indigo-600 !text-white hover:!bg-indigo-500" : ""}>
            <RotateCw className="h-4 w-4" /> {s === "failed" || s === "waiting_retry" ? "Retry now" : "Re-run with current rules"}
          </Button>
        )}
        {reviewing && (
          <>
            <Button variant="secondary" onClick={() => go(() => api.action(run.id, "reject", note))} disabled={busy || !note.trim()}>
              <X className="h-4 w-4" /> Reject
            </Button>
            <Button variant="success" onClick={() => go(() => api.action(run.id, "approve", note))}
              disabled={busy || (s === "needs_review" && !note.trim())}>
              <Check className="h-4 w-4" /> {s === "needs_review" ? "Override & approve" : "Approve"}
            </Button>
          </>
        )}
        {s === "approved" && (
          <Button variant="secondary" onClick={() => go(() => api.action(run.id, "mark_paid"))} disabled={busy}>
            <Banknote className="h-4 w-4" /> Mark as paid
          </Button>
        )}
      </div>
    </div>
  );
}
