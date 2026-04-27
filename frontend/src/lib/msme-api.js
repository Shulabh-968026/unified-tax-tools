/* 43B(h) MSME utility API helpers — built on top of the shared auth-aware http client. */
import { http, API } from "@/lib/api";

/* Expose the shared http client for calls that hit non-/msme endpoints (e.g. /clients). */
export { http } from "@/lib/api";

/* axios-like instance that mounts every call under /api/msme/... */
export const api = {
  get: (url, config) => http.get(`/msme${url}`, config),
  post: (url, data, config) => http.post(`/msme${url}`, data, config),
  put: (url, data, config) => http.put(`/msme${url}`, data, config),
  delete: (url, config) => http.delete(`/msme${url}`, config),
};

export const MSME_API = `${API}/msme`;

export const formatINR = (n) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Number(n));
};

export const formatINRCompact = (n) => {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const abs = Math.abs(v);
  if (abs >= 1e7) return `₹${(v / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `₹${(v / 1e3).toFixed(1)} K`;
  return `₹${v.toFixed(0)}`;
};

export const formatDate = (s) => {
  if (!s) return "—";
  try {
    const d = new Date(s);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  } catch {
    return s;
  }
};
