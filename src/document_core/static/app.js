const state = {
  jobs: [], total: 0, limit: 20, offset: 0, selectedId: null,
  selectedUpdatedAt: null, selectedStatus: null, reviewDirty: false, targets: [],
  jobsSignature: null, statsSignature: null, status: "", query: "", currentUser: null
};
const labels = {
  received: "Eingegangen", processing: "In Verarbeitung", quarantined: "Zu prüfen",
  delivering: "In Zustellung", delivered: "Zugestellt", failed: "Fehlgeschlagen"
};
const documentTypeLabels = {
  invoice: "Rechnung", report: "Bericht", correspondence: "Korrespondenz",
  form: "Formular", unknown: "Nicht erkannt"
};
const roleLabels = { admin: "Administrator", operator: "Operator", viewer: "Betrachter" };
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "—").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));
const formatTime = (value) => value ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";

async function api(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = document.cookie.split("; ").find(item => item.startsWith("document_core_csrf="))?.split("=")[1];
    if (csrf) { options.headers = new Headers(options.headers || {}); options.headers.set("X-CSRF-Token", decodeURIComponent(csrf)); }
  }
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

async function loadStats(force = false) {
  const stats = await api("/v1/jobs/stats");
  const signature = JSON.stringify(stats);
  if (!force && signature === state.statsSignature) return;
  state.statsSignature = signature;
  const order = ["received", "processing", "quarantined", "failed", "delivering", "delivered"];
  $("#stats").innerHTML = order.map(status => `
    <button class="stat ${state.status === status ? "active" : ""}" data-status="${status}">
      <span>${labels[status]}</span><strong>${stats.by_status[status] || 0}</strong>
    </button>`).join("");
  document.querySelectorAll(".stat").forEach(button => button.addEventListener("click", () => {
    state.status = state.status === button.dataset.status ? "" : button.dataset.status;
    state.offset = 0;
    state.jobsSignature = null; state.statsSignature = null;
    $("#status-filter").value = state.status;
    refreshAll();
  }));
}

async function loadJobs(force = false) {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.status) params.append("status", state.status);
  if (state.query) params.set("q", state.query);
  const result = await api(`/v1/jobs?${params}`);
  const signature = JSON.stringify(result);
  if (!force && signature === state.jobsSignature) return;
  state.jobsSignature = signature;
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
  state.selectedStatus = job.status;
  state.reviewDirty = false;
  const routing = job.routing_reference;
  const canWrite = state.currentUser?.role !== "viewer";
  const canReview = canWrite && job.status === "quarantined";
  const canRelease = canWrite && job.status === "quarantined";
  const canRetry = canWrite && job.status === "failed";
  const canDelete = canWrite && ["failed", "processing", "quarantined"].includes(job.status);
  const previewUrl = `/v1/jobs/${job.id}/content`;
  const target = state.targets.find(item => item.id === job.target_system_id);
  const destination = job.metadata.destination_reference || "Wird bei Zustellung erzeugt";
  $("#detail-pane").innerHTML = `
    <div class="detail-header">
      <div class="detail-kicker"><span class="badge ${job.status}">${labels[job.status]}</span><span>${formatTime(job.updated_at)}</span></div>
      <h2>${esc(job.original_filename)}</h2>
      <div class="detail-id">${esc(job.id)}</div>
      <div class="detail-actions">
        <a class="button" href="${previewUrl}?download=true">Herunterladen</a>
        ${canRelease ? '<button id="release-job" class="button primary" type="button">Freigeben</button>' : ""}
        ${canRetry ? '<button id="retry-job" class="button danger" type="button">Erneut versuchen</button>' : ""}
        ${canDelete ? '<button id="delete-job" class="button danger" type="button">Dokument löschen</button>' : ""}
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
          <div class="fact"><span>Zielsystem</span><strong>${esc(target?.name || "Standardziel")}</strong></div>
          <div class="fact"><span>Ablage / Zustellreferenz</span><strong>${esc(destination)}</strong></div>
          <div class="fact"><span>Versuche</span><strong>${job.attempt_count}</strong></div>
          <div class="fact"><span>Nächster Versuch</span><strong>${formatTime(job.next_attempt_at)}</strong></div>
          <div class="fact"><span>Routing</span><strong>${routing ? `${esc(routing.namespace)} / ${esc(routing.type)} / ${esc(routing.value)}` : "—"}</strong></div>
          <div class="fact"><span>Letzter Fehler</span><strong>${esc(job.last_error)}</strong></div>
        </div>
      </section>
      ${classificationPanel(job)}
      <section class="panel">
        <div class="panel-header"><h3>Metadaten</h3></div>
        <pre class="metadata">${esc(JSON.stringify(job.metadata, null, 2))}</pre>
      </section>
      ${canReview ? reviewForm(job) : ""}
      <section class="panel">
        <div class="panel-header"><h3>Aktivitäts- und Zustellprotokoll</h3></div>
        <div id="event-timeline" class="event-timeline"><div class="timeline-empty">Protokoll wird geladen …</div></div>
      </section>
      ${historyPanel(job)}
    </div>`;
  $("#review-form")?.addEventListener("submit", submitReview);
  $("#review-form")?.addEventListener("input", () => { state.reviewDirty = true; });
  $("#release-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/release`, "POST", "Dokument freigegeben"));
  $("#retry-job")?.addEventListener("click", () => mutateJob(`/v1/jobs/${job.id}/retry`, "POST", "Retry eingeplant"));
  $("#delete-job")?.addEventListener("click", () => deleteJob(job));
  loadJobEvents(job.id);
}

