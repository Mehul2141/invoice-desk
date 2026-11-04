/* eslint-disable @typescript-eslint/no-explicit-any */
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { money, type Stage } from "../api";
import { CheckList, Confidence, KV, SectionTitle, cx } from "./ui";

const DESCRIPTIONS: Record<string, string> = {
  ingest: "Receives the file, fingerprints it (SHA-256) and notes whether the same file has been submitted before.",
  read: "Checks for a machine-readable text layer. Scanned images have none and are read visually by the model.",
  extract: "The LLM transcribes the invoice into a fixed schema with a confidence per key field. It extracts — it does not decide.",
  validate: "Checks the invoice against itself: required fields, line arithmetic, tax treatment, dates and reading confidence.",
  vendor: "Matches the issuer to the approved vendor master by tax ID, then name; checks the vendor is allowed to be paid.",
  po: "2-way match: finds the purchase order — from the reference on the invoice, or by inferring it from vendor, lines and amount.",
  receipt: "3-way match: compares billed quantities with what the warehouse actually received (goods receipts / GRNs). Services POs are 2-way.",
  rules: "Deterministic AP controls: price and quantity tolerance, PO balance across split invoices, duplicates, bank details, sender domain.",
  decision: "Rules engine turns every check into a recommendation; the approval policy in Settings decides whether a human must sign off.",
};

export default function StageDetail({ stage }: { stage: Stage; runId: number }) {
  const d = stage.detail;
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">{DESCRIPTIONS[stage.key]}</p>
      {stage.status === "pending" && <p className="text-sm text-slate-400">Waiting for earlier stages…</p>}
      {stage.status === "running" && (
        <div className="flex items-center gap-2 text-sm text-indigo-700">
          <Loader2 className="h-4 w-4 animate-spin" />
          {stage.key === "extract" ? "The model is reading the invoice…" : stage.key === "decision" ? "Deciding and writing the explanation…" : "Working…"}
        </div>
      )}
      {stage.status === "skipped" && <p className="text-sm text-slate-400">{stage.summary}</p>}
      {(stage.status === "error" || stage.status === "waiting") && d ? (
        <div className={cx("rounded-lg border p-4 text-sm",
          stage.status === "error" ? "border-rose-200 bg-rose-50 text-rose-800" : "border-sky-200 bg-sky-50 text-sky-900")}>
          <div className="font-semibold">{d.reason}</div>
          {stage.status === "waiting" && (
            <p className="mt-1">Attempt {d.attempt} of {d.max_attempts} failed. The invoice stays in the queue and retries automatically
              {d.retry_at ? ` at ${new Date(d.retry_at).toLocaleTimeString()}` : ""} — with a longer wait each time, and never faster
              than the provider asks.</p>
          )}
          {d.technical_detail && (
            <details className="mt-2 text-xs opacity-80">
              <summary className="cursor-pointer">Technical detail</summary>
              <code className="mt-1 block whitespace-pre-wrap break-words">{d.technical_detail}</code>
            </details>
          )}
        </div>
      ) : (
        d && <Body stageKey={stage.key} d={d} />
      )}
    </div>
  );
}

