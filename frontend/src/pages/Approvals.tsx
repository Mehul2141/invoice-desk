import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { api, money, timeAgo, type Run } from "../api";
import { Card, Empty, StatusChip, StatusIcon, cx } from "../components/ui";
import ActionPanel from "../components/ActionPanel";
import { PageHeader } from "../App";

type Tab = "needs_review" | "pending_approval" | "failed";

const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "needs_review", label: "Needs review", hint: "A control raised an exception. Overriding requires a note." },
  { key: "pending_approval", label: "Pending approval", hint: "Every control passed — waiting for sign-off (human-in-the-loop mode or above the auto-approval limit)." },
  { key: "failed", label: "Failed", hint: "The document could not be read. Retry once the AI service is available." },
];

export default function Approvals() {
  const [items, setItems] = useState<Run[] | null>(null);
  const [counts, setCounts] = useState<Record<Tab, number>>({ needs_review: 0, pending_approval: 0, failed: 0 });
  const [tab, setTab] = useState<Tab>("needs_review");

  const load = async () => {
    const runs = await api.runs();
    setCounts({
      needs_review: runs.filter((r) => r.status === "needs_review").length,
      pending_approval: runs.filter((r) => r.status === "pending_approval").length,
      failed: runs.filter((r) => r.status === "failed").length,
    });
    const mine = runs.filter((r) => r.status === tab);
    setItems(await Promise.all(mine.map((r) => api.run(r.id))));
  };

  useEffect(() => {
    setItems(null);
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const current = TABS.find((t) => t.key === tab)!;

  return (
    <div>
      <PageHeader title="Approvals" subtitle="Everything waiting for a person. Each decision is recorded in the invoice’s audit trail." />
      <div className="space-y-4 px-4 py-6 sm:px-8">
        <div className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={cx("rounded-md px-3 py-1.5 text-sm font-medium", tab === t.key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100")}>
              {t.label} <span className="ml-1 opacity-70">{counts[t.key]}</span>
            </button>
          ))}
        </div>
        <p className="text-sm text-slate-500">{current.hint}</p>

        {items == null ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : items.length === 0 ? (
          <Card><Empty icon={<CheckCircle2 className="h-10 w-10" />} title={`Nothing in “${current.label}”`}>You’re all caught up.</Empty></Card>
        ) : (
          items.map((run) => (
            <Card key={run.id} className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <StatusChip status={run.status} />
                    <span>#{run.id} · {timeAgo(run.updated_at || run.created_at)} · {run.vendor_name ?? run.filename}
                      {run.invoice_number && <> · <span className="font-mono">{run.invoice_number}</span></>}
                      {run.total != null && <> · {money(run.total, run.currency || "USD")}</>}
                      {run.po_number && <> · {run.po_number}</>}</span>
                  </div>
                  <h3 className="mt-1.5 font-semibold text-slate-900">{run.status === "failed" ? run.error : run.result?.headline}</h3>
                </div>
                <Link to={`/runs/${run.id}`} className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline">
                  Open invoice <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
              <div className="mt-3 grid gap-4 lg:grid-cols-2">
                <div>
                  {run.result && (
                    <ul className="space-y-1.5">
                      {run.result.reasons.filter((c) => c.severity !== "low").map((c) => (
                        <li key={c.id} className="flex gap-2 text-sm text-slate-700">
                          <StatusIcon status={c.status} className="mt-0.5 h-4 w-4 shrink-0" /> {c.message}
                        </li>
                      ))}
                      {run.status === "pending_approval" && (
                        <li className="text-sm text-slate-600">All controls passed — {run.result.status_reason}.</li>
                      )}
                    </ul>
                  )}
                  {run.result && (
                    <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700"><b>Suggested next step:</b> {run.result.next_action}</p>
                  )}
                </div>
                <ActionPanel run={run} onDone={() => load()} />
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