function classificationPanel(job) {
  const result = job.metadata?.classification;
  if (!result) return "";
  const numericConfidence = Number(result.confidence);
  const confidence = Number.isFinite(numericConfidence)
    ? Math.max(0, Math.min(1, numericConfidence))
    : 0;
  const percent = Math.round(confidence * 100);
  const level = confidence >= 0.8 ? "high" : confidence >= 0.5 ? "medium" : "low";
  const provider = result.provider === "rules" ? "Regelbasiert" : result.provider || "Unbekannt";
  const typeLabel = documentTypeLabels[result.document_type] || result.document_type;
  const evidence = Array.isArray(result.evidence) ? result.evidence : [];
  return `<section class="panel classification-panel">
    <div class="panel-header"><h3>Klassifizierung</h3><span class="classification-source">${esc(provider)}</span></div>
    <div class="classification-content">
      <div class="classification-summary">
        <div><span>Vorgeschlagener Dokumenttyp</span><strong>${esc(typeLabel)}</strong></div>
        <div class="confidence-value ${level}"><span>Erkennungssicherheit</span><strong>${percent} %</strong></div>
      </div>
      <div class="confidence-track" role="progressbar" aria-label="Erkennungssicherheit" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent}">
        <span class="${level}" style="width:${percent}%"></span>
      </div>
      ${evidence.length ? `<div class="classification-evidence"><span>Erkannte Hinweise</span><div>${evidence.map(item => `<span>${esc(item)}</span>`).join("")}</div></div>` : ""}
      ${confidence < 0.6 ? '<div class="classification-warning">Die Erkennung ist unsicher. Bitte Dokumenttyp und Metadaten manuell prüfen.</div>' : ""}
      <div class="classification-version">Version: ${esc(result.model_version || "—")}</div>
    </div>
  </section>`;
}

