import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Clock, FileStack, Inbox, ShieldCheck, ShieldX, Sparkles, UserCheck } from "lucide-react";
import { api, duration, money, timeAgo, type InvoiceStatus, type RunSummary, type Stats } from "../api";
import { Button, Card, DecisionChip, Empty, STATUS_STYLE, StatusChip, cx } from "../components/ui";
import { PageHeader } from "../App";

const LIFECYCLE: InvoiceStatus[] = ["queued", "processing", "waiting_retry", "needs_review", "pending_approval", "approved", "paid", "rejected", "failed"];

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [filter, setFilter] = useState<InvoiceStatus | "all">("all");
  const [q, setQ] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    let alive = true;
    const load = () => Promise.all([api.stats(), api.runs()]).then(([s, r]) => {
      if (!alive) return;
      setStats(s);
      setRuns(r);
    }).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const shown = runs.filter((r) => {
    if (filter !== "all" && r.status !== filter) return false;
    if (q) {
      const hay = `${r.vendor_name} ${r.invoice_number} ${r.po_number} ${r.filename} ${r.sender_email}`.toLowerCase();
      if (!hay.includes(q.toLowerCase())) return false;
    }
    return true;
  });

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Every invoice received, where it is in its journey, and why."
        right={<Link to="/inbox"><Button><Inbox className="h-4 w-4" /> Go to AP inbox</Button></Link>} />
      <div className="space-y-6 px-4 py-6 sm:px-8">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-6">
          <Kpi icon={<FileStack />} label="Invoices received" value={stats?.received ?? "—"} sub={stats ? `${stats.in_progress} in progress` : ""} />
          <Kpi icon={<Sparkles />} label="Touchless rate" value={stats?.touchless_rate == null ? "—" : `${stats.touchless_rate}%`}
            sub={stats ? `${stats.touchless} of ${stats.decided} approved with no human touch` : ""} tone="indigo" />
          <Kpi icon={<UserCheck />} label="Awaiting a person" value={stats?.awaiting_human ?? "—"}
            sub={stats ? `${stats.counts.needs_review} exceptions · ${stats.counts.pending_approval} approvals` : ""} tone="amber" onClick={() => nav("/approvals")} />
          <Kpi icon={<ShieldCheck />} label="Approved for payment" value={stats ? money(stats.value_approved) : "—"}
            sub={stats ? `${money(stats.value_paid)} paid` : ""} tone="emerald" />
          <Kpi icon={<ShieldX />} label="Stopped before payment" value={stats ? money(stats.value_blocked) : "—"}
            sub={stats ? `${stats.counts.rejected} rejected · ${stats.counts.needs_review} in review` : ""} tone="rose" />
          <Kpi icon={<Clock />} label="Avg. processing time" value={duration(stats?.avg_duration_ms)} sub="email → decision" />
        </div>

        <Card className="p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Invoice lifecycle</div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => setFilter("all")}
              className={cx("rounded-lg border px-3 py-2 text-left transition", filter === "all" ? "border-slate-900 bg-slate-900 text-white" : "border-slate-200 hover:border-slate-300")}>
              <div className="text-lg font-semibold tabular-nums">{runs.length}</div>
              <div className="text-xs opacity-80">All</div>
            </button>
            {LIFECYCLE.map((s) => (
              <button key={s} onClick={() => setFilter(filter === s ? "all" : s)}
                className={cx("min-w-[104px] rounded-lg border px-3 py-2 text-left transition",
                  filter === s ? "border-indigo-500 bg-indigo-50" : "border-slate-200 hover:border-slate-300",
                  !stats?.counts[s] && filter !== s && "opacity-50")}>
                <div className="text-lg font-semibold tabular-nums text-slate-900">{stats?.counts[s] ?? 0}</div>
                <div className="flex items-center gap-1.5 text-xs text-slate-600">
                  <span className={cx("h-1.5 w-1.5 rounded-full", STATUS_STYLE[s].dot)} /> {STATUS_STYLE[s].label}
                </div>
              </button>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <div className="text-sm font-medium text-slate-700">
              {filter === "all" ? "All invoices" : STATUS_STYLE[filter].label} <span className="text-slate-400">({shown.length})</span>
            </div>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search vendor, invoice, PO…"
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 sm:w-64" />
          </div>
          {shown.length === 0 ? (
            <Empty icon={<FileStack className="h-10 w-10" />} title={runs.length ? "No invoices match" : "No invoices yet"}>
              {!runs.length && <>Open the <Link className="text-indigo-600" to="/inbox">AP inbox</Link> and process the new emails.</>}
            </Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[920px] text-sm">
                <thead>
                  <tr className="text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2.5">#</th>
                    <th className="px-4 py-2.5">Vendor</th>
                    <th className="px-4 py-2.5">Invoice</th>
                    <th className="px-4 py-2.5">PO</th>
                    <th className="px-4 py-2.5 text-right">Total</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Recommendation</th>
                    <th className="px-4 py-2.5">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {shown.map((r) => (
                    <tr key={r.id} onClick={() => nav(`/runs/${r.id}`)} className="cursor-pointer hover:bg-slate-50">
                      <td className="px-4 py-3">
                        <div className="font-medium text-slate-800">{r.id}</div>
                        <div className="text-xs text-slate-400">{timeAgo(r.created_at)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="max-w-[200px] truncate font-medium text-slate-800">{r.vendor_name || "—"}</div>
                        <div className="max-w-[200px] truncate text-xs text-slate-400">{r.sender_email || r.filename}</div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{r.invoice_number || "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs">{r.po_number || "—"}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{money(r.total, r.currency || "USD")}</td>
                      <td className="px-4 py-3">
                        <StatusChip status={r.status} />
                        {r.approved_by && r.status !== "pending_approval" && (
                          <div className="mt-1 text-[11px] text-slate-400">{r.approved_by === "system" ? "auto-approved" : "approved by reviewer"}</div>
                        )}
                      </td>
                      <td className="px-4 py-3"><DecisionChip decision={r.decision} /></td>
                      <td className="max-w-[300px] px-4 py-3 text-xs text-slate-600"><span className="line-clamp-2">{r.error || r.headline || ""}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

function Kpi({ icon, label, value, sub, tone = "slate", onClick }: {
  icon: React.ReactNode; label: string; value: React.ReactNode; sub?: string;
  tone?: "slate" | "indigo" | "emerald" | "amber" | "rose"; onClick?: () => void;
}) {
  const t = {
    slate: "bg-slate-100 text-slate-600", indigo: "bg-indigo-50 text-indigo-600", emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600", rose: "bg-rose-50 text-rose-600",
  }[tone];
  return (
    <Card className={cx("p-4", onClick && "cursor-pointer transition hover:border-slate-300")}>
      <div onClick={onClick}>
        <div className={cx("mb-3 grid h-8 w-8 place-items-center rounded-lg [&>svg]:h-4 [&>svg]:w-4", t)}>{icon}</div>
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <div className="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">{value}</div>
        {sub && <div className="mt-0.5 text-xs text-slate-400">{sub}</div>}
      </div>
    </Card>
  );
}
