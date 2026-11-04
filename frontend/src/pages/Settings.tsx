import { useEffect, useState, type ReactNode } from "react";
import { Bot, Info, RotateCcw, Save, Trash2, UserCheck } from "lucide-react";
import { api, money, type Settings } from "../api";
import { Button, Card, cx } from "../components/ui";
import { PageHeader } from "../App";

export default function SettingsPage() {
  const [saved, setSaved] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.settings().then((s) => { setSaved(s.values); setDraft(s.values); });
  }, []);

  if (!draft || !saved) return <div className="p-8 text-sm text-slate-500">Loading…</div>;

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setDraft({ ...draft, [k]: v });
  const flash = (tone: "ok" | "err", text: string) => { setMsg({ tone, text }); setTimeout(() => setMsg(null), 5000); };

  const save = async () => {
    setBusy(true);
    try {
      const s = await api.saveSettings(draft);
      setSaved(s.values);
      setDraft(s.values);
      flash("ok", "Saved. New invoices use these rules immediately; use “Re-run with current rules” on an existing invoice to re-evaluate it.");
    } catch (e) {
      flash("err", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    const s = await api.resetSettings();
    setSaved(s.values);
    setDraft(s.values);
    flash("ok", "Default rules restored.");
  };
  const resetDemo = async () => {
    if (!confirm("Clear all invoices, restore the ledger and put every email back in the inbox as new?")) return;
    try {
      await api.reset();
      flash("ok", "Demo data reset — inbox restored, ledger back to seeded history. Rules were kept.");
    } catch (e) {
      flash("err", (e as Error).message);
    }
  };

  const examplePo = 10000;
  const allowedOver = Math.min(examplePo * draft.amount_tolerance_pct / 100, draft.amount_tolerance_abs);

  return (
    <div>
      <PageHeader
        title="Rules & settings"
        subtitle="Matching rules and approval policy. Every invoice records the rules it was evaluated under."
        right={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={restore} disabled={busy}><RotateCcw className="h-4 w-4" /> Restore defaults</Button>
            <Button onClick={save} disabled={busy || !dirty}><Save className="h-4 w-4" /> {dirty ? "Save changes" : "Saved"}</Button>
          </div>
        }
      />
      <div className="max-w-5xl space-y-6 px-4 py-6 sm:px-8">
        {msg && (
          <div className={cx("rounded-lg border px-4 py-2.5 text-sm",
            msg.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-700")}>{msg.text}</div>
        )}

        <Section title="Approval policy" subtitle="What happens to an invoice that passes every control.">
          <div className="grid gap-3 md:grid-cols-2">
            <ModeCard active={draft.approval_mode === "autonomous"} onClick={() => set("approval_mode", "autonomous")}
              icon={<Bot className="h-5 w-5" />} title="Autonomous"
              text="The AI approves clean invoices straight through for payment. Only exceptions — and invoices above the limit — reach a person." />
            <ModeCard active={draft.approval_mode === "hitl"} onClick={() => set("approval_mode", "hitl")}
              icon={<UserCheck className="h-5 w-5" />} title="Human-in-the-loop"
              text="The AI reads, matches and recommends, but every invoice waits in Approvals until a person signs off." />
          </div>
          {draft.approval_mode === "autonomous" && (
            <Field label="Auto-approval limit" hint="Clean invoices above this total still need a person’s approval. 0 = no limit.">
              <NumInput value={draft.auto_approve_limit} onChange={(v) => set("auto_approve_limit", v)} prefix="$" step={1000} />
            </Field>
          )}
          <p className="flex gap-2 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <Info className="h-4 w-4 shrink-0 text-slate-400" />
            In both modes, invoices that fail a critical control (duplicate, blocked or unknown vendor) are rejected automatically,
            and any other exception goes to Approvals → Needs review.
          </p>
        </Section>

        <Section title="2-way match — invoice ↔ purchase order" subtitle="How far an invoice may deviate from its PO before it becomes an exception.">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Unit price tolerance" hint="Invoice unit price may exceed the PO price by up to this much.">
              <NumInput value={draft.price_tolerance_pct} onChange={(v) => set("price_tolerance_pct", v)} suffix="%" step={0.5} />
            </Field>
            <Field label="Quantity tolerance" hint="Total billed quantity may exceed the ordered quantity by up to this much.">
              <NumInput value={draft.quantity_tolerance_pct} onChange={(v) => set("quantity_tolerance_pct", v)} suffix="%" step={1} />
            </Field>
            <Field label="Amount tolerance (%)" hint="Total billed across all invoices may exceed the PO total by this %…">
              <NumInput value={draft.amount_tolerance_pct} onChange={(v) => set("amount_tolerance_pct", v)} suffix="%" step={0.5} />
            </Field>
            <Field label="Amount tolerance (max $)" hint="…but by no more than this amount — whichever is lower.">
              <NumInput value={draft.amount_tolerance_abs} onChange={(v) => set("amount_tolerance_abs", v)} prefix="$" step={50} />
            </Field>
          </div>
          <p className="rounded-lg bg-indigo-50/60 p-3 text-xs text-indigo-900">
            Example: a {money(examplePo).replace(".00", "")} PO can be billed up to <b>{money(examplePo + allowedOver)}</b> in total, and a $100.00 unit price up
            to <b>{money(100 * (1 + draft.price_tolerance_pct / 100))}</b>. An order of 100 units can be billed for up
            to <b>{Math.floor(100 * (1 + draft.quantity_tolerance_pct / 100) + 1e-9)}</b>.
          </p>
        </Section>

        <Section title="3-way match — invoice ↔ PO ↔ goods receipt (GRN)" subtitle="Pay only for goods the warehouse has confirmed as received. Services POs are always 2-way.">
          <label className="flex cursor-pointer items-center gap-3">
            <Toggle on={draft.three_way_match} onChange={(v) => set("three_way_match", v)} />
            <span className="text-sm font-medium text-slate-800">Require a goods receipt for goods POs</span>
          </label>
          {draft.three_way_match && (
            <Field label="Received quantity tolerance" hint="Total billed may exceed the quantity received by up to this much.">
              <NumInput value={draft.receipt_tolerance_pct} onChange={(v) => set("receipt_tolerance_pct", v)} suffix="%" step={1} />
            </Field>
          )}
        </Section>

        <Section title="Other controls">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Duplicate window" hint="Same vendor + same amount within this many days is flagged as a possible duplicate.">
              <NumInput value={draft.duplicate_window_days} onChange={(v) => set("duplicate_window_days", v)} suffix="days" step={1} />
            </Field>
            <Field label="Minimum reading confidence" hint="Fields the AI read with lower confidence send the invoice to review.">
              <NumInput value={draft.min_confidence_pct} onChange={(v) => set("min_confidence_pct", v)} suffix="%" step={5} />
            </Field>
          </div>
        </Section>

        <Section title="Demo tools">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-600">Clear all invoices, restore the PO ledger and mark every inbox email as new. Rules above are kept.</p>
            <Button variant="danger" onClick={resetDemo}><Trash2 className="h-4 w-4" /> Reset demo data</Button>
          </div>
        </Section>
      </div>
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="font-semibold text-slate-900">{title}</h2>
      {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </Card>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-sm font-medium text-slate-800">{label}</div>
      {hint && <div className="mb-1.5 text-xs text-slate-500">{hint}</div>}
      {children}
    </div>
  );
}

function NumInput({ value, onChange, prefix, suffix, step }: {
  value: number; onChange: (v: number) => void; prefix?: string; suffix?: string; step?: number;
}) {
  return (
    <div className="flex w-48 items-center overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-100">
      {prefix && <span className="pl-3 text-sm text-slate-400">{prefix}</span>}
      <input type="number" min={0} step={step} value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
        className="w-full px-3 py-1.5 text-sm tabular-nums outline-none" />
      {suffix && <span className="pr-3 text-sm text-slate-400">{suffix}</span>}
    </div>
  );
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} onClick={() => onChange(!on)}
      className={cx("relative h-6 w-11 shrink-0 rounded-full transition", on ? "bg-indigo-600" : "bg-slate-300")}>
      <span className={cx("absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all", on ? "left-[22px]" : "left-0.5")} />
    </button>
  );
}

function ModeCard({ active, onClick, icon, title, text }: { active: boolean; onClick: () => void; icon: ReactNode; title: string; text: string }) {
  return (
    <button type="button" onClick={onClick}
      className={cx("flex gap-3 rounded-xl border-2 p-4 text-left transition",
        active ? "border-indigo-500 bg-indigo-50/50" : "border-slate-200 hover:border-slate-300")}>
      <div className={cx("grid h-9 w-9 shrink-0 place-items-center rounded-lg", active ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-500")}>{icon}</div>
      <div>
        <div className="flex items-center gap-2 font-medium text-slate-900">
          {title}
          <span className={cx("h-3.5 w-3.5 rounded-full border-2", active ? "border-indigo-600 bg-indigo-600 ring-2 ring-inset ring-white" : "border-slate-300")} />
        </div>
        <p className="mt-0.5 text-sm text-slate-600">{text}</p>
      </div>
    </button>
  );
}
