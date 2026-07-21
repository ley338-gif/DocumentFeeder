const state = {
  jobs: [], total: 0, limit: 20, offset: 0, selectedId: null,
  selectedUpdatedAt: null, reviewDirty: false, targets: [], status: "", query: ""
};
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
  if (state.selectedId !== id) state.reviewDirty = false;
  state.selectedId = id;
  renderJobs();
  try { renderDetail(await api(`/v1/jobs/${id}`)); }
  catch (error) { toast(error.message, true); }
}

function renderDetail(job) {
  state.selectedUpdatedAt = job.updated_at;
  state.reviewDirty = false;
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
  $("#review-form")?.addEventListener("input", () => { state.reviewDirty = true; });
  $("#release-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/release`, "POST", "Dokument freigegeben"));
  $("#retry-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/retry`, "POST", "Retry eingeplant"));
}

function reviewForm(job) {
  const routing = job.routing_reference || {};
  const targetOptions = state.targets.filter(target => target.enabled).map(target =>
    `<option value="${target.id}" ${target.id === job.target_system_id ? "selected" : ""}>${esc(target.name)} (${esc(target.kind)})</option>`
  ).join("");
  return `<section class="panel">
    <div class="panel-header"><h3>Manuelle Prüfung</h3></div>
    <form id="review-form" class="review-form" data-id="${job.id}">
      <label>Dokumenttyp<input name="document_type" value="${esc(job.document_type === "unknown" ? "" : job.document_type)}" required></label>
      <label>Bearbeiter<input name="reviewer" autocomplete="name" required></label>
      <label>Namespace<input name="namespace" value="${esc(routing.namespace || "")}" required></label>
      <label>Referenztyp<input name="reference_type" value="${esc(routing.type || "record")}" required></label>
      <label>Zielsystem<select name="target_system_id" required>${targetOptions}</select></label>
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
    routing_reference: { namespace: form.get("namespace"), type: form.get("reference_type"), value: form.get("reference_value") },
    target_system_id: form.get("target_system_id")
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

function switchView(view) {
  $("#documents-view").classList.toggle("hidden", view !== "documents");
  $("#channels-view").classList.toggle("hidden", view !== "channels");
  $("#targets-view").classList.toggle("hidden", view !== "targets");
  document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  if (view === "channels") loadChannels();
  if (view === "targets") loadTargets();
}

async function loadTargets() {
  try {
    state.targets = await api("/v1/target-systems");
    const list = $("#target-list");
    list.innerHTML = state.targets.map(target => `
      <article class="channel-card">
        <div>
          <div class="job-title">
            <span class="badge ${target.enabled ? "delivered" : "received"}">${target.enabled ? "Aktiv" : "Pausiert"}</span>
            ${target.is_default ? '<span class="badge processing">Standard</span>' : ""}
            <h3>${esc(target.name)}</h3>
          </div>
          <span class="channel-path">${target.kind === "http" ? esc(target.endpoint_url) : "data/output"}</span>
          <div class="channel-details">
            <span>Typ <strong>${esc(target.kind)}</strong></span>
            <span>Timeout <strong>${target.timeout_seconds}s</strong></span>
            <span>Letzte Zustellung <strong>${formatTime(target.last_delivery_at)}</strong></span>
            <span>Token <strong>${target.has_bearer_token ? "hinterlegt" : "—"}</strong></span>
          </div>
          ${target.last_error ? `<div class="channel-error">${esc(target.last_error)}</div>` : ""}
        </div>
        <div class="channel-actions">
          ${!target.is_default ? `<button class="button target-default" data-id="${target.id}" type="button">Als Standard</button>` : ""}
          <button class="button target-toggle" data-id="${target.id}" data-enabled="${target.enabled}" type="button" ${target.is_default ? "disabled" : ""}>${target.enabled ? "Pausieren" : "Aktivieren"}</button>
          ${!target.is_default ? `<button class="button danger target-delete" data-id="${target.id}" type="button">Löschen</button>` : ""}
        </div>
      </article>`).join("");
    document.querySelectorAll(".target-default").forEach(button => button.addEventListener("click", () => updateTarget(button.dataset.id, {enabled: true, is_default: true}, "Standardziel geändert")));
    document.querySelectorAll(".target-toggle").forEach(button => button.addEventListener("click", () => updateTarget(button.dataset.id, {enabled: button.dataset.enabled !== "true"}, "Zielsystem aktualisiert")));
    document.querySelectorAll(".target-delete").forEach(button => button.addEventListener("click", () => deleteTarget(button.dataset.id)));
  } catch (error) { toast(error.message, true); }
}

async function updateTarget(id, body, message) {
  try {
    await api(`/v1/target-systems/${id}`, {method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)});
    toast(message); await loadTargets();
  } catch (error) { toast(error.message, true); }
}

async function deleteTarget(id) {
  if (!window.confirm("Zielsystem löschen? Bereits verarbeitete Jobs bleiben erhalten.")) return;
  try { await api(`/v1/target-systems/${id}`, {method: "DELETE"}); toast("Zielsystem gelöscht"); await loadTargets(); }
  catch (error) { toast(error.message, true); }
}

async function createTarget(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const kind = form.get("kind");
  const body = {
    name: form.get("name"), kind,
    endpoint_url: kind === "http" ? form.get("endpoint_url") : null,
    bearer_token: form.get("bearer_token") || null,
    timeout_seconds: Number(form.get("timeout_seconds")),
    enabled: form.get("enabled") === "on", is_default: form.get("is_default") === "on"
  };
  try {
    await api("/v1/target-systems", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)});
    event.currentTarget.reset(); event.currentTarget.elements.enabled.checked = true; event.currentTarget.elements.timeout_seconds.value = 30;
    toast("Zielsystem angelegt"); await loadTargets();
  } catch (error) { toast(error.message, true); }
}

async function loadChannels() {
  try {
    const channels = await api("/v1/input-channels");
    const list = $("#channel-list");
    if (!channels.length) {
      list.innerHTML = '<div class="empty-list"><strong>Noch keine Eingangskanäle</strong><br><span>Lege rechts den ersten Hotfolder an.</span></div>';
      return;
    }
    list.innerHTML = channels.map(channel => `
      <article class="channel-card">
        <div>
          <div class="job-title"><span class="badge ${channel.enabled ? "delivered" : "received"}">${channel.enabled ? "Aktiv" : "Pausiert"}</span><h3>${esc(channel.name)}</h3></div>
          <span class="channel-path">data/${esc(channel.directory)}</span>
          <div class="channel-details">
            <span>Muster <strong>${esc(channel.patterns.join(", "))}</strong></span>
            <span>Letzter Eingang <strong>${formatTime(channel.last_ingested_at)}</strong></span>
          </div>
          ${channel.last_error ? `<div class="channel-error">${esc(channel.last_error)}</div>` : ""}
        </div>
        <div class="channel-actions">
          <button class="button channel-toggle" data-id="${channel.id}" data-enabled="${channel.enabled}" type="button">${channel.enabled ? "Pausieren" : "Aktivieren"}</button>
          <button class="button danger channel-delete" data-id="${channel.id}" data-name="${esc(channel.name)}" type="button">Löschen</button>
        </div>
      </article>`).join("");
    document.querySelectorAll(".channel-toggle").forEach(button => button.addEventListener("click", () => toggleChannel(button.dataset.id, button.dataset.enabled !== "true")));
    document.querySelectorAll(".channel-delete").forEach(button => button.addEventListener("click", () => deleteChannel(button.dataset.id, button.dataset.name)));
  } catch (error) { toast(error.message, true); }
}

async function toggleChannel(id, enabled) {
  try {
    await api(`/v1/input-channels/${id}`, { method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({enabled}) });
    toast(enabled ? "Kanal aktiviert" : "Kanal pausiert"); loadChannels();
  } catch (error) { toast(error.message, true); }
}

async function deleteChannel(id, name) {
  if (!window.confirm(`Eingangskanal „${name}“ löschen? Vorhandene Dateien und Jobs bleiben erhalten.`)) return;
  try {
    await api(`/v1/input-channels/${id}`, { method: "DELETE" });
    toast("Kanal gelöscht"); loadChannels();
  } catch (error) { toast(error.message, true); }
}

async function createChannel(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const body = {
    name: form.get("name"), directory: form.get("directory"),
    patterns: String(form.get("patterns")).split(",").map(value => value.trim()).filter(Boolean),
    enabled: form.get("enabled") === "on"
  };
  try {
    await api("/v1/input-channels", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    event.currentTarget.reset(); event.currentTarget.elements.enabled.checked = true;
    event.currentTarget.elements.patterns.value = "*.pdf, *.txt";
    toast("Eingangskanal angelegt"); loadChannels();
  } catch (error) { toast(error.message, true); }
}

$("#file-upload").addEventListener("change", event => { if (event.target.files[0]) uploadFile(event.target.files[0]); event.target.value = ""; });
$("#refresh").addEventListener("click", () => refreshAll());
$("#status-filter").addEventListener("change", event => { state.status = event.target.value; state.offset = 0; refreshAll(); });
$("#search").addEventListener("input", event => { window.clearTimeout(state.searchTimer); state.searchTimer = window.setTimeout(() => { state.query = event.target.value.trim(); state.offset = 0; loadJobs(); }, 250); });
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadJobs(); });
$("#next").addEventListener("click", () => { state.offset += state.limit; loadJobs(); });
document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
$("#channel-form").addEventListener("submit", createChannel);
$("#reload-channels").addEventListener("click", loadChannels);
$("#target-form").addEventListener("submit", createTarget);
$("#reload-targets").addEventListener("click", loadTargets);

loadTargets();
refreshAll();
window.setInterval(async () => {
  await refreshAll();
  if (state.selectedId) {
    try {
      const job = await api(`/v1/jobs/${state.selectedId}`);
      if (!state.reviewDirty && job.updated_at !== state.selectedUpdatedAt) renderDetail(job);
    } catch (_) { /* transient */ }
  }
}, 4000);
