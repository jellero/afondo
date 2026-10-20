"use strict";

// Feed is already indexed server-side. Browsing never invokes an AI model.
const $ = id => document.getElementById(id);
const TOPIC_LABELS = {
  tutti:"Tutte", attualita:"Attualità", politica:"Politica", economia:"Economia",
  mondo:"Mondo", tecnologia:"Tecnologia", scienza:"Scienza", salute:"Salute",
  ambiente:"Ambiente", sport:"Sport", cultura:"Cultura"
};
const TOPIC_GLYPHS = {
  attualita:"◎", politica:"§", economia:"↗", mondo:"◌", tecnologia:"⌘",
  scienza:"✳", salute:"+", ambiente:"❦", sport:"◉", cultura:"◇"
};
const STATUS_COLOR = {
  unverified:"slate", supported:"green", caution:"amber", disputed:"red"
};
let state = {topic:"tutti", sort:"recenti", query:"", limit:24};
let allItems = [];
let pageItems = [];
let heroId = null;
let lastFocused = null;
let debounce = 0;
let latestRequest = 0;
let isLoading = false;

const el = (tag, css, text) => {
  const n = document.createElement(tag);
  if(css) n.className = css;
  if(text !== undefined) n.textContent = String(text);
  return n;
};
const safeLink = raw => {
  try {
    const url = new URL(raw);
    return ["https:","http:"].includes(url.protocol) ? url.href : null;
  } catch { return null; }
};
const relativeDate = iso => {
  if(!iso) return "Data non disponibile";
  const date = new Date(iso), diff = Date.now() - date.getTime();
  if(!Number.isFinite(diff)) return "Data non disponibile";
  const mins = Math.floor(diff/60000);
  if(mins >= 0 && mins < 1) return "Ora";
  if(mins >= 0 && mins < 60) return mins + " min fa";
  if(mins >= 0 && mins < 1440) return Math.floor(mins/60) + " h fa";
  try { return date.toLocaleDateString("it-IT",{day:"numeric",month:"short",year:"numeric"}); }
  catch { return "Data non disponibile"; }
};
const indicator = (item, hero=false) => {
  const value = item.indicator || {};
  const dot = el("span","signal-dot "+(STATUS_COLOR[value.state] || "slate"));
  dot.setAttribute("aria-hidden","true");
  const wrapper = el("span",hero ? "hero-indicator" : "indicator");
  wrapper.append(dot, el("span","",value.label || "Non ancora verificata"));
  return wrapper;
};
const link = (url, text, css) => {
  const a = el("a",css,text);
  a.href = url; a.target="_blank"; a.rel="noopener noreferrer";
  return a;
};
const articleURL = item => item.kind === "article" && item.article_id ?
  "/analyze?article=" + encodeURIComponent(item.article_id) : safeLink(item.url);

function drawHero(items) {
  const hero = $("hero");
  const featured = items.find(item=>item.featured) || items[0];
  heroId = featured?.id || null;
  hero.replaceChildren();
  const inside = el("div","hero-inner");
  if(!featured){
    hero.className = "hero";
    inside.append(
      el("span","hero-kicker","AFONDO / LETTURA CONSAPEVOLE"),
      el("h3","","Dietro ogni titolo c'è una storia. E delle prove."),
      el("p","","Il tuo spazio per leggere le notizie con più contesto.")
    );
    const a = el("a","hero-link","Inizia con una notizia →");a.href="/analyze";inside.append(a);
    hero.append(inside);
    $("spotlight-caption").textContent = "Il contesto prima dei giudizi";
    return;
  }
  hero.className="hero hero-story";
  inside.append(el("span","hero-kicker",
    (TOPIC_LABELS[featured.topic] || "Attualità").toUpperCase() + " / " +
    featured.source.toUpperCase()));
  inside.append(el("h3","",featured.title));
  inside.append(el("p","",featured.summary));
  inside.append(indicator(featured,true));
  const open = el("button","hero-link","Esplora la notizia →");
  open.type="button";open.addEventListener("click",()=>openDrawer(featured));
  inside.append(open);hero.append(inside);
  $("spotlight-caption").textContent = featured.featured ? "Selezione editoriale" : "Dal flusso delle notizie";
}

