import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
export const API = `${BASE}/api`;

export const http = axios.create({
  baseURL: API,
  withCredentials: true,
});

// Auth
export const authMe = () => http.get("/auth/me").then((r) => r.data);
export const authSession = (sessionId) =>
  http.post("/auth/session", null, { headers: { "X-Session-ID": sessionId } }).then((r) => r.data);
export const authLogout = () => http.post("/auth/logout").then((r) => r.data);

// Admin
export const adminListMembers = () => http.get("/admin/users").then((r) => r.data);
export const adminInvite = (email, role) => http.post("/admin/users", { email, role }).then((r) => r.data);
export const adminChangeRole = (userId, role) => http.patch(`/admin/users/${userId}`, { role }).then((r) => r.data);
export const adminRevoke = (userId) => http.delete(`/admin/users/${userId}`).then((r) => r.data);
export const adminCancelInvite = (email) => http.delete("/admin/invitations", { params: { email } }).then((r) => r.data);

// Clients
export const listClients = (archived = false) =>
  http.get("/clients", { params: { archived } }).then((r) => r.data);
export const createClient = (payload) => http.post("/clients", payload).then((r) => r.data);
export const getClient = (id) => http.get(`/clients/${id}`).then((r) => r.data);
export const updateClient = (id, payload) => http.patch(`/clients/${id}`, payload).then((r) => r.data);
export const archiveClient = (id, archived = true) => http.patch(`/clients/${id}`, { archived }).then((r) => r.data);

// Consolidated
export const getConsolidated = (clientId, period) =>
  http.get(`/clients/${clientId}/consolidated`, { params: { period } }).then((r) => r.data);
export const exportConsolidatedUrl = (clientId, period) =>
  `${API}/clients/${clientId}/consolidated/export?period=${encodeURIComponent(period)}`;

// Runs
export const listRuns = (params = {}) =>
  http.get("/runs", { params: { archived: false, ...params } }).then((r) => r.data);

export const uploadRun = ({ jsonFile, xlsxFile, clientId, period, divisionId, onProgress }) => {
  const fd = new FormData();
  fd.append("accounting_json", jsonFile);
  fd.append("ledger_xlsx", xlsxFile);
  fd.append("client_id", clientId);
  fd.append("period", period);
  if (divisionId) fd.append("division_id", divisionId);
  return http.post("/runs", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: onProgress,
  }).then((r) => r.data);
};

export const archiveRun = (id) => http.post(`/runs/${id}/archive`).then((r) => r.data);
export const getRun = (id) => http.get(`/runs/${id}`).then((r) => r.data);
export const generateRun = (id, payload) => http.post(`/runs/${id}/generate`, payload).then((r) => r.data);
export const getTransactions = (id, bucket, ledger) =>
  http.get(`/runs/${id}/transactions`, { params: { bucket, ledger } }).then((r) => r.data);
export const exportRunUrl = (id) => `${API}/runs/${id}/export`;