async function loadJobEvents(jobId) {
  const timeline = $("#event-timeline");
  if (!timeline) return;
  try {
    const events = await api(`/v1/jobs/${jobId}/events`);
    if (state.selectedId !== jobId || !$("#event-timeline")) return;
    timeline.innerHTML = events.length ? [...events].reverse().map(event => {
      const duration = event.completed_at
        ? Math.max(0, new Date(event.completed_at) - new Date(event.started_at))
        : null;
      const meta = [
        event.target_name,
        event.attempt ? `Versuch ${event.attempt}` : null,
        duration !== null ? `${duration} ms` : null,
        event.delivery_rule ? `Regel: ${event.delivery_rule}` : null
      ].filter(Boolean).map(esc).join(" · ");
      return `<article class="timeline-event ${event.event_type}">
        <span class="timeline-marker" aria-hidden="true"></span>
        <div class="timeline-body">
          <div class="timeline-heading"><strong>${esc(event.message)}</strong><time>${formatTime(event.started_at)}</time></div>
          ${meta ? `<div class="timeline-meta">${meta}</div>` : ""}
          ${event.external_reference ? `<div class="timeline-reference">Referenz: ${esc(event.external_reference)}</div>` : ""}
          ${event.error ? `<div class="timeline-error">${esc(event.error)}</div>` : ""}
        </div>
      </article>`;
    }).join("") : '<div class="timeline-empty">Für diesen Job sind noch keine Ereignisse vorhanden.</div>';
  } catch (error) {
    if (timeline) timeline.innerHTML = `<div class="timeline-error">${esc(error.message)}</div>`;
  }
}

async function deleteJob(job) {
  if (!window.confirm(`„${job.original_filename}“ dauerhaft löschen? Eine laufende Verarbeitung wird abgebrochen; Job und Arbeitskopie werden entfernt.`)) return;
  try {
    await api(`/v1/jobs/${job.id}`, {method: "DELETE"});
    state.selectedId = null; state.selectedStatus = null; state.jobsSignature = null; state.statsSignature = null;
    $("#detail-pane").innerHTML = '<div class="empty-detail"><div class="empty-symbol">✓</div><h2>Dokument gelöscht</h2><p>Job und Arbeitskopie wurden dauerhaft entfernt.</p></div>';
    toast("Dokument gelöscht"); await refreshAll(true, true);
  } catch (error) { toast(error.message, true); }
}

