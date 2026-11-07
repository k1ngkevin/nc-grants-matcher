async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail))
        msg = data.detail.map((d) => d.msg).join("; ");
    } catch {}
    const error = new Error(msg);
    error.status = res.status;
    if (res.status === 429) {
      const header = res.headers.get("Retry-After");
      const numeric = header && /^\d+$/.test(header) ? Number(header) : NaN;
      const retry = Number.isFinite(numeric) ? numeric : Math.ceil((Date.parse(header) - Date.now()) / 1000);
      if (Number.isFinite(retry) && retry > 0) {
        error.retryAfterSeconds = retry;
        const minutes = Math.ceil(retry / 60);
        error.message += retry < 60
          ? ` Try again in ${retry} seconds.`
          : ` Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.`;
      } else {
        error.message += " Please wait before trying again.";
      }
    }
    throw error;
  }
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) return res.json();
  if (type.includes("text/csv")) return res.blob();
  return res.text();
}

export const api = {
  meta: () => request("GET", "/api/meta"),
  search: (filters) => request("POST", "/api/search", filters),
  exportCsv: (filters) => request("POST", "/api/export.csv", filters),
  decide: (body) => request("POST", "/api/decisions", body),
  projects: (agency) => request("GET", `/api/agencies/${agency}/projects`),
  addProject: (agency, body) =>
    request("POST", `/api/agencies/${agency}/projects`, body),
  deleteProject: (agency, id) =>
    request("DELETE", `/api/agencies/${agency}/projects/${id}`),
  documents: (agency) => request("GET", `/api/agencies/${agency}/documents`),
  addDocument: (agency, body) =>
    request("POST", `/api/agencies/${agency}/documents`, body),
  deleteDocument: (agency, id) =>
    request("DELETE", `/api/agencies/${agency}/documents/${id}`),
  subscribe: (body) => request("POST", "/api/public/subscriptions", body),
  previewEmail: (body) => request("POST", "/api/subscriptions/preview", body),
  testEmail: (body) => request("POST", "/api/subscriptions/test", body),
  sendFeedback: (body) => request("POST", "/api/feedback", body),
  startResearch: (body) => request("POST", "/api/research", body),
  savedResearch: (opportunity, agency) => request("GET", `/api/research?opportunity_id=${encodeURIComponent(opportunity)}&agency_id=${encodeURIComponent(agency)}`),
  researchJob: (id) => request("GET", `/api/research/jobs/${encodeURIComponent(id)}`),
};

/** A notice attachment served through our server, so it can be shown in the page. */
export function documentUrl(opportunityId, docId, page) {
  return `/api/opportunities/${encodeURIComponent(opportunityId)}/documents/${docId}${page ? `#page=${page}` : ""}`;
}

export function money(n) {
  if (!n) return "Amount not listed";
  if (n >= 1_000_000)
    return `$${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  return `$${Math.round(n / 1000)}K`;
}

export function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export const store = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {}
  },
};
