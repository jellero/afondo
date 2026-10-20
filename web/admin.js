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
  for (const section of ["overview", "sources", "ai", "analysis", "editorial", "monitor"]) {
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
  // Clear sensitive form state and in-memory references on logout.
  window.location.reload();
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
  await reloadArticleQueue();
  await reloadEditorial();
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
  $("g-display").checked = Boolean(grant.public_display_allowed);
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
    public_display_allowed: $("g-display").checked,
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


let articleQueue = [];

async function reloadArticleQueue() {
  try {
    const old = $("analysis-article").value;
    const data = await api("/article-queue?limit=60");
    articleQueue = data.items || [];
    const select = $("analysis-article");
    select.replaceChildren();
    const prompt = make("option", "", "Seleziona un articolo");
    prompt.value = ""; select.append(prompt);
    for (const article of articleQueue) {
      const option = make("option", "",
        article.title + " · " + article.text_chars + " caratteri");
      option.value = article.id;
      if (article.text_chars > data.max_input_chars) option.disabled = true;
      select.append(option);
    }
    if (articleQueue.some(article => article.id === old)) select.value = old;
    if (select.value) await loadExtractedClaims(select.value);
    else clearAnalysis("Seleziona un articolo per eseguire l'estrazione.");
  } catch (error) {
    clearAnalysis("Impossibile caricare gli articoli: " + error.message);
  }
}

function clearAnalysis(message) {
  $("analysis-status").textContent = message;
  $("analysis-runs").replaceChildren();
  $("analysis-candidates").replaceChildren();
}

async function loadExtractedClaims(id) {
  if (!id) return clearAnalysis("Seleziona un articolo.");
  try {
    const data = await api("/articles/" + encodeURIComponent(id) + "/ai");
    const runs = $("analysis-runs");
    runs.replaceChildren();
    const latest = data.runs?.[0];
    if (!latest) {
      clearAnalysis("Questo articolo non è ancora stato elaborato dall'AI.");
      return;
    }
    $("analysis-status").textContent =
      "Ultima elaborazione: " + latest.status + " · " + latest.provider + " / " + latest.model;
    runs.append(make("p", "small muted",
      "Eseguita: " + latest.started_at +
      " · Versione prompt: " + latest.prompt_version +
      " · Token input: " + (latest.input_tokens ?? "n/d") +
      " · Token output: " + (latest.output_tokens ?? "n/d")));
    if (latest.rejected_candidate_count) {
      runs.append(make("p", "small muted", latest.rejected_candidate_count +
        " proposte non ancorate al testo originale sono state scartate."));
    }
    const container = $("analysis-candidates"); container.replaceChildren();
    if (!data.candidates.length) {
      container.append(make("p", "muted", "Nessuna candidata ancorata al testo."));
      return;
    }
    for (const candidate of data.candidates) {
      const card = make("div", "panel");
      card.style.background = "#0e1723";
      card.append(make("span", "pill", candidate.kind + " · " + candidate.review_status));
      card.append(make("p", "", "«" + candidate.quote + "»"));
      card.append(make("p", "muted small", candidate.normalized_claim));
      card.append(make("p", "muted small",
        "Posizione nel testo originale: " +
        candidate.start_offset + "–" + candidate.end_offset));
      if (candidate.review_status === "pending") {
        const actions = make("div", "actions");
        for (const decision of ["accept", "reject"]) {
          if (decision === "accept" && candidate.kind !== "factual") continue;
          const button = make("button", decision === "accept" ? "primary" : "secondary",
                              decision === "accept" ? "Accetta come claim da verificare" :
                                                      "Rifiuta");
          button.type = "button";
          button.addEventListener("click", async () => {
            button.disabled = true;
            try {
              await api("/ai-candidates/" + encodeURIComponent(candidate.id) +
                        "/decision?decision=" + decision, {method: "POST"});
              await loadExtractedClaims(id);
              flash(decision === "accept" ?
                "Affermazione aggiunta alle verifiche, senza assegnare attendibilità." :
                "Candidata rifiutata.");
            } catch (error) { flash(error.message, true); button.disabled = false; }
          });
          actions.append(button);
        }
        card.append(actions);
      }
      container.append(card);
    }
  } catch (error) { clearAnalysis("Errore caricamento AI: " + error.message); }
}

$("analysis-article").addEventListener("change", event =>
  loadExtractedClaims(event.target.value)
);
$("analysis-refresh").addEventListener("click", reloadArticleQueue);

$("analysis-run").addEventListener("click", async () => {
  const id = $("analysis-article").value;
  if (!id) return flash("Seleziona prima un articolo.", true);
  if (!window.confirm(
      "Confermi di avere titolo per inviare il contenuto di questo articolo " +
      "a un provider AI esterno? Questa operazione può generare costi API.")) return;
  const button = $("analysis-run");
  button.disabled = true;
  $("analysis-status").textContent = "Estrazione in corso, attendere la risposta del provider...";
  try {
    const data = await api("/articles/" + encodeURIComponent(id) + "/ai-extract",
                           {method: "POST"});
    $("analysis-status").textContent = "Estrazione registrata.";
    await loadExtractedClaims(id);
    flash((data.candidates?.length || 0) + " candidate estratte. Revisionale prima dell'uso.");
  } catch (error) {
    $("analysis-status").textContent = "Errore nell'estrazione.";
    flash(error.message, true);
  } finally { button.disabled = false; }
});


let editorialRows = [];
async function reloadEditorial() {
  try {
    const selected = $("ed-article").value;
    const result = await api("/editorial?limit=100");
    editorialRows = result.items || [];
    const select = $("ed-article");
    select.replaceChildren();
    const opt = make("option", "", "Seleziona un articolo");
    opt.value = ""; select.append(opt);
    for (const article of editorialRows) {
      const option = make("option", "", article.title + " · " + (article.outlet || "Testo inviato"));
      option.value = article.id; select.append(option);
    }
    if(editorialRows.some(a => a.id === selected)) select.value = selected;
    showEditorial();
  } catch(error) { $("ed-feedback").textContent = "Errore: " + error.message; }
}
function showEditorial() {
  const id = $("ed-article").value;
  const article = editorialRows.find(item => item.id === id);
  $("ed-form").classList.toggle("hidden", !article);
  if(!article) return;
  $("ed-topic").value = article.topic || "";
  $("ed-status").value = article.status || "draft";
  $("ed-featured").checked = Boolean(article.featured);
  $("ed-sensationalistic").checked = Boolean(article.sensationalistic);
  $("ed-out-of-context").checked = Boolean(article.out_of_context);
  $("ed-note").value = article.note || "";
  $("ed-evidence").value = article.evidence_url || "";
  $("ed-feedback").textContent = article.updated_at ?
    "Ultimo aggiornamento: " + article.updated_at : "Nessuna revisione editoriale";
}
$("ed-article").addEventListener("change", showEditorial);
$("ed-form").addEventListener("submit", async event => {
  event.preventDefault();
  const article = $("ed-article").value;
  if(!article) return;
  const body = {
    topic: value("ed-topic") || null,
    status: value("ed-status"),
    featured: $("ed-featured").checked,
    sensationalistic: $("ed-sensationalistic").checked,
    out_of_context: $("ed-out-of-context").checked,
    note: value("ed-note"),
    evidence_url: value("ed-evidence") || null
  };
  const hasWarning = body.sensationalistic || body.out_of_context;
  if (body.status==="approved" && hasWarning &&
      (body.note.length<40 || !body.evidence_url)) {
    return flash("Per pubblicare un avviso devi scrivere una motivazione di 40+ caratteri e collegare un documento.",true);
  }
  if (body.status==="approved" && hasWarning &&
      !window.confirm("Confermi la pubblicazione di questa segnalazione editoriale documentata?")) return;
  try {
    const result = await api("/editorial/" + encodeURIComponent(article),{
      method:"PUT", body
    });
    $("ed-feedback").textContent = "Salvato · " + result.status;
    await reloadEditorial();
    flash(result.visible_warning ? "Segnalazione pubblicata sul portale." : "Scheda editoriale salvata.");
  } catch(error) {flash("Errore editoriale: "+error.message,true)}
});