function reviewForm(job) {
  const routing = job.routing_reference || {};
  const suggestion = job.metadata?.classification;
  const targetOptions = state.targets.filter(target => target.enabled).map(target =>
    `<option value="${target.id}" ${target.id === job.target_system_id ? "selected" : ""}>${esc(target.name)} (${esc(target.kind)})</option>`
  ).join("");
  return `<section class="panel">
    <div class="panel-header"><h3>Manuelle Prüfung</h3></div>
    <form id="review-form" class="review-form" data-id="${job.id}">
      <label>Dokumenttyp<input name="document_type" value="${esc(job.document_type === "unknown" ? "" : job.document_type)}" required>${suggestion ? `<small>Vorschlag vorausgefüllt · ${Math.round(Number(suggestion.confidence || 0) * 100)} % Sicherheit</small>` : ""}</label>
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

async function uploadFiles(files) {
  const accepted = [];
  const duplicates = [];
  const failed = [];
  toast(files.length === 1 ? "Dokument wird hochgeladen" : `${files.length} Dokumente werden hochgeladen`);
  for (const file of files) {
    const body = new FormData(); body.append("file", file);
    try {
      const job = await api("/v1/documents", { method: "POST", body });
      (job.duplicate ? duplicates : accepted).push(job);
    } catch (error) {
      failed.push({file, message: error.message});
    }
  }
  state.offset = 0;
  state.jobsSignature = null;
  state.statsSignature = null;
  await refreshAll(true, true);
  const lastJob = accepted.at(-1) || duplicates.at(-1);
  if (lastJob) await selectJob(lastJob.id);
  if (failed.length) {
    toast(`${accepted.length} neu, ${duplicates.length} Duplikate, ${failed.length} fehlgeschlagen: ${failed[0].file.name}`, true);
  } else if (duplicates.length) {
    toast(`${accepted.length} neu angenommen, ${duplicates.length} Duplikate übersprungen`);
  } else {
    toast(accepted.length === 1 ? "Dokument angenommen" : `${accepted.length} Dokumente angenommen`);
  }
}

async function refreshAll(includeStats = true, force = false) {
  try { await Promise.all([loadJobs(force), includeStats ? loadStats(force) : Promise.resolve(), loadHealth()]); }
  catch (error) { toast(error.message, true); }
}

function switchView(view, sourceButton = null) {
  $("#documents-view").classList.toggle("hidden", view !== "documents");
  $("#channels-view").classList.toggle("hidden", view !== "channels");
  $("#targets-view").classList.toggle("hidden", view !== "targets");
  $("#automation-view").classList.toggle("hidden", view !== "automation");
  $("#users-view").classList.toggle("hidden", view !== "users");
  $("#audit-view").classList.toggle("hidden", view !== "audit");
  if (sourceButton) {
    document.querySelectorAll(".nav-button").forEach(button => button.classList.toggle("active", button === sourceButton));
  }
  if (view === "documents" && sourceButton) {
    state.status = sourceButton.dataset.status === "all" ? "" : sourceButton.dataset.status;
    state.offset = 0; state.jobsSignature = null; state.statsSignature = null;
    $("#status-filter").value = state.status; refreshAll();
  }
  if (view === "channels") loadChannels();
  if (view === "targets") loadTargets();
  if (view === "automation") loadRules();
  if (view === "users") loadUsers();
  if (view === "audit") loadAuditEvents();
}

async function loadAuditEvents() {
  const params = new URLSearchParams({limit: "100"});
  const query = $("#audit-search").value.trim(); const outcome = $("#audit-outcome").value;
  if (query) params.set("q", query); if (outcome) params.set("outcome", outcome);
  try {
    const result = await api(`/v1/audit-events?${params}`);
    $("#audit-list").innerHTML = result.items.length ? result.items.map(event => `<article class="audit-row"><span class="audit-status ${event.outcome}"></span><div><strong>${esc(event.actor_username)}</strong><span>${esc(event.action)}</span></div><div><strong>${esc(event.resource_type)}</strong><span>${esc(event.resource_id)}</span></div><span class="badge ${event.outcome === "success" ? "delivered" : "failed"}">${event.outcome === "success" ? "Erfolgreich" : "Fehler"}</span><time>${formatTime(event.created_at)}</time></article>`).join("") : '<div class="empty-list"><strong>Keine Protokolleinträge gefunden</strong></div>';
    $("#audit-page-info").textContent = `${result.total} Einträge`;
  } catch (error) { toast(error.message, true); }
}

async function loadUsers() {
  const users = await api("/v1/users");
  $("#user-list").innerHTML = users.map(user => `<article class="channel-card"><div><div class="job-title"><span class="badge ${user.active ? "delivered" : "received"}">${user.active ? "Aktiv" : "Deaktiviert"}</span><h3>${esc(user.display_name)}</h3></div><span class="channel-path">${esc(user.username)}</span><div class="channel-details"><span>Rolle <strong>${esc(user.role)}</strong></span><span>Letzte Anmeldung <strong>${formatTime(user.last_login_at)}</strong></span></div></div><div class="channel-actions"><select class="user-role" data-id="${user.id}"><option value="viewer" ${user.role === "viewer" ? "selected" : ""}>Betrachter</option><option value="operator" ${user.role === "operator" ? "selected" : ""}>Operator</option><option value="admin" ${user.role === "admin" ? "selected" : ""}>Admin</option></select><button class="button user-password" data-id="${user.id}">Passwort zurücksetzen</button><button class="button user-toggle" data-id="${user.id}" data-active="${user.active}">${user.active ? "Deaktivieren" : "Aktivieren"}</button></div></article>`).join("");
  document.querySelectorAll(".user-role").forEach(element => element.addEventListener("change", () => updateUser(element.dataset.id, {role: element.value})));
  document.querySelectorAll(".user-toggle").forEach(button => button.addEventListener("click", () => updateUser(button.dataset.id, {active: button.dataset.active !== "true"})));
  document.querySelectorAll(".user-password").forEach(button => button.addEventListener("click", () => resetPassword(button.dataset.id)));
}

async function updateUser(id, body) { try { await api(`/v1/users/${id}`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}); toast("Benutzer aktualisiert"); await loadUsers(); } catch (error) { toast(error.message, true); } }
async function resetPassword(id) { const password = window.prompt("Neues Passwort (mindestens 12 Zeichen)"); if (!password) return; await updateUser(id, {password}); }
async function createUser(event) { event.preventDefault(); const userForm = event.currentTarget; const form = new FormData(userForm); try { await api("/v1/users", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(form))}); userForm.reset(); toast("Benutzer angelegt"); await loadUsers(); } catch (error) { toast(error.message, true); } }

async function initializeSession() {
  try {
    state.currentUser = await api("/v1/auth/me");
    $("#login-screen").classList.add("hidden");
    if (state.currentUser.role === "admin") $("#admin-nav").classList.remove("hidden");
    document.body.classList.toggle("read-only-config", state.currentUser.role !== "admin");
    document.body.classList.toggle("viewer-mode", state.currentUser.role === "viewer");
    renderAccount();
    loadTargets(); updatePathPreview(); refreshAll();
  } catch (_) { $("#login-screen").classList.remove("hidden"); }
}

function renderAccount() {
  const user = state.currentUser;
  $("#account-name").textContent = user.display_name;
  $("#account-role").textContent = roleLabels[user.role] || user.role;
  $("#account-avatar").textContent = user.display_name.trim().slice(0, 2).toUpperCase();
  $("#profile-username").textContent = user.username;
  $("#profile-role").textContent = roleLabels[user.role] || user.role;
  $("#profile-form").elements.display_name.value = user.display_name;
}

async function saveProfile(event) {
  event.preventDefault();
  const profileForm = event.currentTarget;
  const form = new FormData(profileForm);
  const body = {display_name: form.get("display_name")};
  const passwordChanged = Boolean(form.get("password"));
  if (passwordChanged) body.password = form.get("password");
  try { state.currentUser = await api("/v1/auth/me", {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}); profileForm.elements.password.value = ""; renderAccount(); if (passwordChanged) { window.alert("Passwort geändert. Bitte melde dich erneut an."); window.location.reload(); } else { toast("Profil gespeichert"); } }
  catch (error) { toast(error.message, true); }
}

async function logout() { try { await api("/v1/auth/logout", {method:"POST"}); window.location.reload(); } catch (error) { toast(error.message, true); } }

async function login(event) {
  event.preventDefault(); const form = new FormData(event.currentTarget);
  try { await api("/v1/auth/login", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(Object.fromEntries(form))}); $("#login-error").classList.add("hidden"); await initializeSession(); }
  catch (error) { $("#login-error").textContent = error.message; $("#login-error").classList.remove("hidden"); }
}

async function loadTargets() {
  try {
    state.targets = await api("/v1/target-systems");
    const ruleTarget = $("#rule-form")?.elements.target_system_id;
    if (ruleTarget) ruleTarget.innerHTML = state.targets.filter(target => target.enabled).map(target => `<option value="${target.id}">${esc(target.name)}</option>`).join("");
    const list = $("#target-list");
    list.innerHTML = state.targets.map(target => `
      <article class="channel-card">
        <div>
          <div class="job-title">
            <span class="badge ${target.enabled ? "delivered" : "received"}">${target.enabled ? "Aktiv" : "Pausiert"}</span>
            ${target.is_default ? '<span class="badge processing">Standard</span>' : ""}
            <h3>${esc(target.name)}</h3>
          </div>
          <span class="channel-path">${target.kind === "http" ? esc(target.endpoint_url) : `data/${esc(target.directory)}`}</span>
          <div class="channel-details">
            <span>Typ <strong>${esc(target.kind)}</strong></span>
            <span>Timeout <strong>${target.timeout_seconds}s</strong></span>
            <span>Letzte Zustellung <strong>${formatTime(target.last_delivery_at)}</strong></span>
            <span>Token <strong>${target.has_bearer_token ? "hinterlegt" : "—"}</strong></span>
            ${target.kind === "filesystem" ? `<span>Ablage <strong>data/${esc(target.directory)}/${esc(target.path_template)}</strong></span>` : ""}
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
  const targetForm = event.currentTarget;
  const form = new FormData(targetForm);
  const kind = form.get("kind");
  const body = {
    name: form.get("name"), kind,
    endpoint_url: kind === "http" ? form.get("endpoint_url") : null,
    directory: form.get("directory") || "output",
    path_template: form.get("path_template") || "{document_type}/{job_id}",
    bearer_token: form.get("bearer_token") || null,
    timeout_seconds: Number(form.get("timeout_seconds")),
    enabled: form.get("enabled") === "on", is_default: form.get("is_default") === "on"
  };
  try {
    await api("/v1/target-systems", {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body)});
    targetForm.reset(); targetForm.elements.enabled.checked = true; targetForm.elements.timeout_seconds.value = 30;
    toast("Zielsystem angelegt"); await loadTargets();
  } catch (error) { toast(error.message, true); }
}