function Body({ stageKey, d }: { stageKey: string; d: any }) {
  switch (stageKey) {
    case "ingest":
      return (
        <KV rows={[
          ["File", d.filename],
          ["Size", `${d.size_kb} KB`],
          ["Source", d.source === "sample" ? "Prepared sample" : "Upload"],
          ["SHA-256", <code className="text-xs break-all">{d.sha256}</code>],
          ["Seen before", d.previous_runs_of_same_file?.length
            ? d.previous_runs_of_same_file.map((r: any) => `run #${r.id} (${r.decision ?? "no decision"})`).join(", ")
            : "No"],
        ]} />
      );
    case "read":
      return (
        <div className="space-y-4">
          <KV rows={[
            ["Pages", d.pages],
            ["Type", d.is_scanned ? <span className="font-medium text-amber-700">Scanned image</span> : "Digital PDF"],
            ["Text layer", `${d.text_chars} characters`],
            ["Reading method", d.method],
          ]} />
          {d.text_preview && (
            <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <summary className="cursor-pointer text-xs font-medium text-slate-600">Raw text layer</summary>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-slate-600">{d.text_preview}</pre>
            </details>
          )}
        </div>
      );
    case "extract":
      return <Extraction d={d} />;
    case "validate":
      return (
        <div className="space-y-5">
          <CheckList checks={d.checks} />
          {d.computed?.lines && (
            <div>
              <SectionTitle>Computed amounts</SectionTitle>
              <KV rows={[
                ["Sum of lines", money(d.computed.sum_lines)],
                ["Tax", `${money(d.computed.tax)}${d.computed.tax_inclusive ? " (included in prices)" : ""}`],
                ["Invoice total", money(d.computed.total)],
                ["Net amount for PO match", <b>{money(d.computed.net)}</b>],
              ]} />
            </div>
          )}
        </div>
      );
    case "vendor":
      return (
        <div className="space-y-5">
          <CheckList checks={d.checks} />
          {d.vendor && (
            <div>
              <SectionTitle>Vendor master record</SectionTitle>
              <KV rows={[
                ["Vendor", `${d.vendor.legal_name} (${d.vendor.vendor_id})`],
                ["Matched by", d.method],
                ["Tax ID", d.vendor.tax_id],
                ["Status", d.vendor.status],
                ["Terms", `Net ${d.vendor.payment_terms_days}`],
                ["Bank on file", `${d.vendor.bank_name} ${d.bank_account_masked}`],
                ["Contact", `${d.vendor.contact_email} · ${d.vendor.contact_phone}`],
              ]} />
            </div>
          )}
          {d.candidates && (
            <div>
              <SectionTitle>Closest names in vendor master</SectionTitle>
              <SimpleTable head={["Vendor", "Name similarity"]}
                rows={d.candidates.map((c: any) => [`${c.name} (${c.vendor_id})`, `${c.name_score}%`])} />
            </div>
          )}
        </div>
      );
    case "po":
      return (
        <div className="space-y-5">
          <CheckList checks={d.checks} />
          <KV rows={[
            ["Reference on invoice", d.reference_on_invoice ?? <span className="text-slate-400">none</span>],
            ["Match method", d.method ?? "no match"],
          ]} />
          {d.candidates?.length > 0 && (
            <div>
              <SectionTitle>PO inference — open POs for this vendor</SectionTitle>
              <SimpleTable head={["PO", "Description", "Line similarity", "Amount fit", "Score"]}
                rows={d.candidates.map((c: any) => [
                  <span className="font-mono text-xs">{c.po_number}</span>, c.description,
                  pct(c.line_similarity), pct(c.amount_similarity), <b>{c.score.toFixed(2)}</b>,
                ])} />
              <p className="mt-2 text-xs text-slate-400">Score = 0.6 × line-description similarity + 0.4 × amount fit vs remaining PO balance. Accept only if ≥ 0.75 and ≥ 0.15 ahead of the next PO.</p>
            </div>
          )}
          {d.line_map && (
            <div>
              <SectionTitle>Invoice lines → {d.po.po_number} lines</SectionTitle>
              <SimpleTable head={["Invoice line", "PO line", "Match"]}
                rows={d.line_map.map((m: any) => [
                  m.invoice_description,
                  m.po_sku ? <span><span className="font-mono text-xs">{m.po_sku}</span> · {m.po_description}</span> : <span className="text-rose-600">not on PO</span>,
                  pct(m.score),
                ])} />
            </div>
          )}
          {d.po && (
            <div>
              <SectionTitle>{d.po.po_number} · {d.po.description}</SectionTitle>
              <SimpleTable head={["SKU", "Description", "Qty", "Unit price", "Amount"]} align={[0, 0, 1, 1, 1]}
                rows={d.po.lines.map((l: any) => [<span className="font-mono text-xs">{l.sku}</span>, l.description, l.quantity, money(l.unit_price), money(l.amount)])} />
              <p className="mt-2 text-xs text-slate-500">Issued {d.po.issue_date} by {d.po.buyer} · PO total {money(d.po.total)}</p>
            </div>
          )}
        </div>
      );
    case "receipt":
      return (
        <div className="space-y-5">
          <CheckList checks={d.checks} />
          <KV rows={[
            ["Match type", d.match_type === "2-way" ? "2-way (services PO — no receipt expected)" : d.three_way_enabled ? "3-way (invoice ↔ PO ↔ goods receipt)" : "3-way switched off in Settings"],
            ["Receipt tolerance", `${d.receipt_tolerance_pct}%`],
          ]} />
          {d.receipts?.length > 0 && (
            <div>
              <SectionTitle>Goods receipts on this PO</SectionTitle>
              <SimpleTable head={["GRN", "Date", "SKU", "Qty received", "Received by"]} align={[0, 0, 0, 1, 0]}
                rows={d.receipts.map((g: any) => [<span className="font-mono text-xs">{g.grn_number}</span>, g.receipt_date,
                  <span className="font-mono text-xs">{g.sku}</span>, g.quantity_received, g.received_by])} />
            </div>
          )}
          {d.lines?.length > 0 && (
            <div>
              <SectionTitle>Ordered vs received vs billed</SectionTitle>
              <SimpleTable head={["SKU", "Ordered", "Received", "Billed before", "This invoice", "Total billed"]} align={[0, 1, 1, 1, 1, 1]}
                rows={d.lines.map((l: any) => [
                  <span className="font-mono text-xs">{l.sku}</span>, l.ordered, l.received, l.billed_before, l.this_invoice,
                  <span className={cx(l.cumulative > l.received * (1 + d.receipt_tolerance_pct / 100) && "font-semibold text-rose-600")}>{l.cumulative}</span>,
                ])} />
            </div>
          )}
        </div>
      );
    case "rules":
      return (
        <div className="space-y-5">
          <CheckList checks={d.checks} />
          {d.rules && <RulesApplied r={d.rules} />}
          {d.po_balance && <Balance b={d.po_balance} />}
          {d.lines?.length > 0 && (
            <div>
              <SectionTitle>Line-level comparison</SectionTitle>
              <SimpleTable head={["SKU", "PO price", "Invoice (net)", "Variance", "Ordered", "Billed before", "This invoice"]}
                align={[0, 1, 1, 1, 1, 1, 1]}
                rows={d.lines.map((l: any) => [
                  <span className="font-mono text-xs">{l.sku}</span>,
                  money(l.po_unit_price),
                  money(l.invoice_unit_price_net),
                  <span className={cx(l.price_variance_pct > 2 ? "text-rose-600 font-medium" : l.price_variance_pct > 0 ? "text-amber-700" : "")}>
                    {l.price_variance_pct > 0 ? "+" : ""}{l.price_variance_pct ?? 0}%
                  </span>,
                  l.po_quantity,
                  l.previously_billed,
                  <span className={cx(l.cumulative_quantity > l.po_quantity && "font-medium text-rose-600")}>{l.this_invoice}</span>,
                ])} />
            </div>
          )}
        </div>
      );
    case "decision":
      return (
        <div className="space-y-5">
          <div>
            <SectionTitle>All checks</SectionTitle>
            <CheckList checks={d.checks} />
          </div>
          <div className="space-y-1 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            <p><b>Recommendation:</b> any <i>critical</i> failure (duplicate, blocked or unknown vendor) → Reject. Any <i>high</i>-severity
              failure or warning → Exception (Needs review). Otherwise → Matched, with low-severity notes attached.</p>
            <p><b>Status:</b> Reject → Rejected · Exception → Needs review · Matched → Approved automatically in autonomous mode
              (up to the auto-approval limit), otherwise Pending approval.{d.status_reason ? ` This invoice: ${d.status_reason}.` : ""}</p>
          </div>
        </div>
      );
    default:
      return <pre className="text-xs">{JSON.stringify(d, null, 2)}</pre>;
  }
}

