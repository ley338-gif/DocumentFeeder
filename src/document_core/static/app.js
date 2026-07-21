const state = { jobs: [], total: 0, limit: 20, offset: 0, selectedId: null, status: "", query: "" };
const labels = {
  received: "Eingegangen", processing: "In Verarbeitung", quarantined: "Zu prüfen",
  delivering: "In Zustellung", delivered: "Zugestellt", failed: "Fehlgeschlagen"
};
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "—").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const formatTime = (value) => value ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Anfrage fehlgeschlagen (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) { /* no JSON */ }
    throw new Error(message);
  }
  return response.headers.get("content-type")?.includes("json") ? response.json() : response;
}

function toast(message, error = false) {
  const element = $("#toast");
  element.textContent = message;
  element.className = `toast show${error ? " error" : ""}`;
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.className = "toast", 3200);
}

async function loadHealth() {
  try {
    const health = await api("/health");
    $("#health-dot").className = `health-dot ${health.status}`;
    $("#health-text").textContent = health.status === "ok" ? "API und Datenbank bereit" : "System eingeschränkt";
  } catch (_) {
    $("#health-dot").className = "health-dot error";
    $("#health-text").textContent = "System nicht erreichbar";
  }
}

async function loadStats() {
  const stats = await api("/v1/jobs/stats");
  const order = ["received", "processing", "quarantined", "failed", "delivering", "delivered"];
  $("#stats").innerHTML = order.map(status => `
    <button class="stat ${state.status === status ? "active" : ""}" data-status="${status}">
      <span>${labels[status]}</span><strong>${stats.by_status[status] || 0}</strong>
    </button>`).join("");
  document.querySelectorAll(".stat").forEach(button => button.addEventListener("click", () => {
    state.status = state.status === button.dataset.status ? "" : button.dataset.status;
    state.offset = 0;
    $("#status-filter").value = state.status;
    refreshAll();
  }));
}

async function loadJobs() {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.status) params.append("status", state.status);
  if (state.query) params.set("q", state.query);
  const result = await api(`/v1/jobs?${params}`);
  state.jobs = result.items;
  state.total = result.total;
  renderJobs();
}

function renderJobs() {
  const list = $("#job-list");
  if (!state.jobs.length) {
    list.innerHTML = '<div class="empty-list"><strong>Keine Jobs gefunden</strong><br><span>Filter ändern oder ein Dokument hochladen.</span></div>';
  } else {
    list.innerHTML = state.jobs.map(job => `
      <button class="job-row ${state.selectedId === job.id ? "active" : ""}" data-id="${job.id}">
        <span>
          <span class="job-title"><span class="badge ${job.status}">${labels[job.status]}</span><strong>${esc(job.original_filename)}</strong></span>
          <span class="job-meta"><span>${esc(job.document_type)}</span><span>•</span><span>${esc(job.source)}</span><span>•</span><span>Versuch ${job.attempt_count}</span></span>
        </span>
        <span class="job-time">${formatTime(job.updated_at)}</span>
      </button>`).join("");
    document.querySelectorAll(".job-row").forEach(row => row.addEventListener("click", () => selectJob(row.dataset.id)));
  }
  const from = state.total ? state.offset + 1 : 0;
  const to = Math.min(state.offset + state.limit, state.total);
  $("#page-info").textContent = `${from}–${to} von ${state.total}`;
  $("#previous").disabled = state.offset === 0;
  $("#next").disabled = state.offset + state.limit >= state.total;
}

async function selectJob(id) {
  state.selectedId = id;
  renderJobs();
  try { renderDetail(await api(`/v1/jobs/${id}`)); }
  catch (error) { toast(error.message, true); }
}

