import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, FileUp, Inbox as InboxIcon, Paperclip, Play, PlayCircle } from "lucide-react";
import { api, shortDate, type InboxMessage } from "../api";
import { Button, Card, Empty, StatusChip, cx } from "../components/ui";
import { PageHeader } from "../App";

type Filter = "all" | "new" | "processed";

export default function InboxPage() {
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const load = () => api.inbox().then(setMessages).catch((e) => setNotice({ tone: "err", text: e.message }));
  useEffect(() => {
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, []);

  const shown = useMemo(() => messages.filter((m) =>
    filter === "all" ? true : filter === "new" ? !m.run_id : !!m.run_id), [messages, filter]);
  const selected = messages.find((m) => m.id === selectedId) ?? shown[0] ?? null;
  const newCount = messages.filter((m) => !m.run_id).length;

  const flash = (tone: "ok" | "err", text: string) => {
    setNotice({ tone, text });
    setTimeout(() => setNotice(null), 5000);
  };

  const processOne = async (m: InboxMessage) => {
    setBusy(true);
    try {
      const { run_id } = await api.processMessage(m.id);
      nav(`/runs/${run_id}`);
    } catch (e) {
      flash("err", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const processAll = async () => {
    setBusy(true);
    try {
      const { run_ids } = await api.processAll();
      flash("ok", `${run_ids.length} invoice${run_ids.length === 1 ? "" : "s"} queued — processed one at a time. Watch statuses update here or on the dashboard.`);
      load();
    } catch (e) {
      flash("err", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const upload = async (files: FileList | null) => {
    const f = files?.[0];
    if (!f) return;
    setBusy(true);
    try {
      const { run_id } = await api.upload(f);
      nav(`/runs/${run_id}`);
    } catch (e) {
      flash("err", (e as Error).message);
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="AP inbox"
        subtitle="ap@harborview-mfg.com — vendor invoices arrive here by email."
        right={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
              <FileUp className="h-4 w-4" /> Upload invoice
            </Button>
            <Button onClick={processAll} disabled={busy || newCount === 0}>
              <PlayCircle className="h-4 w-4" /> Process all new ({newCount})
            </Button>
            <input ref={fileInput} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => upload(e.target.files)} />
          </div>
        }
      />
      {notice && (
        <div className={cx("mx-4 mt-4 rounded-lg border px-4 py-2.5 text-sm sm:mx-8",
          notice.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-rose-200 bg-rose-50 text-rose-700")}>
          {notice.text}
        </div>
      )}

      <div className="grid min-h-0 flex-1 gap-4 px-4 py-4 sm:px-8 lg:grid-cols-[400px_1fr]">
        <Card className="flex min-h-0 flex-col overflow-hidden">
          <div className="flex gap-1 border-b border-slate-100 p-2">
            {(["all", "new", "processed"] as Filter[]).map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                className={cx("rounded-md px-2.5 py-1 text-sm font-medium capitalize",
                  filter === f ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100")}>
                {f}{f === "new" && newCount ? ` (${newCount})` : ""}
              </button>
            ))}
          </div>
          <ul className="min-h-0 flex-1 divide-y divide-slate-100 overflow-y-auto">
            {shown.length === 0 && <Empty icon={<InboxIcon className="h-8 w-8" />} title="No messages" />}
            {shown.map((m) => (
              <li key={m.id}>
                <button onClick={() => setSelectedId(m.id)}
                  className={cx("w-full px-4 py-3 text-left transition",
                    selected?.id === m.id ? "bg-indigo-50/70" : "hover:bg-slate-50")}>
                  <div className="flex items-center gap-2">
                    {!m.run_id && <span className="h-2 w-2 shrink-0 rounded-full bg-indigo-500" title="New" />}
                    <span className={cx("min-w-0 flex-1 truncate text-sm", !m.run_id ? "font-semibold text-slate-900" : "text-slate-700")}>
                      {m.from_name}
                    </span>
                    <span className="shrink-0 text-xs text-slate-400">{shortDate(m.received_at)}</span>
                  </div>
                  <div className={cx("mt-0.5 truncate text-sm", !m.run_id ? "text-slate-800" : "text-slate-500")}>{m.subject}</div>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <span className="inline-flex min-w-0 items-center gap-1 truncate text-xs text-slate-500">
                      <Paperclip className="h-3 w-3 shrink-0" /> {m.attachment}
                    </span>
                    {m.run_status && <StatusChip status={m.run_status} />}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="flex min-h-[60vh] flex-col overflow-hidden">
          {!selected ? (
            <Empty icon={<InboxIcon className="h-10 w-10" />} title="Select a message" />
          ) : (
            <>
              <div className="border-b border-slate-100 px-5 py-4">
                <h2 className="text-lg font-semibold text-slate-900">{selected.subject}</h2>
                <div className="mt-1 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="text-slate-600">
                    <span className="font-medium text-slate-800">{selected.from_name}</span>{" "}
                    <span className="text-slate-400">&lt;{selected.from_email}&gt;</span>
                  </span>
                  <span className="text-xs text-slate-400">{new Date(selected.received_at).toLocaleString()}</span>
                </div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
                <p className="whitespace-pre-wrap text-sm text-slate-700">{selected.body}</p>

                <div className={cx("flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3",
                  selected.run_id ? "border-slate-200 bg-slate-50" : "border-indigo-200 bg-indigo-50/60")}>
                  {selected.run_id ? (
                    <>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 text-sm">
                          <span className="font-medium text-slate-800">Invoice #{selected.run_id}</span>
                          {selected.run_status && <StatusChip status={selected.run_status} />}
                        </div>
                        {selected.run_headline && <p className="mt-0.5 truncate text-xs text-slate-500">{selected.run_headline}</p>}
                      </div>
                      <Link to={`/runs/${selected.run_id}`}>
                        <Button variant="secondary">Open invoice <ArrowRight className="h-4 w-4" /></Button>
                      </Link>
                    </>
                  ) : (
                    <>
                      <span className="text-sm text-slate-700">
                        <Paperclip className="mr-1 inline h-3.5 w-3.5" />
                        <b>{selected.attachment}</b> has not been processed yet.
                      </span>
                      <Button onClick={() => processOne(selected)} disabled={busy}>
                        <Play className="h-3.5 w-3.5" /> Process invoice
                      </Button>
                    </>
                  )}
                </div>

                <iframe title="attachment" src={`/api/inbox/${selected.id}/attachment#view=FitH&toolbar=0`}
                  className="min-h-[480px] w-full flex-1 rounded-lg border border-slate-200" />
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
