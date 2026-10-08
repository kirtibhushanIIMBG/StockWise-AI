// Event wiring for StockWise AI.
const SUGGESTED = ["What should I order today?", "Which products are running out?", "How much should I spend?",
  "Why is Product A at risk?", "What happens if my budget doubles?", "Which products have too much stock?"];

function busy(btn, on, label) {
  if (on) { btn.dataset.label = btn.textContent; btn.textContent = label; btn.disabled = true; btn.classList.add("loading"); }
  else { btn.textContent = btn.dataset.label; btn.disabled = false; btn.classList.remove("loading"); }
}
function showMsg(text, ok = true) {
  const m = $("#add-msg"); m.hidden = false; m.className = "msg " + (ok ? "ok" : "bad"); m.textContent = text;
}
async function refreshPlan() {
  try { Dashboard.renderPlan(await API.plan(Number($("#budget").value) || 0)); } catch (e) { /* plan is optional on load */ }
}

async function init() {
  try {
    const [health, inv] = await Promise.all([API.health(), API.inventory()]);
    Dashboard.render(inv);
    const st = $("#ai-status");
    st.classList.add(health.ai_available ? "on" : "off");
    st.querySelector(".txt").textContent = health.ai_available ? "Assistant connected" : "Assistant offline";
    st.title = health.ai_available ? "AI assistant connected" : "AI questions are unavailable until the assistant is connected.";
    if (!health.ai_available) {
      document.querySelectorAll(".ai-off").forEach((e) => e.hidden = false);
      $("#btn-parse").disabled = true;
    }
    refreshPlan();
  } catch (e) { alert(e.message); }

  $("#chips").innerHTML = SUGGESTED.map((q) => `<button type="button">${q}</button>`).join("");
  $("#chips").querySelectorAll("button").forEach((b) => b.onclick = () => askQuestion(b.textContent));

  $("#see-risk").onclick = () => Dashboard.showUrgent();
  $("#file-input").onchange = (e) => $("#file-label").textContent = e.target.files[0]?.name || "Choose a CSV file…";

  $("#btn-upload").onclick = async (ev) => {
    const f = $("#file-input").files[0];
    if (!f) return showMsg("Please choose a CSV file first.", false);
    busy(ev.target, true, "Reading your file");
    try {
      const d = await API.upload(f);
      Dashboard.render(d); refreshPlan();
      showMsg(`Loaded ${d.loaded} products.` + (d.warnings.length ? " Some rows were skipped: " + d.warnings.join(" ") : ""));
    } catch (e) { showMsg(e.message, false); } finally { busy(ev.target, false); }
  };

  $("#btn-sample").onclick = async () => {
    const d = await API.sample(); Dashboard.render(d); refreshPlan(); showMsg("Demo data loaded.");
  };

  $("#btn-parse").onclick = async (ev) => {
    const text = $("#nl-text").value.trim();
    if (!text) return showMsg("Please describe your stock first.", false);
    busy(ev.target, true, "Reading your description");
    $("#add-msg").hidden = true;
    try {
      const d = await API.parse(text);
      if (!d.rows.length) { $("#preview").hidden = true; return showMsg(d.message, false); }
      Dashboard.renderPreview(d.rows);
      $("#preview").scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) { showMsg(e.message, false); } finally { busy(ev.target, false); }
  };

  $("#btn-cancel").onclick = () => { $("#preview").hidden = true; showMsg("Nothing was changed."); };

  $("#btn-confirm").onclick = async (ev) => {
    busy(ev.target, true, "Saving");
    try {
      const d = await API.confirm(Dashboard.readPreview(), $("#accept-buffer").checked);
      Dashboard.render(d); refreshPlan();
      $("#preview").hidden = true;
      const lines = d.added.map((p) => `${p.product_name}: ${STATUS_TEXT[p.status]}. ${p.action}`);
      showMsg("Saved. " + lines.join(" "));
    } catch (e) { showMsg(e.message, false); } finally { busy(ev.target, false); }
  };

  $("#btn-plan").onclick = async (ev) => {
    const b = Number($("#budget").value);
    if (!(b >= 0)) return alert("Please enter a budget of zero or more.");
    busy(ev.target, true, "Planning");
    try { Dashboard.renderPlan(await API.plan(b)); } catch (e) { alert(e.message); } finally { busy(ev.target, false); }
  };

  $("#btn-sc-budget").onclick = async () => {
    try {
      const r = await API.scenario({ kind: "budget", budget_a: Number($("#sc-a").value), budget_b: Number($("#sc-b").value) });
      const out = $("#sc-out"); out.hidden = false;
      out.innerHTML = `Moving from <b>${inr(r.plan_a.budget)}</b> to <b>${inr(r.plan_b.budget)}</b> lets you buy <b>${num(r.additional_units)} more units</b>
        for an extra <b>${inr(r.additional_spend)}</b>.` +
        (r.newly_covered_products.length ? ` ${r.newly_covered_products.length} more product(s) get new stock.` : "") +
        ` Still unfunded at the higher budget: <b>${num(r.remaining_unmet_units_b)} units</b>.`;
    } catch (e) { alert(e.message); }
  };

  $("#btn-sc-lt").onclick = async () => {
    try {
      const r = await API.scenario({ kind: "lead_time", sku: $("#sc-product").value, new_lead_time: Number($("#sc-lt").value) });
      const b = r.before, a = r.after, out = $("#sc-out"); out.hidden = false;
      out.innerHTML = `<b>${esc(r.product_name)}</b>: if delivery takes <b>${num(a.lead_time_days)} days</b> instead of ${num(b.lead_time_days)},
        the order point moves from ${num(b.reorder_point)} to <b>${num(a.reorder_point)} units</b>, status goes from ${pill(b.status)} to ${pill(a.status)},
        and the recommended order changes from ${num(b.suggested_qty)} to <b>${num(a.suggested_qty)} units</b> (${inr(b.estimated_cost)} → <b>${inr(a.estimated_cost)}</b>).
        Your saved inventory was not changed.`;
    } catch (e) { alert(e.message); }
  };

  $("#ask-form").onsubmit = (e) => { e.preventDefault(); const q = $("#ask-input").value.trim(); if (q) askQuestion(q); };
  $("#modal-close").onclick = () => $("#modal").hidden = true;
  $("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").hidden = true; };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").hidden = true; });

  // Highlight the sidebar link for the section in view.
  const links = [...document.querySelectorAll(".nav a")];
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (en.isIntersecting) links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === "#" + en.target.id));
  }), { rootMargin: "-40% 0px -55% 0px" });
  document.querySelectorAll("main .section").forEach((s) => io.observe(s));
}

async function askQuestion(q) {
  const chat = $("#chat");
  $("#ask-input").value = "";
  chat.querySelector(".empty-chat")?.remove();
  chat.insertAdjacentHTML("beforeend", `<div class="bubble user">${esc(q)}</div>`);
  const wait = document.createElement("div");
  wait.className = "bubble bot"; wait.innerHTML = `<div class="who">${icon("spark")}StockWise recommendation</div><span class="loading">Checking your inventory</span>`;
  chat.appendChild(wait); chat.scrollTop = chat.scrollHeight;
  try {
    const r = await API.ask(q);
    wait.innerHTML = `<div class="who">${icon("spark")}StockWise recommendation</div>${md(r.answer)}`;
  } catch (e) {
    wait.innerHTML = `<div class="who">${icon("spark")}StockWise</div><p>${esc(e.message)}</p>`;
  }
  chat.scrollTop = chat.scrollHeight;
}

init();
