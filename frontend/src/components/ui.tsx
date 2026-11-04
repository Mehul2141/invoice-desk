import type { ReactNode } from "react";
import { AlertTriangle, Ban, CheckCircle2, Circle, Clock, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { Check, Decision, InvoiceStatus, StageStatus } from "../api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

// System recommendation (what the controls concluded), distinct from the invoice's lifecycle status.
export const DECISION_STYLE: Record<Decision, { label: string; chip: string; banner: string; dot: string }> = {
  APPROVE: {
    label: "Matched",
    chip: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
    banner: "from-emerald-50 to-white border-emerald-200",
    dot: "bg-emerald-500",
  },
  HOLD: {
    label: "Exception",
    chip: "bg-amber-50 text-amber-800 ring-amber-600/25",
    banner: "from-amber-50 to-white border-amber-200",
    dot: "bg-amber-500",
  },
  REJECT: {
    label: "Reject",
    chip: "bg-rose-50 text-rose-700 ring-rose-600/20",
    banner: "from-rose-50 to-white border-rose-200",
    dot: "bg-rose-500",
  },
};

export function DecisionChip({ decision, size = "sm" }: { decision: Decision | null; size?: "sm" | "lg" }) {
  if (!decision) return <span className="text-slate-400">—</span>;
  const s = DECISION_STYLE[decision];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        s.chip,
        size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs",
      )}
    >
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export const STATUS_STYLE: Record<InvoiceStatus, { label: string; chip: string; dot: string; pulse?: boolean }> = {
  queued: { label: "Queued", chip: "bg-slate-100 text-slate-700 ring-slate-500/20", dot: "bg-slate-400" },
  processing: { label: "Processing", chip: "bg-indigo-50 text-indigo-700 ring-indigo-600/20", dot: "bg-indigo-500", pulse: true },
  waiting_retry: { label: "Waiting for AI", chip: "bg-sky-50 text-sky-700 ring-sky-600/20", dot: "bg-sky-500", pulse: true },
  failed: { label: "Failed", chip: "bg-rose-50 text-rose-800 ring-rose-700/25", dot: "bg-rose-600" },
  needs_review: { label: "Needs review", chip: "bg-amber-50 text-amber-800 ring-amber-600/25", dot: "bg-amber-500" },
  pending_approval: { label: "Pending approval", chip: "bg-violet-50 text-violet-700 ring-violet-600/20", dot: "bg-violet-500" },
  approved: { label: "Approved", chip: "bg-emerald-50 text-emerald-700 ring-emerald-600/20", dot: "bg-emerald-500" },
  rejected: { label: "Rejected", chip: "bg-rose-50 text-rose-700 ring-rose-600/20", dot: "bg-rose-500" },
  paid: { label: "Paid", chip: "bg-teal-50 text-teal-700 ring-teal-600/20", dot: "bg-teal-500" },
};

export function StatusChip({ status, size = "sm" }: { status: InvoiceStatus | null; size?: "sm" | "lg" }) {
  if (!status) return <span className="text-slate-400">—</span>;
  const s = STATUS_STYLE[status];
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full font-medium ring-1 ring-inset", s.chip,
      size === "lg" ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-xs")}>
      <span className={cx("h-1.5 w-1.5 rounded-full", s.dot, s.pulse && "animate-pulse")} />
      {s.label}
    </span>
  );
}

export function StatusIcon({ status, className = "h-5 w-5" }: { status: StageStatus | Check["status"]; className?: string }) {
  switch (status) {
    case "running":
      return <Loader2 className={cx(className, "animate-spin text-indigo-600")} />;
    case "waiting":
      return <Clock className={cx(className, "text-sky-600")} />;
    case "pass":
      return <CheckCircle2 className={cx(className, "text-emerald-600")} />;
    case "warn":
      return <AlertTriangle className={cx(className, "text-amber-500")} />;
    case "fail":
      return <XCircle className={cx(className, "text-rose-600")} />;
    case "error":
      return <Ban className={cx(className, "text-rose-700")} />;
    case "skipped":
      return <MinusCircle className={cx(className, "text-slate-300")} />;
    default:
      return <Circle className={cx(className, "text-slate-300")} />;
  }
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-slate-200 bg-white shadow-sm", className)}>{children}</div>;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{children}</h3>
      {right}
    </div>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(110px,max-content)_1fr] gap-x-6 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="min-w-0 break-words text-slate-800">{v ?? <span className="text-slate-400">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

const SEVERITY_TAG: Record<string, string> = {
  critical: "bg-rose-100 text-rose-700",
  high: "bg-amber-100 text-amber-800",
  low: "bg-slate-100 text-slate-600",
};

export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="divide-y divide-slate-100">
      {checks.map((c) => (
        <li key={c.id} className="flex gap-3 py-2.5">
          <StatusIcon status={c.status} className="mt-0.5 h-4.5 w-4.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-slate-800">{c.label}</span>
              {c.status !== "pass" && c.severity !== "none" && (
                <span className={cx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", SEVERITY_TAG[c.severity])}>
                  {c.severity === "low" ? "note" : c.severity}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-sm text-slate-600">{c.message}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.9 ? "bg-emerald-500" : value >= 0.7 ? "bg-amber-400" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2" title={`${pct}% confidence`}>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div className={cx("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-xs tabular-nums text-slate-500">{pct}%</span>
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  className,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger" | "success";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  const v = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm",
    secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50",
    ghost: "text-slate-600 hover:bg-slate-100",
    danger: "bg-rose-600 text-white hover:bg-rose-500 shadow-sm",
    success: "bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm",
  }[variant];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        v,
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-3 text-slate-300">{icon}</div>
      <p className="font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 max-w-sm text-sm text-slate-500">{children}</div>}
    </div>
  );
}