async function loadRules() {
  try {
    await loadTargets();
    const rules = await api("/v1/delivery-rules");
    $("#rule-list").innerHTML = rules.length ? rules.map(rule => {
      const target = state.targets.find(item => item.id === rule.target_system_id);
      return `<article class="channel-card"><div><div class="job-title"><span class="badge ${rule.enabled ? "delivered" : "received"}">${rule.enabled ? "Aktiv" : "Pausiert"}</span><h3>${esc(rule.name)}</h3></div><p class="rule-sentence">Wenn <strong>${esc(rule.document_type)}</strong>, dann an <strong>${esc(target?.name || "Unbekannt")}</strong>.</p><span class="channel-path">${esc(rule.path_template || target?.path_template || "Zielvorlage")}</span></div><div class="channel-actions"><button class="button rule-toggle" data-id="${rule.id}" data-enabled="${rule.enabled}" type="button">${rule.enabled ? "Pausieren" : "Aktivieren"}</button><button class="button danger rule-delete" data-id="${rule.id}" type="button">Löschen</button></div></article>`;
    }).join("") : '<div class="empty-list"><strong>Noch keine Ablageregeln</strong><br><span>Ohne Regel gilt das Standardziel.</span></div>';
    document.querySelectorAll(".rule-toggle").forEach(button => button.addEventListener("click", () => updateRule(button.dataset.id, {enabled: button.dataset.enabled !== "true"})));
    document.querySelectorAll(".rule-delete").forEach(button => button.addEventListener("click", () => deleteRule(button.dataset.id)));
  } catch (error) { toast(error.message, true); }
}

