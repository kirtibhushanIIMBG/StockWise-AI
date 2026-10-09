// Thin Fetch wrapper. All calculations happen on the server.
const API = {
  async call(path, opts = {}) {
    let res;
    try {
      res = await fetch(path, { credentials: "same-origin", ...opts });
    } catch (e) {
      throw new Error("We couldn't reach StockWise. Please check that the app is running.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.message || "Something went wrong. Please try again.");
    return data;
  },
  json(path, body) {
    return this.call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  },
  health: () => API.call("/api/health"),
  inventory: () => API.call("/api/inventory"),
  sample: () => API.call("/api/sample", { method: "POST" }),
  upload(file) { const fd = new FormData(); fd.append("file", file); return API.call("/api/upload", { method: "POST", body: fd }); },
  parse: (text) => API.json("/api/parse-inventory", { text }),
  cancel: () => API.call("/api/cancel-inventory", { method: "POST" }),
  confirm: (items, apply_default_buffer) => API.json("/api/confirm-inventory", { items, apply_default_buffer }),
  plan: (budget) => API.json("/api/purchase-plan", { budget }),
  scenario: (body) => API.json("/api/scenario", body),
  ask: (question) => API.json("/api/ask", { question }),
};