function Extraction({ d }: { d: any }) {
  const f = d.fields;
  const c = f.field_confidence || {};
  const conf = (k: string) => (k in c ? <Confidence value={c[k]} /> : null);
  const row = (label: string, value: any, key?: string) => (
    <tr key={label} className="border-b border-slate-100 last:border-0">
      <td className="py-2 pr-4 text-slate-500">{label}</td>
      <td className="py-2 pr-4 font-medium text-slate-800">{value ?? <span className="font-normal italic text-slate-400">not found</span>}</td>
      <td className="py-2">{key && conf(key)}</td>
    </tr>
  );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded bg-slate-100 px-2 py-1 text-slate-600">Engine: {d.usage?.model}</span>
        {d.usage?.input_tokens && (
          <span className="rounded bg-slate-100 px-2 py-1 text-slate-600">{d.usage.input_tokens.toLocaleString()} in / {(d.usage.output_tokens ?? 0).toLocaleString()} out tokens</span>
        )}
        {d.usage?.fallback_from && (
          <span className="rounded bg-sky-50 px-2 py-1 text-sky-700" title={d.usage.fallback_from.join("\n")}>
            Fell back from {d.usage.fallback_from.length} busy model{d.usage.fallback_from.length > 1 ? "s" : ""}
          </span>
        )}
      </div>
      {f.extraction_warnings?.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide">Reader notes</div>
          <ul className="list-disc pl-5">{f.extraction_warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-2">
        <table className="w-full text-sm">
          <tbody>
            {row("Vendor", f.vendor_name, "vendor_name")}
            {row("Tax ID", f.vendor_tax_id)}
            {row("Invoice number", f.invoice_number, "invoice_number")}
            {row("Invoice date", f.invoice_date, "invoice_date")}
            {row("Due date", f.due_date)}
            {row("PO reference", f.po_reference, "po_reference")}
          </tbody>
        </table>
        <table className="w-full text-sm">
          <tbody>
            {row("Subtotal", f.subtotal != null ? money(f.subtotal) : null)}
            {row("Tax", f.tax_amount != null ? `${money(f.tax_amount)}${f.tax_inclusive ? " (included)" : ""}` : null)}
            {row("Total", f.total != null ? money(f.total) : null, "total")}
            {row("Currency", f.currency)}
            {row("Bank", f.bank_name)}
            {row("Account", f.bank_account ? `••••${String(f.bank_account).slice(-4)}` : null, "bank_account")}
          </tbody>
        </table>
      </div>
      <div>
        <SectionTitle right={conf("line_items")}>Line items</SectionTitle>
        <SimpleTable head={["SKU", "Description", "Qty", "Unit price", "Amount"]} align={[0, 0, 1, 1, 1]}
          rows={(f.line_items || []).map((l: any) => [
            l.sku ? <span className="font-mono text-xs">{l.sku}</span> : <span className="text-slate-400">—</span>,
            l.description, l.quantity, money(l.unit_price), money(l.amount),
          ])} />
      </div>
      {f.notes && <KV rows={[["Notes on invoice", f.notes]]} />}
      <details className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <summary className="cursor-pointer text-xs font-medium text-slate-600">Raw JSON from extractor</summary>
        <pre className="mt-2 max-h-80 overflow-auto text-xs text-slate-600">{JSON.stringify(f, null, 2)}</pre>
      </details>
    </div>
  );
}

function RulesApplied({ r }: { r: any }) {
  const items = [
    ["Unit price vs PO", `+${r.price_tolerance_pct}%`],
    ["Quantity vs ordered", `+${r.quantity_tolerance_pct}%`],
    ["Amount vs PO total", `+${r.amount_tolerance_pct}% / max $${Number(r.amount_tolerance_abs).toLocaleString()}`],
    ["Billed vs received", r.three_way_match ? `+${r.receipt_tolerance_pct}%` : "3-way off"],
    ["Duplicate window", `${r.duplicate_window_days} days`],
    ["Min. reading confidence", `${r.min_confidence_pct}%`],
  ];
  return (
    <div>
      <SectionTitle right={<Link to="/settings" className="text-xs text-indigo-600 hover:underline">Change rules</Link>}>Matching rules applied to this run</SectionTitle>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {items.map(([k, v]) => (
          <div key={k} className="rounded-lg border border-slate-200 px-3 py-2">
            <div className="text-[11px] text-slate-500">{k}</div>
            <div className="text-sm font-medium tabular-nums text-slate-800">{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Balance({ b }: { b: any }) {
  const total = b.po_total || 1;
  const before = Math.min(100, (b.billed_before / total) * 100);
  const thisPct = Math.min(100 - before, (b.this_invoice / total) * 100);
  const over = b.billed_after > total;
  return (
    <div>
      <SectionTitle>PO balance</SectionTitle>
      <div className="relative h-4 overflow-hidden rounded-full bg-slate-100">
        <div className="absolute inset-y-0 left-0 bg-slate-400" style={{ width: `${before}%` }} />
        <div className={cx("absolute inset-y-0", over ? "bg-rose-500" : "bg-indigo-500")} style={{ left: `${before}%`, width: `${thisPct}%` }} />
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-slate-400" />Billed before {money(b.billed_before)}</span>
        <span><span className={cx("mr-1 inline-block h-2 w-2 rounded-full", over ? "bg-rose-500" : "bg-indigo-500")} />This invoice {money(b.this_invoice)}</span>
        <span>PO total {money(b.po_total)}</span>
        <span className={cx("font-medium", over ? "text-rose-600" : "text-slate-800")}>
          {over ? `Over by ${money(b.billed_after - b.po_total)}` : `Remaining after ${money(b.remaining_after)}`}
        </span>
      </div>
      {b.previous_invoices?.length > 0 && (
        <p className="mt-1 text-xs text-slate-400">
          Earlier invoices on this PO: {b.previous_invoices.map((i: any) => `${i.invoice_number} (${i.status})`).join(", ")}
        </p>
      )}
    </div>
  );
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

function SimpleTable({ head, rows, align = [] }: { head: string[]; rows: any[][]; align?: number[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            {head.map((h, i) => (
              <th key={h} className={cx("px-3 py-2 text-xs font-medium text-slate-500", align[i] ? "text-right" : "text-left")}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((cell, j) => (
                <td key={j} className={cx("px-3 py-2 text-slate-700", !!align[j] && "text-right tabular-nums")}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