async function updateRule(id, body) {
  try { await api(`/v1/delivery-rules/${id}`, {method:"PATCH", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}); toast("Regel aktualisiert"); await loadRules(); }
  catch (error) { toast(error.message, true); }
}

async function deleteRule(id) {
  if (!window.confirm("Ablageregel löschen?")) return;
  try { await api(`/v1/delivery-rules/${id}`, {method:"DELETE"}); toast("Regel gelöscht"); await loadRules(); }
  catch (error) { toast(error.message, true); }
}

async function createRule(event) {
  event.preventDefault(); const ruleForm = event.currentTarget; const form = new FormData(ruleForm);
  const body = {name:form.get("name"), document_type:form.get("document_type"), target_system_id:form.get("target_system_id"), path_template:form.get("path_template") || null, priority:Number(form.get("priority")), enabled:form.get("enabled") === "on"};
  try { await api("/v1/delivery-rules", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}); ruleForm.reset(); ruleForm.elements.enabled.checked = true; ruleForm.elements.priority.value = 100; updatePathPreview(); toast("Ablageregel angelegt"); await loadRules(); }
  catch (error) { toast(error.message, true); }
}

function updatePathPreview() {
  const input = $("#rule-path-template");
  const preview = $("#rule-path-preview");
  if (!input || !preview) return;
  const examples = {
    year: "2026", month: "07", supplier_name: "Beispiel_GmbH",
    invoice_number: "RE12345", document_type: "invoice", extension: ".pdf",
    job_id: "job-123", reference: "REF-42"
  };
  preview.textContent = input.value.replace(/\{([a-z_]+)\}/g, (match, key) => examples[key] || match);
}

