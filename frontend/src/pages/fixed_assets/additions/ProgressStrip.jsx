import React from "react";
import { CheckCircle2, Circle, CircleDot } from "lucide-react";

export function ProgressStrip({ progress, active, onPick }) {
  const { rows = [], summary = {} } = progress;
  if (!rows.length) {
    return (
      <div className="bg-white border border-[#E5E5E0] px-4 py-2.5 text-[11.5px] text-slate-500">
        No classified additions yet — go to <strong>Ledgers</strong> tab to confirm IT-Block per ledger first.
      </div>
    );
  }
  return (
    <div className="bg-white border border-[#E5E5E0] px-4 py-2.5">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="text-[10px] font-mono uppercase tracking-wider text-slate-500 mr-1">
          Block progress · {summary.done || 0} done · {summary.in_progress || 0} in progress · {summary.not_started || 0} not started
        </div>
        {rows.map(b => {
          const isActive = b.block_label === active;
          const Icon = b.status === "done" ? CheckCircle2 : b.status === "in_progress" ? CircleDot : Circle;
          const cls = b.status === "done"
            ? "text-emerald-700 bg-emerald-50 border-emerald-200"
            : b.status === "in_progress"
              ? "text-amber-700 bg-amber-50 border-amber-200"
              : "text-slate-600 bg-slate-50 border-slate-200";
          return (
            <button
              key={b.block_label}
              data-testid={`fa-progress-${b.block_label.replace(/\W+/g, "-")}`}
              onClick={() => onPick(b.block_label)}
              className={`inline-flex items-center gap-1.5 px-2 py-1 border text-[11px] ${cls} ${isActive ? "ring-2 ring-slate-900 ring-offset-1" : ""}`}
            >
              <Icon size={11}/>
              <span className="truncate max-w-[180px]">{b.block_label}</span>
              <span className="font-mono text-[10px]">{b.reviewed}/{b.total}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