function renderDetail(job) {
  const routing = job.routing_reference;
  const canReview = job.status === "quarantined";
  const canRelease = job.status === "quarantined";
  const canRetry = job.status === "failed";
  const previewUrl = `/v1/jobs/${job.id}/content`;
  $("#detail-pane").innerHTML = `
    <div class="detail-header">
      <div class="detail-kicker"><span class="badge ${job.status}">${labels[job.status]}</span><span>${formatTime(job.updated_at)}</span></div>
      <h2>${esc(job.original_filename)}</h2>
      <div class="detail-id">${esc(job.id)}</div>
      <div class="detail-actions">
        <a class="button" href="${previewUrl}?download=true">Herunterladen</a>
        ${canRelease ? '<button id="release-job" class="button primary" type="button">Freigeben</button>' : ""}
        ${canRetry ? '<button id="retry-job" class="button danger" type="button">Erneut versuchen</button>' : ""}
      </div>
    </div>
    <div class="detail-content">
      <section class="panel">
        <div class="panel-header"><h3>Dokumentvorschau</h3><a href="${previewUrl}" target="_blank" rel="noreferrer">Neu öffnen</a></div>
        <iframe class="preview" src="${previewUrl}" title="Vorschau ${esc(job.original_filename)}"></iframe>
      </section>
      <section class="panel">
        <div class="panel-header"><h3>Verarbeitung</h3></div>
        <div class="facts">
          <div class="fact"><span>Dokumenttyp</span><strong>${esc(job.document_type)}</strong></div>
          <div class="fact"><span>Quelle</span><strong>${esc(job.source)}</strong></div>
          <div class="fact"><span>Versuche</span><strong>${job.attempt_count}</strong></div>
          <div class="fact"><span>Nächster Versuch</span><strong>${formatTime(job.next_attempt_at)}</strong></div>
          <div class="fact"><span>Routing</span><strong>${routing ? `${esc(routing.namespace)} / ${esc(routing.type)} / ${esc(routing.value)}` : "—"}</strong></div>
          <div class="fact"><span>Letzter Fehler</span><strong>${esc(job.last_error)}</strong></div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-header"><h3>Metadaten</h3></div>
        <pre class="metadata">${esc(JSON.stringify(job.metadata, null, 2))}</pre>
      </section>
      ${canReview ? reviewForm(job) : ""}
      ${historyPanel(job)}
    </div>`;
  $("#review-form")?.addEventListener("submit", submitReview);
  $("#release-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/release`, "POST", "Dokument freigegeben"));
  $("#retry-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/retry`, "POST", "Retry eingeplant"));
}

function reviewForm(job) {
  const routing = job.routing_reference || {};
  return `<section class="panel">
    <div class="panel-header"><h3>Manuelle Prüfung</h3></div>
    <form id="review-form" class="review-form" data-id="${job.id}">
      <label>Dokumenttyp<input name="document_type" value="${esc(job.document_type === "unknown" ? "" : job.document_type)}" required></label>
      <label>Bearbeiter<input name="reviewer" autocomplete="name" required></label>
      <label>Namespace<input name="namespace" value="${esc(routing.namespace || "")}" required></label>
      <label>Referenztyp<input name="reference_type" value="${esc(routing.type || "record")}" required></label>
      <label class="wide">Referenzwert<input name="reference_value" value="${esc(routing.value || "")}" required></label>
      <label class="wide">Begründung<textarea name="reason" required></textarea></label>
      <button class="button primary" type="submit">Review speichern</button>
    </form>
  </section>`;
}

function historyPanel(job) {
  if (!job.review_history.length) return "";
  return `<section class="panel"><div class="panel-header"><h3>Review-Historie</h3></div><ul class="history">
    ${job.review_history.map(event => `<li><strong>${esc(event.reviewer)}</strong><span>${esc(event.reason)}</span><small>${formatTime(event.reviewed_at)}</small></li>`).join("")}
  </ul></section>`;
}

async function submitReview(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const body = {
    reviewer: form.get("reviewer"), reason: form.get("reason"), document_type: form.get("document_type"),
    routing_reference: { namespace: form.get("namespace"), type: form.get("reference_type"), value: form.get("reference_value") }
  };
  try {
    const job = await api(`/v1/jobs/${event.currentTarget.dataset.id}/review`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    renderDetail(job); toast("Review gespeichert"); await refreshAll(false);
  } catch (error) { toast(error.message, true); }
}

async function mutateJob(path, method, successMessage) {
  try {
    const job = await api(path, { method });
    renderDetail(job); toast(successMessage); await refreshAll(false);
  } catch (error) { toast(error.message, true); }
}

async function uploadFile(file) {
  const body = new FormData(); body.append("file", file);
  try {
    const job = await api("/v1/documents", { method: "POST", body });
    toast("Dokument angenommen"); state.offset = 0; await refreshAll(); await selectJob(job.id);
  } catch (error) { toast(error.message, true); }
}

async function refreshAll(includeStats = true) {
  try { await Promise.all([loadJobs(), includeStats ? loadStats() : Promise.resolve(), loadHealth()]); }
  catch (error) { toast(error.message, true); }
}

$("#file-upload").addEventListener("change", event => { if (event.target.files[0]) uploadFile(event.target.files[0]); event.target.value = ""; });
$("#refresh").addEventListener("click", () => refreshAll());
$("#status-filter").addEventListener("change", event => { state.status = event.target.value; state.offset = 0; refreshAll(); });
$("#search").addEventListener("input", event => { window.clearTimeout(state.searchTimer); state.searchTimer = window.setTimeout(() => { state.query = event.target.value.trim(); state.offset = 0; loadJobs(); }, 250); });
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadJobs(); });
$("#next").addEventListener("click", () => { state.offset += state.limit; loadJobs(); });

refreshAll();
window.setInterval(async () => {
  await refreshAll();
  if (state.selectedId) { try { renderDetail(await api(`/v1/jobs/${state.selectedId}`)); } catch (_) { /* transient */ } }
}, 4000);
