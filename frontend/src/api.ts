/* eslint-disable @typescript-eslint/no-explicit-any */
export type Decision = "APPROVE" | "HOLD" | "REJECT";
export type Provider = "anthropic" | "gemini" | "mock";
export type InvoiceStatus =
  | "queued"
  | "processing"
  | "waiting_retry"
  | "failed"
  | "needs_review"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "paid";

export const ACTIVE_STATUSES: InvoiceStatus[] = ["queued", "processing", "waiting_retry"];

export const PROVIDER_LABEL: Record<string, string> = {
  anthropic: "Claude",
  gemini: "Gemini",
  mock: "Mock (no API key)",
  template: "template",
};
export type StageStatus = "pending" | "running" | "waiting" | "pass" | "warn" | "fail" | "skipped" | "error";

export interface Check {
  id: string;
  label: string;
  status: "pass" | "warn" | "fail" | "info";
  severity: "none" | "low" | "high" | "critical";
  message: string;
  category: string | null;
  action: string | null;
  evidence: Record<string, unknown>;
}

export interface Stage {
  run_id: number;
  idx: number;
  key: string;
  name: string;
  status: StageStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  summary: string | null;
  detail: any;
}

export interface RunSummary {
  id: number;
  created_at: string;
  updated_at: string | null;
  finished_at: string | null;
  filename: string;
  source: "email" | "upload";
  sender_email: string | null;
  extraction_mode: Provider | null;
  status: InvoiceStatus;
  status_label: string;
  decision: Decision | null;
  approved_by: "system" | "reviewer" | null;
  vendor_id: string | null;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  total: number | null;
  currency: string | null;
  po_number: string | null;
  headline: string | null;
  duration_ms: number | null;
  attempts: number;
  next_retry_at: string | null;
  error: string | null;
}

export interface RunResult {
  decision: Decision;
  status: InvoiceStatus;
  status_reason: string;
  headline: string;
  explanation: string;
  vendor_email: string | null;
  narrative_source: Provider | "template";
  next_action: string;
  reasons: Check[];
  checks: Check[];
  check_counts: { pass: number; warn: number; fail: number };
  po_balance: any;
  extraction: any;
}

export interface Event {
  id: number;
  at: string;
  status: InvoiceStatus | null;
  actor: "system" | "reviewer" | "user";
  note: string | null;
}

export interface Run extends RunSummary {
  started_at: string | null;
  error_detail: string | null;
  queue_position: number;
  result: RunResult | null;
  rules: Settings | null;
  stages: Stage[];
  events: Event[];
  email?: { id: string; from_name: string; from_email: string; subject: string; received_at: string } | null;
}

export interface InboxMessage {
  id: string;
  received_at: string;
  from_name: string;
  from_email: string;
  subject: string;
  body: string;
  attachment: string;
  run_id: number | null;
  run_status: InvoiceStatus | null;
  run_status_label: string | null;
  run_headline: string | null;
}

export interface Settings {
  approval_mode: "autonomous" | "hitl";
  auto_approve_limit: number;
  price_tolerance_pct: number;
  quantity_tolerance_pct: number;
  amount_tolerance_pct: number;
  amount_tolerance_abs: number;
  three_way_match: boolean;
  receipt_tolerance_pct: number;
  duplicate_window_days: number;
  min_confidence_pct: number;
}

export interface Stats {
  received: number;
  counts: Record<InvoiceStatus, number>;
  in_progress: number;
  decided: number;
  touchless: number;
  touchless_rate: number | null;
  awaiting_human: number;
  value_approved: number;
  value_paid: number;
  value_blocked: number;
  value_pending: number;
  avg_duration_ms: number | null;
}

export interface Health {
  ok: boolean;
  llm_enabled: boolean;
  provider: Provider;
  model: string | null;
}

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not json */
    }
    throw new Error(msg);
  }
  return res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => req<Health>("/api/health"),
  stats: () => req<Stats>("/api/stats"),
  runs: () => req<RunSummary[]>("/api/runs"),
  run: (id: number | string) => req<Run>(`/api/runs/${id}`),
  inbox: () => req<InboxMessage[]>("/api/inbox"),
  processMessage: (id: string) => req<{ run_id: number }>(`/api/inbox/${id}/process`, { method: "POST" }),
  processAll: () => req<{ run_ids: number[] }>("/api/inbox/process-all", { method: "POST" }),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ run_id: number }>("/api/runs", { method: "POST", body: fd });
  },
  action: (id: number, action: "approve" | "reject" | "mark_paid", note = "") =>
    req<Run>(`/api/runs/${id}/action`, json("POST", { action, note })),
  reprocess: (id: number) => req<Run>(`/api/runs/${id}/reprocess`, { method: "POST" }),
  settings: () => req<{ values: Settings; defaults: Settings }>("/api/settings"),
  saveSettings: (s: Partial<Settings>) => req<{ values: Settings; defaults: Settings }>("/api/settings", json("PUT", s)),
  resetSettings: () => req<{ values: Settings; defaults: Settings }>("/api/settings/reset", { method: "POST" }),
  vendors: () => req<any[]>("/api/vendors"),
  purchaseOrders: () => req<any[]>("/api/purchase-orders"),
  goodsReceipts: () => req<any[]>("/api/goods-receipts"),
  ledger: () => req<any[]>("/api/ledger"),
  reset: () => req<{ ok: boolean }>("/api/demo/reset", { method: "POST" }),
};

export const money = (n: number | null | undefined, currency = "USD") =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: currency || "USD" });

export const duration = (ms: number | null | undefined) =>
  ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;

export function timeAgo(iso: string) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function shortDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + " " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
