import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { Bot, Database, FileText, Inbox, LayoutDashboard, ListChecks, Settings as SettingsIcon, UserCheck } from "lucide-react";
import { api, money, PROVIDER_LABEL, type Health, type Settings } from "./api";
import { cx } from "./components/ui";
import Dashboard from "./pages/Dashboard";
import InboxPage from "./pages/Inbox";
import RunView from "./pages/RunView";
import Approvals from "./pages/Approvals";
import RefData from "./pages/RefData";
import SettingsPage from "./pages/Settings";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [badges, setBadges] = useState({ inbox: 0, approvals: 0 });

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    const tick = () => {
      api.stats().then((s) => setBadges((b) => ({ ...b, approvals: s.awaiting_human }))).catch(() => {});
      api.inbox().then((m) => setBadges((b) => ({ ...b, inbox: m.filter((x) => !x.run_id).length }))).catch(() => {});
      api.settings().then((s) => setSettings(s.values)).catch(() => {});
    };
    tick();
    const t = setInterval(tick, 3000);
    return () => clearInterval(t);
  }, []);

  const NAV = [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
    { to: "/inbox", label: "AP inbox", icon: Inbox, badge: badges.inbox, tone: "bg-indigo-100 text-indigo-700" },
    { to: "/approvals", label: "Approvals", icon: UserCheck, badge: badges.approvals, tone: "bg-amber-100 text-amber-800" },
    { to: "/data", label: "Vendors, POs & GRNs", icon: Database },
    { to: "/settings", label: "Rules & settings", icon: SettingsIcon },
  ];

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-indigo-600 text-white shadow-sm">
            <FileText className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">Invoice Desk</div>
            <div className="text-xs text-slate-500">Harborview Manufacturing · AP</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map(({ to, label, icon: Icon, end, badge, tone }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition",
                isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
              <Icon className="h-4 w-4" />
              <span className="flex-1">{label}</span>
              {!!badge && <span className={cx("rounded-full px-1.5 text-xs font-semibold", tone)}>{badge}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="m-3 space-y-2.5 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
          <div>
            <div className="mb-0.5 flex items-center gap-1.5 font-medium text-slate-700"><ListChecks className="h-3.5 w-3.5 text-indigo-500" /> Approval mode</div>
            {settings == null ? <span className="text-slate-400">—</span> : settings.approval_mode === "hitl" ? (
              <span className="text-slate-600">Human-in-the-loop — every invoice needs sign-off</span>
            ) : (
              <span className="text-slate-600">Autonomous{settings.auto_approve_limit ? ` up to ${money(settings.auto_approve_limit).replace(".00", "")}` : ""}</span>
            )}
          </div>
          <div>
            <div className="mb-0.5 flex items-center gap-1.5 font-medium text-slate-700"><Bot className="h-3.5 w-3.5 text-indigo-500" /> Document AI</div>
            {health == null ? <span className="text-rose-600">Backend unreachable</span> : health.llm_enabled ? (
              <span className="text-slate-600">{PROVIDER_LABEL[health.provider]} · <code className="text-[11px]">{health.model}</code></span>
            ) : (
              <span className="text-amber-700">Mock mode — no API key</span>
            )}
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-white px-3 py-2 md:hidden">
          {NAV.map(({ to, label, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx("whitespace-nowrap rounded-md px-2.5 py-1 text-sm", isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600")}>
              {label}
            </NavLink>
          ))}
        </div>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/new" element={<Navigate to="/inbox" replace />} />
            <Route path="/runs/:id" element={<RunView />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/review" element={<Navigate to="/approvals" replace />} />
            <Route path="/data" element={<RefData />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-200 bg-white px-4 py-5 sm:px-8">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}
