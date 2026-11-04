import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Bot, Clock, FileSearch, FileText, Flag, History, Mail, RotateCw, ServerCrash, UserCheck } from "lucide-react";
import { ACTIVE_STATUSES, api, duration, money, PROVIDER_LABEL, type Run } from "../api";
import { Card, DECISION_STYLE, DecisionChip, StatusChip, StatusIcon, cx } from "../components/ui";
import StageDetail from "../components/StageDetail";
import ActionPanel from "../components/ActionPanel";

export default function RunView() {
  const { id } = useParams();
  const [run, setRun] = useState<Run | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [tab, setTab] = useState<"stage" | "pdf" | "audit">("stage");
  const [now, setNow] = useState(Date.now());
  const [streamKey, setStreamKey] = useState(0);
  const follow = useRef(true);
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    follow.current = true;
    const es = new EventSource(`/api/runs/${id}/events`);
    es.addEventListener("snapshot", (e) => setRun(JSON.parse((e as MessageEvent).data)));
    es.addEventListener("done", () => es.close());
    es.onerror = () => es.close();
    return () => es.close();
  }, [id, streamKey]);

  useEffect(() => {
    setSelected(null);
    setRun(null);
    setTab("stage");
  }, [id]);

  // Follow the active stage while processing; land on the last meaningful stage when finished.
  useEffect(() => {
    if (!run || !follow.current) return;
    const active = run.stages.find((s) => s.status === "running" || s.status === "waiting" || s.status === "error");
    if (active) setSelected(active.idx);
    else if (!ACTIVE_STATUSES.includes(run.status)) {
      const last = [...run.stages].reverse().find((s) => !["pending", "skipped"].includes(s.status));
      setSelected(last ? last.idx : 0);
    }
  }, [run]);

  useEffect(() => {
    if (!run || !ACTIVE_STATUSES.includes(run.status)) return;
    const t = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(t);
  }, [run?.status]);

  const onAction = (r: Run) => {
    setRun(r);
    if (ACTIVE_STATUSES.includes(r.status)) {
      follow.current = true;
      setStreamKey((k) => k + 1);
    }
  };

  if (!run) return <div className="p-8 text-sm text-slate-500">Loading invoice…</div>;

  const done = run.stages.filter((s) => !["pending", "running", "waiting"].includes(s.status)).length;
  const active = ACTIVE_STATUSES.includes(run.status);
  const elapsed = run.status === "processing" && run.started_at ? now - new Date(run.started_at).getTime() : run.duration_ms;
  const stage = run.stages.find((s) => s.idx === selected) ?? run.stages[0];
  const result = run.result;
  const retryIn = run.next_retry_at ? Math.max(0, Math.ceil((new Date(run.next_retry_at).getTime() - now) / 1000)) : null;

  return (
    <div>
      <div className="border-b border-slate-200 bg-white px-4 py-4 sm:px-8">
        <Link to="/" className="mb-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-indigo-600">
          <ArrowLeft className="h-3 w-3" /> Dashboard
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-slate-900">
              Invoice #{run.id}
              {run.invoice_number && <span className="font-normal text-slate-500"> · {run.invoice_number}</span>}
              {run.vendor_name && <span className="font-normal text-slate-500"> · {run.vendor_name}</span>}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
              {run.email ? (
                <span className="inline-flex items-center gap-1"><Mail className="h-3.5 w-3.5" /> “{run.email.subject}” from {run.email.from_email}</span>
              ) : (
                <span className="inline-flex items-center gap-1"><FileText className="h-3.5 w-3.5" /> Uploaded {run.filename}</span>
              )}
              <span className="inline-flex items-center gap-1"><Bot className="h-3.5 w-3.5" />
                {run.extraction_mode ? `${PROVIDER_LABEL[run.extraction_mode]} extraction` : "Not read yet"}</span>
              {elapsed != null && <span>{duration(elapsed)}</span>}
              {run.attempts > 1 && <span>attempt {run.attempts}</span>}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {run.status === "queued" && run.queue_position > 0 && (
              <span className="text-xs text-slate-500">#{run.queue_position} in queue</span>
            )}
            {run.status === "processing" && <span className="text-xs text-slate-500">stage {Math.min(done + 1, run.stages.length)} of {run.stages.length}</span>}
            <StatusChip status={run.status} size="lg" />
          </div>
        </div>
        <div className="mt-4 h-1 overflow-hidden rounded-full bg-slate-100">
          <div className={cx("h-full rounded-full transition-all duration-500",
            run.status === "failed" ? "bg-rose-500" : run.status === "waiting_retry" ? "bg-sky-500" : active ? "bg-indigo-500" : "bg-emerald-500")}
            style={{ width: `${(done / run.stages.length) * 100}%` }} />
        </div>
      </div>

      <div className="space-y-6 px-4 py-6 sm:px-8">
        {run.status === "waiting_retry" && (
          <div className="fade-in flex flex-wrap items-center justify-between gap-4 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4">
            <div className="flex gap-3">
              <Clock className="mt-0.5 h-5 w-5 shrink-0 text-sky-600" />
              <div className="text-sm text-sky-900">
                <div className="font-semibold">The AI service is busy — this invoice will retry automatically.</div>
                <div className="mt-0.5">{run.error} Next attempt ({run.attempts + 1} of 4){retryIn != null ? ` in ${retryIn}s` : ""}. Nothing is lost; other invoices keep their place in the queue.</div>
              </div>
            </div>
            <ActionPanel run={run} onDone={onAction} compact />
          </div>
        )}

        {run.status === "failed" && (
          <div className="fade-in rounded-xl border border-rose-200 bg-rose-50 px-5 py-4">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex gap-3">
                <ServerCrash className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
                <div className="text-sm text-rose-900">
                  <div className="font-semibold">This invoice could not be read, so no decision was made.</div>
                  <div className="mt-0.5">{run.error}</div>
                  <div className="mt-1 text-rose-700">Nothing was approved or paid. Retry once the service is available, or process the invoice manually.</div>
                  {run.error_detail && (
                    <details className="mt-2 text-xs text-rose-700">
                      <summary className="cursor-pointer">Technical detail</summary>
                      <code className="mt-1 block whitespace-pre-wrap break-words">{run.error_detail}</code>
                    </details>
                  )}
                </div>
              </div>
              <ActionPanel run={run} onDone={onAction} compact />
            </div>
          </div>
        )}

        {result && !active && run.status !== "failed" && <DecisionBanner run={run} onAction={onAction} />}

        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <Card className="h-fit p-2 lg:sticky lg:top-4">
            <ol>
              {run.stages.map((s, i) => (
                <li key={s.idx}>
                  <button
                    onClick={() => {
                      follow.current = false;
                      setSelected(s.idx);
                      setTab("stage");
                      const top = detailRef.current?.getBoundingClientRect().top ?? 0;
                      if (top < 0 || top > window.innerHeight * 0.6) detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
                    }}
                    className={cx("group flex w-full gap-3 rounded-lg px-3 py-2.5 text-left transition",
                      s.idx === stage.idx && tab === "stage" ? "bg-indigo-50/70" : "hover:bg-slate-50")}>
                    <div className="flex flex-col items-center">
                      <div className={cx("grid h-7 w-7 place-items-center rounded-full bg-white", s.status === "running" && "pulse-ring")}>
                        <StatusIcon status={s.status} className="h-5.5 w-5.5" />
                      </div>
                      {i < run.stages.length - 1 && (
                        <div className={cx("mt-1 w-px flex-1", ["pending", "running", "skipped", "waiting"].includes(s.status) ? "bg-slate-200" : "bg-slate-300")} />
                      )}
                    </div>
                    <div className="min-w-0 flex-1 pb-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className={cx("text-sm font-medium", s.status === "pending" || s.status === "skipped" ? "text-slate-400" : "text-slate-800")}>
                          {i + 1}. {s.name}
                        </span>
                        <span className="shrink-0 text-[11px] tabular-nums text-slate-400">
                          {s.status === "waiting" ? "retrying" : s.duration_ms != null ? duration(s.duration_ms) : s.status === "running" ? "…" : ""}
                        </span>
                      </div>
                      {s.summary && <p className={cx("mt-0.5 line-clamp-2 text-xs", s.status === "error" ? "text-rose-600" : "text-slate-500")}>{s.summary}</p>}
                    </div>
                  </button>
                </li>
              ))}
            </ol>
          </Card>

          <div ref={detailRef} className="min-w-0 scroll-mt-4">
            <Card className="min-w-0">
              <div className="flex flex-wrap items-center gap-1 border-b border-slate-100 px-3 pt-2">
                {([["stage", `Stage ${stage.idx + 1}: ${stage.name}`, FileSearch], ["pdf", "Invoice PDF", FileText],
                  ["audit", `Audit trail (${run.events.length})`, History]] as const).map(([k, label, Icon]) => (
                  <button key={k} onClick={() => setTab(k)}
                    className={cx("-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium",
                      tab === k ? "border-indigo-600 text-indigo-700" : "border-transparent text-slate-500 hover:text-slate-800")}>
                    <Icon className="h-4 w-4" /> {label}
                  </button>
                ))}
              </div>
              <div className="p-5">
                {tab === "pdf" ? (
                  <iframe title="invoice" src={`/api/runs/${run.id}/file#view=FitH`} className="h-[75vh] w-full rounded-lg border border-slate-200" />
                ) : tab === "audit" ? (
                  <Timeline run={run} />
                ) : (
                  <div key={stage.idx} className="fade-in">
                    <StageDetail stage={stage} runId={run.id} />
                  </div>
                )}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function DecisionBanner({ run, onAction }: { run: Run; onAction: (r: Run) => void }) {
  const r = run.result!;
  const style = DECISION_STYLE[r.decision];
  const blocking = r.reasons.filter((c) => c.severity === "high" || c.severity === "critical");
  const notes = r.reasons.filter((c) => c.severity === "low");
  const lastHuman = [...run.events].reverse().find((e) => e.actor !== "system" && e.status);
  return (
    <div className={cx("fade-in rounded-xl border bg-gradient-to-br p-5 shadow-sm", style.banner)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <StatusChip status={run.status} size="lg" />
            <span className="text-xs text-slate-500">System recommendation:</span>
            <DecisionChip decision={r.decision} />
            <span className="text-xs text-slate-500">
              · {r.check_counts.pass} passed · {r.check_counts.warn} warnings · {r.check_counts.fail} failed
            </span>
          </div>
          <h2 className="text-lg font-semibold text-slate-900">{r.headline}</h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-700">{r.explanation}</p>
          {lastHuman && (
            <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-white px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200">
              <UserCheck className="h-3.5 w-3.5" /> {lastHuman.actor === "reviewer" ? "Reviewer" : "User"} set {lastHuman.status?.replace("_", " ")}: “{lastHuman.note}”
            </p>
          )}
          <p className="mt-1 text-[11px] text-slate-400">
            Decision by rules engine ({r.status_reason}) · explanation by {PROVIDER_LABEL[r.narrative_source] ?? r.narrative_source}
          </p>
        </div>
        <div className="grid shrink-0 grid-cols-2 gap-x-6 gap-y-1 text-sm">
          <span className="text-slate-500">Vendor</span><span className="font-medium">{run.vendor_name ?? "—"}</span>
          <span className="text-slate-500">Invoice</span><span className="font-mono text-xs leading-5">{run.invoice_number ?? "—"}</span>
          <span className="text-slate-500">PO</span><span className="font-mono text-xs leading-5">{run.po_number ?? "—"}</span>
          <span className="text-slate-500">Total</span><span className="font-medium tabular-nums">{money(run.total, run.currency || "USD")}</span>
          <span className="text-slate-500">Due</span><span className="tabular-nums">{run.due_date ?? "—"}</span>
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          {!["paid", "rejected"].includes(run.status) && (
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <Flag className="h-3.5 w-3.5" /> Next action
              </div>
              <p className="text-sm text-slate-800">{run.status === "approved" && run.approved_by === "reviewer"
                ? "Approved by reviewer — include in the next payment run." : r.next_action}</p>
            </div>
          )}
          {(blocking.length > 0 || notes.length > 0) && (
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Why</div>
              <ul className="space-y-1.5">
                {[...blocking, ...notes].map((c) => (
                  <li key={c.id} className="flex gap-2 text-sm">
                    <StatusIcon status={c.status} className="mt-0.5 h-4 w-4 shrink-0" />
                    <span className={c.severity === "low" ? "text-slate-500" : "text-slate-800"}>{c.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="space-y-3">
          <ActionPanel run={run} onDone={onAction} />
          {r.vendor_email && ["needs_review", "rejected"].includes(run.status) && (
            <div className="rounded-lg border border-slate-200 bg-white p-3">
              <div className="mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Mail className="h-3.5 w-3.5" /> Draft email to vendor
                </span>
                <button onClick={() => navigator.clipboard.writeText(r.vendor_email!)} className="text-xs text-indigo-600 hover:underline">Copy</button>
              </div>
              <pre className="whitespace-pre-wrap font-sans text-sm text-slate-700">{r.vendor_email}</pre>
              <p className="mt-2 text-[11px] text-slate-400">Draft only — nothing is sent automatically.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Timeline({ run }: { run: Run }) {
  const actorStyle = { system: "bg-slate-100 text-slate-600", reviewer: "bg-amber-100 text-amber-800", user: "bg-indigo-100 text-indigo-700" };
  return (
    <ol className="relative space-y-4 border-l border-slate-200 pl-6">
      {run.events.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[29px] top-1 grid h-4 w-4 place-items-center rounded-full bg-white ring-2 ring-slate-200">
            {e.status === "queued" && e.actor === "user" ? <RotateCw className="h-2.5 w-2.5 text-indigo-500" /> : <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />}
          </span>
          <div className="flex flex-wrap items-center gap-2">
            {e.status && <StatusChip status={e.status} />}
            <span className={cx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", actorStyle[e.actor])}>{e.actor}</span>
            <span className="text-xs text-slate-400">{new Date(e.at).toLocaleString()}</span>
          </div>
          {e.note && <p className="mt-1 text-sm text-slate-700">{e.note}</p>}
        </li>
      ))}
    </ol>
  );
}
