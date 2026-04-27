import { useMemo, useState } from "react";
import {
  Download, Search, Filter as FilterIcon, AlertCircle, CheckCheck, ShieldOff, BadgeCheck,
  Wallet,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { MSME_API as API, formatINR, formatINRCompact, formatDate } from "@/lib/msme-api";

const STATUS_FILTERS = [
  { id: "all", label: "All", icon: FilterIcon },
  { id: "Allowed", label: "Allowed", icon: CheckCheck },
  { id: "Exempt", label: "Exempt", icon: BadgeCheck },
  { id: "Disallowed", label: "Disallowed", icon: ShieldOff },
];

function StatusBadge({ status }) {
  const cls =
    status === "Disallowed" ? "badge-disallowed" :
    status === "Allowed" ? "badge-allowed" :
    status === "Exempt" ? "badge-exempt" :
    "badge-unpaid";
  return (
    <span className={`status-badge ${cls}`} data-testid={`status-${status.toLowerCase()}`}>
      {status}
    </span>
  );
}

function KpiCard({ label, sub, value, hint, active, onClick, tone = "neutral", testId, Icon }) {
  const tones = {
    neutral: {
      ring: "before:bg-gradient-to-b before:from-slate-700 before:to-slate-900",
      tint: "bg-slate-50",
      iconBg: "bg-slate-900 text-white",
      valueColor: "text-slate-900",
      activeBg: "bg-slate-100",
    },
    allowed: {
      ring: "before:bg-gradient-to-b before:from-emerald-400 before:to-emerald-700",
      tint: "bg-emerald-50/60",
      iconBg: "bg-emerald-600 text-white",
      valueColor: "text-emerald-800",
      activeBg: "bg-emerald-100/70",
    },
    exempt: {
      ring: "before:bg-gradient-to-b before:from-blue-400 before:to-blue-700",
      tint: "bg-blue-50/60",
      iconBg: "bg-blue-600 text-white",
      valueColor: "text-blue-800",
      activeBg: "bg-blue-100/70",
    },
    disallowed: {
      ring: "before:bg-gradient-to-b before:from-rose-400 before:to-rose-700",
      tint: "bg-rose-50/60",
      iconBg: "bg-rose-600 text-white",
      valueColor: "text-rose-800",
      activeBg: "bg-rose-100/70",
    },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <button
      onClick={onClick}
      className={`swiss-card relative overflow-hidden text-left p-5 w-full transition
        before:content-[''] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] ${t.ring}
        ${active ? `${t.activeBg} kpi-card-active` : t.tint}
        hover:${t.activeBg}`}
      data-testid={testId}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="section-label">{label}</div>
        <div className={`h-7 w-7 rounded-sm flex items-center justify-center ${t.iconBg}`}>
          {Icon ? <Icon size={14} /> : null}
        </div>
      </div>
      <div className={`mt-4 font-display text-3xl md:text-[32px] font-semibold tracking-tight font-mono ${t.valueColor}`}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-gray-500 font-mono">{sub}</div>}
      {hint && <div className="mt-3 text-[11px] text-gray-600">{hint}</div>}
    </button>
  );
}

export default function ResultsView({ session, results, onRecompute }) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const summary = results?.summary;
  const rows = results?.audit_rows || [];

  const filtered = useMemo(() => {
    let out = rows;
    if (filter !== "all") out = out.filter((r) => r.status === filter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      out = out.filter((r) =>
        (r.ledger_name || "").toLowerCase().includes(q) ||
        (r.voucher_no || "").toLowerCase().includes(q),
      );
    }
    return out;
  }, [rows, filter, search]);

  const exportXlsx = () => {
    if (!session?.id) return;
    window.location.href = `${API}/sessions/${session.id}/export`;
  };

  if (!summary) {
    return (
      <div className="border border-gray-200 bg-gray-50 rounded-sm p-12 text-center">
        <AlertCircle className="mx-auto text-gray-400 mb-3" />
        <div className="text-sm text-gray-700 font-medium">No results yet</div>
        <div className="text-xs text-gray-500 mt-1">
          Complete steps 1–3 then click <span className="font-semibold">Run Computation</span>.
        </div>
        {onRecompute && (
          <button
            onClick={onRecompute}
            className="btn-primary-swiss mt-6"
            data-testid="empty-run-compute-btn"
          >
            Run Computation
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="results-view">
      {/* KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard
          label="Total Outstanding"
          value={formatINR(summary.total_outstanding)}
          sub={formatINRCompact(summary.total_outstanding)}
          hint={`${summary.bill_count} bills · all transactions`}
          active={filter === "all"}
          onClick={() => setFilter("all")}
          tone="neutral"
          Icon={Wallet}
          testId="kpi-card-outstanding"
        />
        <KpiCard
          label="Total Allowed"
          value={formatINR(summary.total_allowed)}
          sub={formatINRCompact(summary.total_allowed)}
          hint={`${summary.allowed_count} bills · paid within statutory limit`}
          active={filter === "Allowed"}
          onClick={() => setFilter("Allowed")}
          tone="allowed"
          Icon={CheckCheck}
          testId="kpi-card-allowed"
        />
        <KpiCard
          label="Total Exempt"
          value={formatINR(summary.total_exempt)}
          sub={formatINRCompact(summary.total_exempt)}
          hint={`${summary.exempt_count} bills · Trading / Medium / Capital Goods`}
          active={filter === "Exempt"}
          onClick={() => setFilter("Exempt")}
          tone="exempt"
          Icon={BadgeCheck}
          testId="kpi-card-exempt"
        />
        <KpiCard
          label="Final Disallowance §43B(h)"
          value={formatINR(summary.final_disallowance)}
          sub={formatINRCompact(summary.final_disallowance)}
          hint={`${summary.disallowed_count} bills · added back to taxable income`}
          active={filter === "Disallowed"}
          onClick={() => setFilter("Disallowed")}
          tone="disallowed"
          Icon={ShieldOff}
          testId="kpi-card-disallowance"
        />
      </div>

      {/* Filters bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1">
          {STATUS_FILTERS.map((s) => {
            const Icon = s.icon;
            const active = filter === s.id;
            const count =
              s.id === "all"
                ? rows.length
                : rows.filter((r) => r.status === s.id).length;
            return (
              <button
                key={s.id}
                onClick={() => setFilter(s.id)}
                className={`flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-sm border ${
                  active
                    ? "bg-gray-900 text-white border-gray-900"
                    : "bg-white text-gray-700 border-gray-200 hover:border-gray-900"
                }`}
                data-testid={`filter-btn-${s.id.toLowerCase()}`}
              >
                <Icon size={13} />
                {s.label}
                <span className={`font-mono ${active ? "text-white/80" : "text-gray-400"}`}>· {count}</span>
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 md:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search creditor or invoice…"
              className="pl-9 rounded-sm h-9"
              data-testid="audit-search-input"
            />
          </div>
          <button
            onClick={exportXlsx}
            className="btn-primary-swiss flex items-center gap-2"
            data-testid="export-excel-btn"
          >
            <Download size={14} /> Download Transaction Detail
          </button>
        </div>
      </div>

      {/* Audit table */}
      <div className="border border-gray-200 rounded-sm overflow-hidden">
        <div className="max-h-[640px] overflow-auto">
          <table className="audit-table" data-testid="audit-table">
            <thead>
              <tr>
                <th style={{ minWidth: 180 }}>Creditor</th>
                <th>Invoice #</th>
                <th>Bill Date</th>
                <th className="num">Amount</th>
                <th style={{ minWidth: 150 }}>Statutory Due Date</th>
                <th>Payment Date</th>
                <th className="num">Delay (Days)</th>
                <th>Status</th>
                <th className="num">Disallowance</th>
                <th style={{ minWidth: 280, maxWidth: 360 }}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} data-testid="audit-table-row">
                  <td>
                    <div className="font-medium text-gray-900">{r.ledger_name}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{r.analysis_type}</div>
                  </td>
                  <td className="font-mono text-xs">{r.voucher_no}</td>
                  <td className="font-mono text-xs">{formatDate(r.voucher_date)}</td>
                  <td className="num">{formatINR(r.bill_amount)}</td>
                  <td className="font-mono text-xs">
                    <div>{formatDate(r.statutory_due_date)}</div>
                    <div className="text-[10px] text-gray-500">{r.due_date_basis}</div>
                    {r.fifo_forced && (
                      <span
                        className="inline-flex items-center mt-1 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-sm border border-amber-300 bg-amber-50 text-amber-800"
                        data-testid="fifo-forced-badge"
                      >
                        FIFO Forced
                      </span>
                    )}
                  </td>
                  <td className="font-mono text-xs">
                    {r.payment_date ? formatDate(r.payment_date) : <span className="text-amber-600">Unpaid</span>}
                  </td>
                  <td className="num">
                    {r.delay_days === null || r.delay_days === undefined
                      ? "—"
                      : r.delay_days > 0
                        ? <span className="text-red-600">+{r.delay_days}</span>
                        : <span className="text-emerald-600">{r.delay_days}</span>}
                  </td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="num font-semibold">
                    {r.status === "Disallowed" ? (
                      <span className="text-red-600">{formatINR(r.disallowance)}</span>
                    ) : (
                      <span className="text-gray-400">₹0</span>
                    )}
                  </td>
                  <td
                    className="text-xs text-gray-700 leading-snug"
                    style={{ minWidth: 280, maxWidth: 360, whiteSpace: "normal", wordBreak: "break-word" }}
                    data-testid="audit-reason-cell"
                  >
                    {r.reason}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-center text-gray-500 py-12 text-sm">
                    No bills match the current filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="bg-gray-50 border-t border-gray-200 px-4 py-2 text-xs text-gray-600 flex justify-between font-mono">
          <span data-testid="audit-row-count">Showing {filtered.length} of {rows.length}</span>
          <span>
            Computed{" "}
            {summary.computed_at ? new Date(summary.computed_at).toLocaleString() : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
