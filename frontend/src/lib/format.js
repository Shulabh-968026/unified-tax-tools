// Indian numbering format with 2 decimals, NO rupee symbol.
const INR = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INR_WHOLE = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

export function formatINR(n, opts = {}) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  // `noPaise` — drop the .xx tail; used on KPI tiles where summary
  // aggregates make paise visually noisy and the extra 3 chars push
  // the string past `minFontPx` clipping bounds.
  if (opts && opts.noPaise) return INR_WHOLE.format(Number(n));
  return INR.format(Number(n));
}

export function formatDate(d) {
  if (!d) return "";
  try {
    const dt = new Date(d);
    if (Number.isNaN(dt.getTime())) return d;
    return dt.toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "2-digit" });
  } catch {
    return d;
  }
}

export function formatDateTime(d) {
  if (!d) return "";
  try {
    const dt = new Date(d);
    if (Number.isNaN(dt.getTime())) return d;
    return dt.toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return d;
  }
}
