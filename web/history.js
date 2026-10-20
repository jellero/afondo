"use strict";
const $=id=>document.getElementById(id);
const node=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=String(text);return e};
const safeUrl=value=>{try{const x=new URL(value);return x.protocol==="https:"||x.protocol==="http:"?x.href:null}catch{return null}};
let kind=new URLSearchParams(location.search).get("type")==="author"?"author":"outlet";
let current=new URLSearchParams(location.search).get("id")||"";
let debounce;
function selectKind(newKind){
  kind=newKind;current="";
  for(const b of document.querySelectorAll("[data-kind]"))
    b.setAttribute("aria-pressed",String(b.dataset.kind===kind));
  loadList();
}
async function loadList(){
  const params=new URLSearchParams({kind,q:$("history-search").value});
  try{
    const response=await fetch("/api/v1/history?"+params);
    if(!response.ok)throw Error("Catalogo non disponibile");
    const data=await response.json();
    $("history-count").textContent=data.total+" profili con attribuzione verificata";
    const list=$("history-results");list.replaceChildren();
    for(const profile of data.items){
      const b=node("button","");
      b.type="button";b.append(node("strong","",profile.name));
      b.append(node("span","",profile.type==="author"?
        profile.outlet+" · "+profile.summary.article_count+" articoli":
        profile.origin+" · "+profile.summary.article_count+" articoli"));
      b.addEventListener("click",()=>loadDetail(profile.id));list.append(b);
    }
    if(current && data.items.some(p=>p.id===current))await loadDetail(current);
    else if(!data.items.length){
      $("history-detail").replaceChildren(node("h2","","Nessuno storico ancora disponibile"),
        node("p","","Il sistema non attribuisce automaticamente le notizie a persone o testate. Lo storico si attiva dopo una verifica dell'origine e l'approvazione editoriale."));
    }
  }catch(err){$("history-count").textContent=err.message}
}
async function loadDetail(id){
  current=id;
  const response=await fetch("/api/v1/history/"+kind+"/"+encodeURIComponent(id));
  if(!response.ok)return;
  const data=await response.json(),target=$("history-detail");
  target.replaceChildren();
  target.append(node("div","eyebrow",kind==="author"?"FIRMA NELLA TESTATA":"TESTATA VERIFICATA"),
    node("h2","",data.name),
    node("p","",kind==="author"?"Firma associata a "+data.outlet+" · "+data.origin:data.origin));
  const counts=node("div","history-counts");
  for(const [number,label] of [
    [data.summary.article_count,"Articoli catalogati"],
    [data.summary.articles_with_context_note,"Segnalazioni sul contesto"],
    [data.summary.articles_with_sensationalism_note,"Segnalazioni sul titolo"]
  ]){const cell=node("div");cell.append(node("strong","",number),node("span","",label));counts.append(cell)}
  target.append(counts,node("p","disclaimer",data.summary.disclaimer));
  if(data.summary.sample_status==="limited")
    target.append(node("p","", "Campione limitato: non è possibile trarre conclusioni statistiche sull'affidabilità."));
  for(const article of data.articles){
    const section=node("article","history-story");
    section.append(node("h3","",article.title));
    section.append(node("p","",article.created_at+" · "+(article.author||article.outlet)));
    const link=safeUrl(article.url);
    if(link){const a=node("a","","Leggi l'articolo originale ↗");a.href=link;a.target="_blank";a.rel="noopener noreferrer";section.append(a)}
    const tags=[];
    if(article.flags.out_of_context)tags.push("Fuori contesto (revisione editoriale)");
    if(article.flags.sensationalistic)tags.push("Titolo sensazionalistico (revisione editoriale)");
    if(tags.length)section.append(node("p","",tags.join(" · ")));
    if(article.note)section.append(node("p","",article.note));
    const docs=safeUrl(article.evidence_url);
    if(docs){const a=node("a","","Motivazione / prova ↗");a.href=docs;a.rel="noopener noreferrer";a.target="_blank";section.append(a)}
    if(article.revisions.length){
      const detail=node("details"),summary=node("summary","","Cronologia delle revisioni ("+article.revisions.length+")");detail.append(summary);
      const list=node("ol");
      for(const revision of article.revisions){
        const it=node("li","",revision.happened_at+" · "+revision.event_kind);
        if(revision.change_reason)it.append(node("p","",revision.change_reason));
        if(revision.note)it.append(node("p","",revision.note));
        list.append(it);
      }
      detail.append(list);section.append(detail);
    }
    target.append(section);
  }
  const params=new URLSearchParams({type:kind,id});history.replaceState(null,"","/history?"+params);
}
document.querySelectorAll("[data-kind]").forEach(b=>b.addEventListener("click",()=>selectKind(b.dataset.kind)));
$("history-search").addEventListener("input",()=>{clearTimeout(debounce);debounce=setTimeout(loadList,210)});
for(const b of document.querySelectorAll("[data-kind]"))b.setAttribute("aria-pressed",String(b.dataset.kind===kind));
loadList();
