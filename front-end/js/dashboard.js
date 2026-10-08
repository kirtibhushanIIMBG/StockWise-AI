// Rendering only — every number shown comes from the server response.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const inr = (x) => "₹" + Number(x).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const num = (x) => Number(x).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const icon = (id, cls = "i") => `<svg class="${cls}" aria-hidden="true"><use href="#i-${id}"/></svg>`;

const STATUS_TEXT = {
  "Out of Stock": "Out of stock", "Critical": "Needs urgent attention", "Order Soon": "Time to order more",
  "Healthy": "Healthy", "Excess Stock": "Too much stock", "Low Demand": "Few or no sales",
};
const STATUS_COLOR = {
  "Out of Stock": "#C2361F", "Critical": "#E0674F", "Order Soon": "#D08A1E",
  "Healthy": "#18794E", "Excess Stock": "#2B4BDB", "Low Demand": "#A3AABA",
};
const STATUS_ORDER = ["Out of Stock", "Critical", "Order Soon", "Healthy", "Excess Stock", "Low Demand"];
const pill = (s) => `<span class="pill s-${s.replace(/ /g, "-")}">${STATUS_TEXT[s] || s}</span>`;

function barRows(el, rows, { color = "#2B4BDB", fmt = num, max } = {}) {
  const m = max ?? Math.max(1, ...rows.map((r) => r.value));
  el.innerHTML = rows.length ? rows.map((r) => `
    <div class="bar-row"><span class="lbl" title="${esc(r.label)}">${esc(r.label)}</span>
      <div class="bar-track"><div class="bar" style="width:${(r.value / m) * 100}%;background:${r.color || color}"></div></div>
      <span class="val">${fmt(r.value)}</span></div>`).join("") : `<p class="empty">Nothing to show yet.</p>`;
}

// Signature chart: days of stock vs. delivery day, with the uncovered gap hatched.
function runway(el, products) {
  if (!products.length) {
    el.innerHTML = `<p class="empty">Good news — no product is expected to run out before its next delivery.</p>`;
    return;
  }
  const max = Math.max(1, ...products.map((p) => Math.max(p.lead_time_days, p.coverage_days ?? 0))) * 1.08;
  const pct = (v) => (v / max) * 100;
  el.innerHTML = products.map((p) => {
    const cov = p.coverage_days ?? 0, lt = p.lead_time_days, gap = Math.max(0, lt - cov);
    return `<div class="rw-row" role="img" aria-label="${esc(p.product_name)}: stock lasts ${num(cov)} days, delivery takes ${num(lt)} days">
      <div class="rw-name">${esc(p.product_name)}<small>${STATUS_TEXT[p.status]}</small></div>
      <div class="rw-track">
        <div class="rw-stock" style="width:${pct(cov)}%"></div>
        ${gap > 0 ? `<div class="rw-gap" style="left:${pct(cov)}%;width:${pct(gap)}%"></div>` : ""}
        <div class="rw-truck" style="left:calc(${pct(lt)}% - 1px)" data-label="day ${num(lt)}"></div>
      </div>
      <div class="rw-meta">${num(cov)}d left${gap > 0 ? `<span>${num(gap)}-day gap</span>` : ""}</div>
    </div>`;
  }).join("");
}

