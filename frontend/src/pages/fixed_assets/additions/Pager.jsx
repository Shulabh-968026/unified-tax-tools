import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

export function Pager({ page, totalPages, onPage }) {
  return (
    <div className="flex items-center gap-1">
      <button
        data-testid="fa-add-page-prev"
        onClick={() => onPage(Math.max(1, page - 1))}
        disabled={page <= 1}
        className="p-1 border border-slate-300 disabled:opacity-40 hover:bg-slate-50">
        <ChevronLeft size={12}/>
      </button>
      <button
        data-testid="fa-add-page-next"
        onClick={() => onPage(Math.min(totalPages, page + 1))}
        disabled={page >= totalPages}
        className="p-1 border border-slate-300 disabled:opacity-40 hover:bg-slate-50">
        <ChevronRight size={12}/>
      </button>
    </div>
  );
}
