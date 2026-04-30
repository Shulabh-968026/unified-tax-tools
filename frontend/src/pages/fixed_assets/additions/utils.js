export const inr = (v) => {
  const n = Number(v || 0);
  if (!n) return "";
  const s = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return n < 0 ? `(${s})` : s;
};

export const ADJ_FIELDS = [
  "other_expenses",
  "itc_reversed",
  "interest_capitalized",
  "forex_fluctuations",
  "discount_credits",
];

export const ADJ_LABELS = {
  other_expenses:       "Other Expenses",
  itc_reversed:         "ITC Reversed",
  interest_capitalized: "Interest Capitalised",
  forex_fluctuations:   "Forex",
  discount_credits:     "Discounts/Credits",
};

export const PAGE_SIZE_OPTIONS = [10, 25, 50];

export function capitalised(a) {
  return Number(a.invoice_cost || 0)
    + Number(a.other_expenses || 0)
    - Number(a.itc_reversed || 0)
    + Number(a.interest_capitalized || 0)
    + Number(a.forex_fluctuations || 0)
    - Number(a.discount_credits || 0);
}

export const round2 = (n) => Math.round(n * 100) / 100;

// All toggleable columns with sensible defaults. Acc Date, Description,
// Invoice Cost, Total, and IT Block are always visible. Supplier / voucher
// metadata is hidden by default — auditors who need it can flip via the gear.
export const COLUMN_DEFS = [
  { key: "ptu_date",             label: "PTU Date",      default: true  },
  { key: "other_expenses",       label: "Other Exp",     default: true  },
  { key: "itc_reversed",         label: "ITC Reversed",  default: true  },
  { key: "interest_capitalized", label: "Interest Cap",  default: true  },
  { key: "forex_fluctuations",   label: "Forex",         default: false },
  { key: "discount_credits",     label: "Discounts",     default: true  },
  { key: "supplier",             label: "Supplier",      default: false },
  { key: "voucher_no",           label: "Voucher No",    default: false },
  { key: "invoice_no",           label: "Invoice No",    default: false },
  { key: "invoice_date",         label: "Inv Date",      default: false },
];

export const DEFAULT_COL_VIS = Object.fromEntries(COLUMN_DEFS.map(c => [c.key, c.default]));

export const LS_PAGE_SIZE = "fa.additions.pageSize";
export const LS_COL_VIS   = "fa.additions.colVis.v2";   // bumped — defaults changed
