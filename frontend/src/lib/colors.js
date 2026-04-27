// Centralized accent palette used across utility cards, summary tiles & role badges.
// Each entry is a Tailwind class bag for consistent colour usage.
//
// `bg` : tile background (very light tint)
// `border` : border color tint
// `text` : title / icon color
// `chip` : badge background

export const ACCENTS = {
  indigo:  { bg: "bg-indigo-50",  border: "border-indigo-200",  text: "text-indigo-800",  chip: "bg-indigo-100",  fg: "#3730A3" },
  teal:    { bg: "bg-teal-50",    border: "border-teal-200",    text: "text-teal-800",    chip: "bg-teal-100",    fg: "#115E59" },
  amber:   { bg: "bg-amber-50",   border: "border-amber-200",   text: "text-amber-900",   chip: "bg-amber-100",   fg: "#78350F" },
  rose:    { bg: "bg-rose-50",    border: "border-rose-200",    text: "text-rose-800",    chip: "bg-rose-100",    fg: "#9F1239" },
  slate:   { bg: "bg-slate-50",   border: "border-slate-200",   text: "text-slate-800",   chip: "bg-slate-100",   fg: "#1E293B" },
  emerald: { bg: "bg-emerald-50", border: "border-emerald-200", text: "text-emerald-800", chip: "bg-emerald-100", fg: "#065F46" },
  sky:     { bg: "bg-sky-50",     border: "border-sky-200",     text: "text-sky-800",     chip: "bg-sky-100",     fg: "#075985" },
  violet:  { bg: "bg-violet-50",  border: "border-violet-200",  text: "text-violet-800",  chip: "bg-violet-100",  fg: "#5B21B6" },
  fuchsia: { bg: "bg-fuchsia-50", border: "border-fuchsia-200", text: "text-fuchsia-800", chip: "bg-fuchsia-100", fg: "#86198F" },
};

// Map of Clause-44 columns → accent bucket
export const COL_ACCENTS = {
  col2_total: "slate",
  col3: "sky",
  col4: "amber",
  col5: "emerald",
  col6: "teal",
  col7: "rose",
};

export const ROLE_ACCENT = {
  super_admin: { ...ACCENTS.violet, label: "Super Admin" },
  admin:       { ...ACCENTS.indigo, label: "Admin" },
  user:        { ...ACCENTS.slate,  label: "User" },
};