function drawCard(item) {
  const card=el("article","news-card");
  const thumb=el("div","news-icon "+item.topic,TOPIC_GLYPHS[item.topic] || "◎");
  thumb.setAttribute("aria-hidden","true");
  const body=el("div","news-body");
  const meta=el("div","article-meta");
  meta.append(el("span","topic-tag",TOPIC_LABELS[item.topic] || "Attualità"));
  meta.append(el("span","","·"),el("span","",item.source));
  meta.append(el("span","","·"),el("span","",relativeDate(item.published_at)));
  const headline=el("h3","news-title");
  const open=el("button","",item.title);
  open.type="button";open.setAttribute("aria-label","Apri scheda: "+item.title);
  open.addEventListener("click",()=>openDrawer(item));
  headline.append(open);
  const hints=el("div","article-hints");
  hints.append(indicator(item));
  if(item.preanalysis==="candidate_review_pending")
    hints.append(el("span","coverage-note","· Preanalisi AI completata: revisione in corso"));
  if(item.coverage_sources >= 2) hints.append(
    el("span","coverage-note","Ripresa da "+item.coverage_sources+" fonti nel catalogo")
  );
  body.append(meta,headline,hints);
  const chevron=el("span","card-chevron","›");chevron.setAttribute("aria-hidden","true");
  card.append(thumb,body,chevron);
  return card;
}
function emptyMessage(){
  const box=el("div","empty-state");
  box.append(el("div","empty-glyph","◎"));
  let title="Nessuna notizia disponibile";
  let body="AFONDO mostrerà qui i titoli delle fonti autorizzate. Non pubblichiamo notizie inventate né classificazioni non verificate.";
  if(state.sort === "tendenza"){
    title="Nessun tema ripreso da più fonti";
    body="La sezione In tendenza si basa sulla copertura di almeno due fonti diverse negli ultimi tre giorni. Non misura le visualizzazioni o la popolarità.";
  }else if(state.sort === "verificate"){
    title="Nessuna analisi conclusa";
    body="Gli indicatori compaiono solo quando esistono prove revisionate o segnalazioni editoriali motivate.";
  }else if(state.query) {
    title="Nessun risultato per questa ricerca";
    body="Prova parole più generali o scegli un'altra categoria.";
  }else if(state.topic!=="tutti"){
    title="Non ci sono ancora notizie in "+(TOPIC_LABELS[state.topic]||"questa categoria");
    body="Le notizie verranno mostrate quando entreranno dalle fonti autorizzate.";
  }
  box.append(el("h3","",title),el("p","",body));
  const a=el("a","","Verifica una notizia →");a.href="/analyze";box.append(a);
  return box;
}
function drawFeed(){
  const list=$("news-list");
  list.replaceChildren();
  const filtered=allItems.filter(item=>item.id!==heroId);
  pageItems=filtered.slice(0,state.limit);
  if(pageItems.length===0) list.append(emptyMessage());
  else pageItems.forEach(item=>list.append(drawCard(item)));
  $("load-more").hidden = filtered.length <= state.limit;
}

async function refresh(){
  const request=++latestRequest;
  isLoading=true;
  $("count").textContent="Aggiornamento...";
  const params=new URLSearchParams({topic:state.topic,sort:state.sort,q:state.query,limit:"100"});
  try{
    const resp=await fetch("/api/v1/feed?"+params.toString(),{headers:{"Accept":"application/json"}});
    if(!resp.ok) throw new Error("Servizio temporaneamente non disponibile");
    const data=await resp.json();
    if(request!==latestRequest) return;
    allItems=data.items||[];
    $("count").textContent=(data.total||0)+" notizie";
    $("feed-helper").textContent = state.sort==="tendenza" ?
      "In tendenza = più fonti che trattano titoli simili negli ultimi 3 giorni; non significa più letta o verificata." :
      state.sort==="verificate" ?
      "Analisi disponibili: indicatori parziali basati su prove revisionate o segnalazioni editoriali documentate." :
      "Stati già disponibili all'apertura del portale. I nuovi titoli da feed non sono automaticamente verificati.";
    drawHero(allItems);
    drawFeed();
  }catch(error){
    if(request!==latestRequest) return;
    allItems=[];drawHero([]);
    $("news-list").replaceChildren(emptyMessage());
    $("count").textContent="Connessione non disponibile";
    $("feed-helper").textContent="Controlla che il backend AFONDO sia avviato.";
  }finally{if(request===latestRequest)isLoading=false}
}

function setTopic(topic){
  state.topic=topic;state.limit=24;
  for(const b of document.querySelectorAll("[data-topic]")){
    const selected=b.dataset.topic===topic;
    b.classList.toggle("active",selected);
    b.setAttribute("aria-pressed",String(selected));
  }
  refresh();
}
function setSort(sort){
  state.sort=sort;state.limit=24;
  for(const b of document.querySelectorAll("[data-sort]")){
    const selected=b.dataset.sort===sort;
    b.classList.toggle("active",selected);
    b.setAttribute("aria-pressed",String(selected));
  }
  refresh();
}

