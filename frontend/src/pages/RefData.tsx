/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, money } from "../api";
import { Card, cx } from "../components/ui";
import { PageHeader } from "../App";

type Tab = "pos" | "grns" | "vendors" | "ledger";

export default function RefData() {
  const [tab, setTab] = useState<Tab>("pos");
  const [vendors, setVendors] = useState<any[]>([]);
  const [pos, setPos] = useState<any[]>([]);
  const [grns, setGrns] = useState<any[]>([]);
  const [ledger, setLedger] = useState<any[]>([]);

  useEffect(() => {
    api.vendors().then(setVendors);
    api.purchaseOrders().then(setPos);
    api.goodsReceipts().then(setGrns);
    api.ledger().then(setLedger);
  }, []);

  return (
    <div>
      <PageHeader title="Vendors, POs & goods receipts" subtitle="The procurement data every invoice is matched against. PO balances update as invoices are approved." />
      <div className="px-4 py-6 sm:px-8">
        <div className="mb-4 flex flex-wrap gap-1">
          {([["pos", "Purchase orders"], ["grns", "Goods receipts (GRN)"], ["vendors", "Vendor master"], ["ledger", "Invoice ledger"]] as [Tab, string][]).map(([k, l]) => (
            <button key={k} onClick={() => setTab(k)}
              className={cx("rounded-md px-3 py-1.5 text-sm font-medium", tab === k ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100")}>
              {l}
            </button>
          ))}
        </div>

        {tab === "pos" && (
          <div className="grid gap-4 xl:grid-cols-2">
            {pos.map((po) => {
              const used = Math.min(100, (po.billed / po.total) * 100);
              return (
                <Card key={po.po_number} className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-mono text-sm font-semibold text-slate-900">{po.po_number}</div>
                      <div className="text-sm text-slate-600">{po.description}</div>
                      <div className="text-xs text-slate-400">{po.vendor_name} · {po.buyer} · issued {po.issue_date}</div>
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600"
                        title={po.match_type === "3-way" ? "Goods PO — invoice must be covered by a goods receipt" : "Services PO — no goods receipt"}>{po.match_type}</span>
                      <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium",
                        po.status === "open" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500")}>{po.status}</span>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-indigo-500" style={{ width: `${used}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-slate-500">
                    <span>Billed {money(po.billed)} of {money(po.total)}</span>
                    <span>Remaining {money(po.remaining)}</span>
                  </div>
                  <table className="mt-3 w-full text-xs">
                    <thead><tr className="text-left text-slate-400"><th className="py-1">SKU</th><th>Description</th><th className="text-right">Ordered</th>
                      {po.match_type === "3-way" && <th className="text-right">Received</th>}<th className="text-right">Billed</th><th className="text-right">Unit</th></tr></thead>
                    <tbody>
                      {po.lines.map((l: any) => (
                        <tr key={l.sku} className="border-t border-slate-100">
                          <td className="py-1 font-mono">{l.sku}</td>
                          <td className="text-slate-600">{l.description}</td>
                          <td className="text-right tabular-nums">{l.quantity}</td>
                          {po.match_type === "3-way" && <td className={cx("text-right tabular-nums", l.received_quantity < l.quantity && "text-amber-700")}>{l.received_quantity}</td>}
                          <td className={cx("text-right tabular-nums", (l.billed_quantity > l.quantity || (po.match_type === "3-way" && l.billed_quantity > l.received_quantity)) && "font-medium text-rose-600")}>{l.billed_quantity}</td>
                          <td className="text-right tabular-nums">{money(l.unit_price)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              );
            })}
          </div>
        )}

        {tab === "grns" && (
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[700px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-4 py-2">GRN</th><th>PO</th><th>Received on</th><th>SKU</th><th className="text-right">Qty received</th><th className="px-4">Received by</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {grns.map((g, i) => (
                  <tr key={i}>
                    <td className="px-4 py-2 font-mono text-xs">{g.grn_number}</td>
                    <td className="font-mono text-xs">{g.po_number}</td>
                    <td className="text-xs">{g.receipt_date}</td>
                    <td className="font-mono text-xs">{g.sku}</td>
                    <td className="text-right tabular-nums">{g.quantity_received}</td>
                    <td className="px-4 text-xs text-slate-500">{g.received_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {tab === "vendors" && (
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-4 py-2">ID</th><th>Vendor</th><th>Tax ID</th><th>Bank on file</th><th>Terms</th><th>Contact</th><th className="px-4">Status</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {vendors.map((v) => (
                  <tr key={v.vendor_id}>
                    <td className="px-4 py-2.5 font-mono text-xs">{v.vendor_id}</td>
                    <td><div className="font-medium">{v.legal_name}</div><div className="text-xs text-slate-400">aka {v.aliases.join(", ")}</div></td>
                    <td className="font-mono text-xs">{v.tax_id}</td>
                    <td className="text-xs">{v.bank_name} {v.bank_account}</td>
                    <td>Net {v.payment_terms_days}</td>
                    <td className="text-xs text-slate-500">{v.contact_email}<br />{v.contact_phone}</td>
                    <td className="px-4">
                      <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium", v.status === "approved" ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700")}
                        title={v.status_reason}>{v.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {tab === "ledger" && (
          <Card className="overflow-x-auto">
            <table className="w-full min-w-[800px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr><th className="px-4 py-2">Invoice</th><th>Vendor</th><th>Date</th><th>PO</th><th className="text-right">Net</th><th className="text-right">Total</th><th className="px-4">Status</th><th>Source</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {ledger.map((l) => (
                  <tr key={l.id}>
                    <td className="px-4 py-2 font-mono text-xs">{l.invoice_number}</td>
                    <td className="text-xs">{l.vendor_id}</td>
                    <td className="text-xs">{l.invoice_date}</td>
                    <td className="font-mono text-xs">{l.po_number ?? "—"}</td>
                    <td className="text-right tabular-nums">{money(l.net_amount)}</td>
                    <td className="text-right tabular-nums">{money(l.total)}</td>
                    <td className="px-4 text-xs">{l.status.replace("_", " ")}{l.paid_on ? ` ${l.paid_on}` : ""}</td>
                    <td className="text-xs">{l.run_id ? <Link className="text-indigo-600" to={`/runs/${l.run_id}`}>invoice #{l.run_id}</Link> : "history"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