const Dashboard = {
  data: null,
  filter: "All",

  render(data) {
    this.data = data;
    const s = data.summary;
    $("#data-source").textContent = data.source === "sample" ? "Demo data · synthetic" :
      data.source === "upload" ? "Your uploaded inventory" : "Your inventory";
    $("#k-total").textContent = s.total_products;
    $("#k-reorder").textContent = s.need_reorder;
    $("#k-risk").textContent = s.at_risk;
    $("#k-cost").textContent = inr(s.total_purchase_cost);

    const alert = $("#risk-alert");
    if (s.at_risk) {
      alert.hidden = false;
      alert.innerHTML = `${icon("alert")}<p><b>${s.at_risk} product${s.at_risk > 1 ? "s" : ""} may run out soon.</b>
        <span class="muted">These products may not last until new stock arrives.</span></p>
        <a href="#health" class="btn quiet" id="alert-see">See which products ${icon("arrow")}</a>`;
      $("#alert-see").onclick = () => this.showUrgent();
    } else alert.hidden = true;

    barRows($("#chart-status"), STATUS_ORDER.filter((k) => s.status_counts[k])
      .map((k) => ({ label: STATUS_TEXT[k], value: s.status_counts[k], color: STATUS_COLOR[k] })));
    runway($("#chart-urgent"), data.products.filter((p) => ["Out of Stock", "Critical"].includes(p.status)).slice(0, 6));
    barRows($("#chart-category"), Object.entries(s.cost_by_category).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ label: k, value: v })), { fmt: inr, color: "#0E1A33" });

    this.renderFilters();
    this.renderTable();
    $("#sc-product").innerHTML = data.products.map((p) => `<option value="${esc(p.sku)}">${esc(p.product_name)}</option>`).join("");
  },

  showUrgent() { this.filter = "Urgent"; this.renderFilters(); this.renderTable(); },

  matches(p) {
    if (this.filter === "All") return true;
    if (this.filter === "Urgent") return ["Out of Stock", "Critical"].includes(p.status);
    return p.status === this.filter;
  },

  renderFilters() {
    const c = this.data.summary.status_counts;
    const opts = [["All", "All products", this.data.products.length], ["Urgent", "May run out soon", this.data.summary.at_risk],
      ...STATUS_ORDER.filter((k) => c[k]).map((k) => [k, STATUS_TEXT[k], c[k]])];
    $("#filters").innerHTML = opts.map(([k, label, n]) =>
      `<button data-f="${k}" class="${k === this.filter ? "on" : ""}" aria-pressed="${k === this.filter}">${label}<span class="count">${n}</span></button>`).join("");
    $("#filters").querySelectorAll("button").forEach((b) => b.onclick = () => { this.filter = b.dataset.f; this.renderFilters(); this.renderTable(); });
  },

  renderTable() {
    const rows = this.data.products.filter((p) => this.matches(p));
    $("#health-table").innerHTML = `<thead><tr><th>Product</th><th class="num">Available</th><th class="num">Daily sales</th>
      <th class="num">Days stock may last</th><th class="num">Supplier takes</th><th>Status</th><th>Recommended action</th></tr></thead><tbody>` +
      (rows.length ? rows.map((p) => `<tr>
        <td><span class="prod">${esc(p.product_name)}</span><span class="sub">${esc(p.sku)} · ${esc(p.category)}</span></td>
        <td class="num">${num(p.current_stock)}${p.incoming_stock ? `<span class="sub">+${num(p.incoming_stock)} on the way</span>` : ""}</td>
        <td class="num">${num(p.avg_daily_demand)}</td>
        <td class="num">${p.coverage_days == null ? "No sales" : num(p.coverage_days) + " days"}</td>
        <td class="num">${num(p.lead_time_days)} days</td>
        <td>${pill(p.status)}</td>
        <td class="action-cell">${esc(p.action)}<br><button class="link-btn" data-sku="${esc(p.sku)}">Why this action? ${icon("arrow")}</button></td></tr>`).join("")
        : `<tr><td colspan="7" class="empty">No products in this group.</td></tr>`) + "</tbody>";
    $("#health-table").querySelectorAll(".link-btn").forEach((b) => b.onclick = () => this.explain(b.dataset.sku));
  },

  explain(sku) {
    const p = this.data.products.find((x) => x.sku === sku);
    const e = p.explanation;
    $("#modal-body").innerHTML = `<h3>${esc(p.product_name)} ${pill(p.status)}</h3>
      <div class="ex-grid">
        <div class="ex-item"><h4>What we found</h4><p>${esc(e.what_we_found)}</p></div>
        <div class="ex-item"><h4>Why it matters</h4><p>${esc(e.why_it_matters)}</p></div>
        <div class="ex-item"><h4>What we recommend</h4><p>${esc(e.what_we_recommend)}</p></div>
        <div class="ex-item cost"><h4>Estimated cost</h4><p>${esc(e.estimated_cost)}</p></div>
      </div>
      <details><summary>How was this calculated?</summary><ul>${e.how_calculated.map((l) => `<li>${esc(l)}</li>`).join("")}</ul></details>`;
    $("#modal").hidden = false;
    $("#modal-close").focus();
  },

  renderPlan(p) {
    $("#plan-out").hidden = false;
    $("#p-spend").textContent = inr(p.total_spend);
    $("#p-left").textContent = inr(p.remaining_budget);
    $("#p-covered").textContent = p.fully_funded;
    $("#p-short").textContent = p.partially_funded + p.not_funded;
    $("#plan-explain").textContent = p.explanation;
    $("#plan-method").textContent = "How we prioritised: " + p.method;
    barRows($("#chart-budget"), [
      { label: "Your budget", value: p.budget, color: "#0E1A33" },
      { label: "Planned purchases", value: p.total_spend, color: "#18794E" },
      { label: "Cost to buy everything", value: p.total_required_cost, color: "#D08A1E" },
    ], { fmt: inr });
    const fund = { "Full": "Fully covered", "Partial": "Partly covered", "Not funded": "Not enough budget" };
    $("#plan-table").innerHTML = `<thead><tr><th class="num">#</th><th>Product</th><th>Status</th><th class="num">Recommended</th><th class="num">Buy now</th>
      <th class="num">Cost</th><th class="num">Still needed</th><th>Budget</th></tr></thead><tbody>` +
      (p.lines.length ? p.lines.map((l) => `<tr><td class="num">${l.priority}</td><td><span class="prod">${esc(l.product_name)}</span></td><td>${pill(l.status)}</td>
        <td class="num">${num(l.recommended_qty)}</td><td class="num"><b>${num(l.buy_qty)}</b></td><td class="num">${inr(l.cost)}</td>
        <td class="num">${l.unfunded_qty ? num(l.unfunded_qty) : "–"}</td><td><span class="fund ${l.funding.replace(/ /g, "-")}">${fund[l.funding]}</span></td></tr>`).join("")
        : `<tr><td colspan="8" class="empty">Nothing needs to be ordered right now.</td></tr>`) + "</tbody>";
    $("#btn-export").href = "/api/export?budget=" + encodeURIComponent(p.budget);
  },

  renderPreview(rows) {
    const cols = [["product_name", "Product", "text"], ["current_stock", "Units in stock", "number"], ["avg_daily_demand", "Daily sales", "number"],
      ["lead_time_days", "Delivery days", "number"], ["unit_cost", "Cost per unit (₹)", "number"], ["safety_stock", "Extra buffer units", "number"],
      ["incoming_stock", "On the way", "number"]];
    $("#preview-table").innerHTML = `<thead><tr>${cols.map((c) => `<th>${c[1]}</th>`).join("")}<th>Note</th></tr></thead><tbody>` +
      rows.map((r, i) => `<tr data-i="${i}" data-sku="${esc(r.sku)}">${cols.map(([k, label, t]) =>
        `<td><input type="${t}" min="0" data-k="${k}" aria-label="${label}" value="${esc(r[k] ?? "")}" class="${r.missing.includes(k) ? "missing" : ""}" placeholder="${r.missing.includes(k) ? "needed" : ""}"></td>`).join("")}
        <td class="sub">${r.is_update ? "Updates existing product. " : "New product. "}${r.missing.length ? "Please fill in: " + esc(r.missing_labels.join(", ")) + "." : ""}</td></tr>`).join("") + "</tbody>";
    $("#preview").hidden = false;
  },

  readPreview() {
    return [...document.querySelectorAll("#preview-table tbody tr")].map((tr) => {
      const o = { sku: tr.dataset.sku };
      tr.querySelectorAll("input").forEach((inp) => {
        const v = inp.value.trim();
        o[inp.dataset.k] = v === "" ? null : inp.type === "number" ? Number(v) : v;
      });
      return o;
    });
  },
};

// Minimal, safe markdown for assistant answers (bold, lists, tables, paragraphs).
function md(text) {
  const lines = esc(text).split("\n");
  let html = "", i = 0;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>");
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim()));
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      html += "<table><thead><tr>" + cells(body[0]).map((c) => `<th>${c}</th>`).join("") + "</tr></thead><tbody>" +
        body.slice(1).map((r) => "<tr>" + cells(r).map((c) => `<td>${c}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
      continue;
    }
    if (/^\s*[-*•] /.test(l)) {
      html += "<ul>";
      while (i < lines.length && /^\s*[-*•] /.test(lines[i])) html += `<li>${inline(lines[i++].replace(/^\s*[-*•] /, ""))}</li>`;
      html += "</ul>";
      continue;
    }
    if (/^#{1,4} /.test(l)) html += `<p><b>${inline(l.replace(/^#+ /, ""))}</b></p>`;
    else if (l.trim()) html += `<p>${inline(l)}</p>`;
    i++;
  }
  return html;
}
