"use strict";

// Admin credentials are deliberately never stored in localStorage or cookies.
let adminToken = "";
let sources = [];
let aiProviders = [];
let selectedId = null;

const $ = id => document.getElementById(id);
const value = id => $(id).value.trim();
const list = input => input.split(",").map(item => item.trim()).filter(Boolean);
const make = (tag, name, content) => {
  const el = document.createElement(tag);
  if (name) el.className = name;
  if (content !== undefined) el.textContent = String(content);
  return el;
};

function flash(message, error = false) {
  const box = $("feedback");
  box.textContent = message;
  box.style.borderColor = error ? "#b56262" : "#438b95";
  box.classList.remove("hidden");
  window.setTimeout(() => box.classList.add("hidden"), 4800);
}

async function api(path, options = {}) {
  if (!adminToken) throw new Error("Non autenticato");
  const response = await fetch("/api/v1/admin" + path, {
    method: options.method || "GET",
    headers: {
      "X-Admin-Token": adminToken,
      ...(options.body ? {"Content-Type": "application/json"} : {}),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail || {});
    throw new Error(message || "HTTP " + response.status);
  }
  return body;
}

function tab(name) {
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === name));
  }
  for (const section of ["overview", "sources", "ai", "monitor"]) {
    $("view-" + section).classList.toggle("hidden", section !== name);
  }
  if (name === "monitor") renderMonitor();
}

document.querySelectorAll("[data-tab]").forEach(button =>
  button.addEventListener("click", () => tab(button.dataset.tab))
);
$("overview-to-sources").addEventListener("click", () => tab("sources"));
$("overview-to-ai").addEventListener("click", () => tab("ai"));

$("login-form").addEventListener("submit", async event => {
  event.preventDefault();
  adminToken = value("login-token");
  $("login-token").value = "";
  $("login-error").textContent = "";
  try {
    await api("/status");
    $("login-overlay").classList.add("hidden");
    $("logout").classList.remove("hidden");
    await reloadAll();
  } catch (error) {
    adminToken = "";
    $("login-error").textContent = "Accesso non riuscito: " + error.message;
  }
});
$("logout").addEventListener("click", () => {
  adminToken = "";
  $("ai-key").value = "";
  $("login-overlay").classList.remove("hidden");
  $("logout").classList.add("hidden");
  $("login-error").textContent = "";
  sources = []; aiProviders = []; selectedId = null;
});

async function reloadAll() {
  const [status, sourceData, aiData] = await Promise.all([
    api("/status"), api("/sources"), api("/ai")
  ]);
  sources = sourceData.items || [];
  aiProviders = aiData.items || [];
  $("metric-sources").textContent = status.sources;
  $("metric-enabled").textContent = status.discovery_enabled;
  $("metric-ai").textContent = status.ai_providers;
  renderSources();
  renderAi();
  renderMonitor();
}

function renderSources() {
  const target = $("source-list"), needle = value("source-search").toLowerCase();
  const matched = sources.filter(s =>
    s.name.toLowerCase().includes(needle) || s.id.includes(needle)
  );
  $("source-count").textContent = matched.length + " fonti visualizzate";
  target.replaceChildren();
  for (const source of matched) {
    const button = make("button", "source");
    button.type = "button";
    const chip = make("span", "pill " + (source.enabled ? "green" : "yellow"),
                      source.enabled ? "Discovery abilitata" : "Non autorizzata / sospesa");
    button.append(chip, make("strong", "", source.name),
                  make("span", "small muted", source.id + " · " + source.type));
    button.addEventListener("click", () => openSource(source));
    target.append(button);
  }
}
$("source-search").addEventListener("input", renderSources);

function setSourceFields(source) {
  $("s-id").value = source?.id || "";
  $("s-id").disabled = Boolean(source);
  $("s-name").value = source?.name || "";
  $("s-type").value = source?.type || "newsroom";
  $("s-priority").value = source?.priority || "pilot";
  $("s-regions").value = (source?.regions || ["IT"]).join(", ");
  $("s-languages").value = (source?.languages || ["it"]).join(", ");
  $("s-site").value = source?.site || "";
  $("s-method").value = source?.discovery_method || "rss";
  $("s-url").value = source?.feed_url || "";
  $("s-active").checked = source?.active ?? false;
  $("delete-source").classList.toggle("hidden", !source);
}

function setGrantFields(grant = {}) {
  $("g-recorded").checked = Boolean(grant.permission_recorded);
  $("g-reference").value = grant.permission_reference || "";
  $("g-by").value = grant.approved_by || "";
  $("g-date").value = grant.reviewed_on || "";
  $("g-expires").value = grant.expires_on || "";
  $("g-endpoint").value = grant.endpoint || "";
  $("g-adapter").value = grant.adapter || "feed";
  $("g-schema").value = grant.api_schema ? JSON.stringify(grant.api_schema, null, 2) : "";
  $("g-env").value = grant.token_env || "";
  $("g-header").value = grant.token_header || "Authorization";
}

function openSource(source) {
  selectedId = source?.id || null;
  $("source-form-title").textContent = source ? "Modifica: " + source.name : "Nuova fonte";
  setSourceFields(source);
  setGrantFields(source?.grant);
  $("grant-state").textContent = source ?
    "Stato: " + source.permission_status : "Salva la fonte prima delle autorizzazioni.";
  $("grant-form").querySelector("button[type=submit]").disabled = !source;
  $("source-editor").classList.remove("hidden");
  $("source-editor").scrollIntoView({behavior: "smooth", block: "start"});
}