function openDrawer(item){
  const layer=$("drawer-layer"), content=$("drawer-body");
  lastFocused=document.activeElement;
  content.replaceChildren();
  content.append(el("div","drawer-topic",TOPIC_LABELS[item.topic]||"Attualità"));
  content.append(el("h2","",item.title));
  content.append(el("p","drawer-meta",item.source+" · "+relativeDate(item.published_at)));
  const assessment=el("section","drawer-assessment");
  const title=el("div","drawer-dot");
  title.append(indicator(item));
  assessment.append(title);
  const signal=item.indicator||{};
  if(signal.reviewed && signal.flags?.length){
    const summary=el("p","",signal.flags.map(flag=>flag.label).join(" · "));
    assessment.append(summary);
    if(signal.note) assessment.append(el("p","",signal.note));
    const u=safeLink(signal.evidence_url);
    if(u) assessment.append(link(u,"Riferimento a supporto della valutazione ↗","drawer-link secondary"));
  } else if(signal.state==="supported"||signal.state==="disputed"){
    assessment.append(el("p","",
      "Questo indicatore riguarda soltanto le affermazioni con prove esaminate. Non è un voto complessivo alla testata o all'autore."));
  } else assessment.append(el("p","",
    "Non abbiamo ancora elementi sufficienti per valutare il contenuto di questa notizia. L'assenza di analisi non implica che sia falsa."));
  content.append(assessment);
  if(item.preanalysis==="candidate_review_pending")
    content.append(el("p","drawer-copy",
      "AFONDO ha già individuato affermazioni candidate tramite AI. La revisione e il confronto con le prove sono ancora in corso: non è una certificazione di attendibilità."));
  content.append(el("h3","","Che cosa sappiamo"));
  content.append(el("p","drawer-copy",item.summary));
  if(item.coverage_sources>=2) content.append(el("p","drawer-copy",
    "Titoli simili sono stati rilevati da "+item.coverage_sources+
    " fonti nel catalogo. Questo dato indica copertura, non conferma indipendente."));
  if(item.kind==="article"&&item.article_id){
    const a=el("a","drawer-link","Apri le affermazioni e le prove registrate →");
    a.href="/analyze?article="+encodeURIComponent(item.article_id);
    content.append(a);
  }
  const profiles=item.history||{};
  if(profiles.outlet || profiles.author){
    content.append(el("h3","","Storico e rettifiche"));
    content.append(el("p","drawer-copy",
      "Cronologia parziale delle pubblicazioni con attribuzione verificata: non è un voto reputazionale."));
    if(profiles.outlet){
      const a=el("a","drawer-link secondary","Storico della testata →");
      a.href="/history?"+new URLSearchParams({type:"outlet",id:profiles.outlet});
      content.append(a);
    }
    if(profiles.author){
      const a=el("a","drawer-link secondary","Storico della firma →");
      a.href="/history?"+new URLSearchParams({type:"author",id:profiles.author});
      content.append(a);
    }
  }
  const original=safeLink(item.url);
  if(original) content.append(link(original,"Leggi sul sito della fonte originale ↗",
                                  item.kind==="article"?"drawer-link secondary":"drawer-link"));
  else content.append(el("p","drawer-copy","Non è presente un collegamento alla fonte originale."));
  content.append(el("p","drawer-footnote",
    "AFONDO non ripubblica il testo integrale della notizia. Gli indicatori riflettono solo le verifiche documentate disponibili."));
  layer.hidden=false;
  document.body.style.overflow="hidden";
  $("drawer-close").focus();
}

function closeDrawer(){
  $("drawer-layer").hidden=true;
  document.body.style.overflow="";
  if(lastFocused?.focus) lastFocused.focus();
}
document.querySelectorAll("[data-topic]").forEach(b=>
  b.addEventListener("click",()=>setTopic(b.dataset.topic))
);
document.querySelectorAll("[data-sort]").forEach(b=>
  b.addEventListener("click",()=>setSort(b.dataset.sort))
);
$("search").addEventListener("input",e=>{
  clearTimeout(debounce);
  debounce=setTimeout(()=>{
    state.query=e.target.value.trim().slice(0,100);
    state.limit=24;refresh();
  },220);
});
$("load-more").addEventListener("click",()=>{state.limit+=24;drawFeed()});
$("drawer-close").addEventListener("click",closeDrawer);
$("drawer-scrim").addEventListener("click",closeDrawer);
document.addEventListener("keydown",event=>{
  if(event.key==="Escape"&&!$("drawer-layer").hidden) closeDrawer();
  if(event.key==="/" && document.activeElement?.tagName!=="INPUT" &&
     $("drawer-layer").hidden && !event.ctrlKey && !event.metaKey){
    event.preventDefault();$("search").focus();
  }
  if(event.key==="Tab"&&!$("drawer-layer").hidden){
    const focusable=[...$("drawer").querySelectorAll('a[href],button:not([disabled])')];
    if(!focusable.length) return;
    const first=focusable[0],last=focusable[focusable.length-1];
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus()}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus()}
  }
});
refresh();