function insertPathPlaceholder(button) {
  const input = $("#rule-path-template");
  if (!input) return;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  input.setRangeText(button.dataset.placeholder, start, end, "end");
  input.focus();
  updatePathPreview();
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
  const channelForm = event.currentTarget;
  const form = new FormData(channelForm);
  const body = {
    name: form.get("name"), directory: form.get("directory"),
    patterns: String(form.get("patterns")).split(",").map(value => value.trim()).filter(Boolean),
    enabled: form.get("enabled") === "on"
  };
  try {
    await api("/v1/input-channels", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
    channelForm.reset(); channelForm.elements.enabled.checked = true;
    channelForm.elements.patterns.value = "*.pdf, *.txt";
    toast("Eingangskanal angelegt"); loadChannels();
  } catch (error) { toast(error.message, true); }
}

$("#file-upload").addEventListener("change", event => {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  if (files.length) uploadFiles(files);
});
$("#refresh").addEventListener("click", () => refreshAll(true, true));
$("#status-filter").addEventListener("change", event => { state.status = event.target.value; state.offset = 0; state.jobsSignature = null; state.statsSignature = null; refreshAll(); });
$("#search").addEventListener("input", event => { window.clearTimeout(state.searchTimer); state.searchTimer = window.setTimeout(() => { state.query = event.target.value.trim(); state.offset = 0; state.jobsSignature = null; loadJobs(); }, 250); });
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); state.jobsSignature = null; loadJobs(); });
$("#next").addEventListener("click", () => { state.offset += state.limit; state.jobsSignature = null; loadJobs(); });
document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view, button)));
$("#channel-form").addEventListener("submit", createChannel);
$("#reload-channels").addEventListener("click", loadChannels);
$("#target-form").addEventListener("submit", createTarget);
$("#reload-targets").addEventListener("click", loadTargets);
$("#rule-form").addEventListener("submit", createRule);
$("#user-form").addEventListener("submit", createUser);
$("#reload-users").addEventListener("click", loadUsers);
$("#reload-audit").addEventListener("click", loadAuditEvents);
$("#audit-outcome").addEventListener("change", loadAuditEvents);
$("#audit-search").addEventListener("input", event => { window.clearTimeout(state.auditTimer); state.auditTimer = window.setTimeout(loadAuditEvents, 250); });
$("#login-form").addEventListener("submit", login);
$("#profile-form").addEventListener("submit", saveProfile);
$("#logout-button").addEventListener("click", logout);
$("#account-button").addEventListener("click", () => { const popover = $("#account-popover"); popover.classList.toggle("hidden"); $("#account-button").setAttribute("aria-expanded", String(!popover.classList.contains("hidden"))); });
$("#reload-rules").addEventListener("click", loadRules);
$("#rule-path-template").addEventListener("input", updatePathPreview);
document.querySelectorAll(".template-chips button").forEach(button => button.addEventListener("click", () => insertPathPlaceholder(button)));
initializeSession();
window.setInterval(async () => {
  if (!state.currentUser) return;
  await refreshAll();
  if (state.selectedId && ["received", "processing", "delivering"].includes(state.selectedStatus)) {
    try {
      const job = await api(`/v1/jobs/${state.selectedId}`);
      if (!state.reviewDirty && job.updated_at !== state.selectedUpdatedAt) renderDetail(job);
    } catch (_) { /* transient */ }
  }
}, 4000);