$("new-source").addEventListener("click", () => openSource(null));
$("close-source").addEventListener("click", () => $("source-editor").classList.add("hidden"));

$("source-form").addEventListener("submit", async event => {
  event.preventDefault();
  const payload = {
    id: value("s-id"), name: value("s-name"), type: value("s-type"),
    priority: value("s-priority") || "pilot", regions: list(value("s-regions")),
    languages: list(value("s-languages")), site: value("s-site"),
    discovery_method: value("s-method"), feed_url: value("s-url") || null,
    active: $("s-active").checked,
  };
  try {
    const path = selectedId ? "/sources/" + encodeURIComponent(selectedId) : "/sources";
    const result = await api(path, {method: selectedId ? "PUT" : "POST", body: payload});
    flash(result.grant_reset ? "Fonte salvata; verifica permessi da ripetere." : "Fonte salvata.");
    await reloadAll();
    openSource(sources.find(source => source.id === payload.id));
  } catch (error) { flash("Errore di salvataggio: " + error.message, true); }
});

$("delete-source").addEventListener("click", async () => {
  if (!selectedId || !window.confirm("Archiviare questa fonte? Non verrà più sincronizzata.")) return;
  try {
    await api("/sources/" + encodeURIComponent(selectedId), {method: "DELETE"});
    $("source-editor").classList.add("hidden"); selectedId = null;
    await reloadAll(); flash("Fonte archiviata.");
  } catch (error) { flash(error.message, true); }
});

$("grant-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedId) return;
  let apiSchema = null;
  try {
    if (value("g-schema")) apiSchema = JSON.parse(value("g-schema"));
  } catch { return flash("Mapping JSON non valido.", true); }
  const payload = {
    permission_recorded: $("g-recorded").checked,
    permission_reference: value("g-reference"), approved_by: value("g-by"),
    reviewed_on: value("g-date") || null, expires_on: value("g-expires") || null,
    endpoint: value("g-endpoint") || null, adapter: value("g-adapter"),
    api_schema: apiSchema, token_env: value("g-env") || null,
    token_header: value("g-header"),
  };
  try {
    const result = await api("/sources/" + encodeURIComponent(selectedId) + "/grant",
                              {method: "PUT", body: payload});
    flash(result.enabled ? "Autorizzazione salvata: discovery abilitata." :
          "Autorizzazione salvata, ma la fonte non è ancora pronta.");
    await reloadAll();
    openSource(sources.find(s => s.id === selectedId));
  } catch (error) { flash("Permessi non salvati: " + error.message, true); }
});

function renderAi() {
  const root = $("ai-list"); root.replaceChildren();
  if (!aiProviders.length) root.append(make("p", "muted", "Nessun provider AI configurato."));
  for (const ai of aiProviders) {
    const button = make("button", "source");
    button.type = "button";
    button.append(make("span", "pill " + (ai.active ? "green" : ""),
                       ai.active ? "Predefinito" : "Configurato"));
    button.append(make("strong", "", ai.provider.toUpperCase()));
    button.append(make("span", "small muted", "Modello: " + ai.model +
                       " · Chiave: " + (ai.has_key ? "salvata (nascosta)" : "assente")));
    button.addEventListener("click", () => fillAi(ai));
    root.append(button);
  }
}

function fillAi(entry) {
  $("ai-provider").value = entry.provider;
  $("ai-model").value = entry.model;
  $("ai-key").value = "";
  $("ai-active").checked = entry.active;
}

$("ai-provider").addEventListener("change", () => {
  const current = aiProviders.find(p => p.provider === value("ai-provider"));
  if (current) fillAi(current);
  else {
    $("ai-model").value = "";
    $("ai-key").value = "";
    $("ai-active").checked = true;
  }
});

$("ai-form").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    const body = {provider: value("ai-provider"), model: value("ai-model"),
                  api_key: $("ai-key").value || null, active: $("ai-active").checked};
    await api("/ai", {method: "PUT", body});
    $("ai-key").value = ""; // Never retain submitted secrets in the form.
    await reloadAll();
    flash("Provider e chiave salvati in forma cifrata.");
  } catch (error) { flash("Errore AI: " + error.message, true); }
});

$("ai-test").addEventListener("click", async () => {
  try {
    const response = await api("/ai/" + encodeURIComponent(value("ai-provider")) + "/test",
                               {method: "POST"});
    flash(response.connected ?
      "Connessione riuscita al provider (solo elenco modelli)." :
      "Connessione non riuscita (HTTP " + response.http_status + ").",
      !response.connected);
  } catch (error) { flash("Test non riuscito: " + error.message, true); }
});

$("ai-delete").addEventListener("click", async () => {
  const provider = value("ai-provider");
  if (!window.confirm("Eliminare in modo definitivo la chiave cifrata di " + provider + "?")) return;
  try {
    await api("/ai/" + encodeURIComponent(provider), {method: "DELETE"});
    $("ai-key").value = ""; $("ai-model").value = "";
    await reloadAll(); flash("Configurazione eliminata.");
  } catch (error) { flash(error.message, true); }
});

function renderMonitor() {
  const root = $("monitor-list"); root.replaceChildren();
  for (const source of sources) {
    const card = make("div", "source");
    card.append(make("strong", "", source.name));
    const sync = source.sync || {};
    card.append(make("p", "small muted", "Permessi: " + source.permission_status));
    card.append(make("p", "small muted", "Ultima sync: " + (sync.last_sync || "Mai")));
    card.append(make("p", "small muted", "Stato: " + (sync.status || "Nessuna esecuzione")));
    if (sync.error) card.append(make("p", "small bad", "Errore: " + sync.error));
    root.append(card);
  }
}
