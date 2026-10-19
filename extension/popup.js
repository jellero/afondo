"use strict";

const server = "http://127.0.0.1:8000";
const button = document.getElementById("check");
const status = document.getElementById("status");

function readVisibleArticle() {
  const article =
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.body;
  const title =
    document.querySelector("h1")?.innerText?.trim() ||
    document.title?.trim() ||
    "Articolo senza titolo";
  const author =
    document.querySelector('meta[name="author"]')?.content || null;
  const outlet =
    document.querySelector('meta[property="og:site_name"]')?.content || null;
  const raw = article.innerText || "";
  const text = raw.trim().slice(0, 30000);
  const lang = (document.documentElement.lang || "it").toLowerCase();
  return {title: title.slice(0, 300), text, author, outlet, language: lang.startsWith("en") ? "en" : "it"};
}

button.addEventListener("click", async () => {
  button.disabled = true;
  status.textContent = "Lettura della scheda...";
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (!tab || !/^https?:\/\//.test(tab.url || "")) {
      throw Error("Apri prima una pagina web HTTP o HTTPS.");
    }
    const response = await chrome.scripting.executeScript({
      target: {tabId: tab.id}, func: readVisibleArticle
    });
    const article = response[0]?.result;
    if (!article || article.text.length < 60) {
      throw Error("Testo insufficiente o contenuto non accessibile sulla pagina.");
    }
    status.textContent = "Invio al motore locale...";
    const result = await fetch(server + "/api/v1/articles", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...article, source_url: tab.url})
    });
    const body = await result.json();
    if (!result.ok) throw Error("AFONDO API: " + JSON.stringify(body.detail || body));
    const url = server + "/?article=" + encodeURIComponent(body.id);
    status.replaceChildren();
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Apri l'analisi AFONDO →";
    status.append("Articolo registrato. ", link);
    await chrome.tabs.create({url});
  } catch (error) {
    status.textContent = "Errore: " + (error.message || error);
  } finally {
    button.disabled = false;
  }
});
