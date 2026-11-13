/* Single-view workspace navigation with a short, accessible fade transition. */
(()=>{
"use strict";
const main=document.querySelector(".main");
if(!main)return;
const links=[...document.querySelectorAll('.sidebar-nav .nav-link[href^="#"]')];
const targets=new Set(links.map(link=>decodeURIComponent(link.getAttribute("href").slice(1))));
const topbar=main.querySelector(":scope > .topbar");
const nodes=[...main.children].filter(node=>node!==topbar);
const views=new Map();
let current="overview",switchToken=0;
let activeView=document.createElement("div");
activeView.className="workspace-view";
activeView.dataset.workspaceView="overview";
views.set("overview",activeView);
for(const node of nodes){
 if(node.id&&targets.has(node.id)&&node.id!=="overview"){
  activeView=document.createElement("div");
  activeView.className="workspace-view";
  activeView.dataset.workspaceView=node.id;
  views.set(node.id,activeView);
 }
 activeView.append(node);
}
for(const view of views.values())main.append(view);
const title=topbar?.querySelector("h1");
const reducedMotion=()=>window.matchMedia?.("(prefers-reduced-motion: reduce)").matches??false;
function scrollToTop(){
 const root=document.documentElement,old=root.style.scrollBehavior;
 root.style.scrollBehavior="auto";window.scrollTo(0,0);root.style.scrollBehavior=old;
}
function activate(id,options={}){
 const next=views.get(id);if(!next)return false;
 const animate=options.animate!==false&&!reducedMotion(),token=++switchToken,previous=views.get(current);
 if(previous===next){scrollToTop();return true;}
 if(previous&&animate){previous.classList.remove("is-entering");previous.classList.add("is-leaving");}
 const show=()=>{
  if(token!==switchToken)return;
  if(previous){previous.hidden=true;previous.classList.remove("is-leaving");previous.setAttribute("aria-hidden","true");}
  next.hidden=false;next.removeAttribute("aria-hidden");next.classList.remove("is-leaving","is-entering");
  if(animate){void next.offsetWidth;next.classList.add("is-entering");}
  current=id;scrollToTop();
  const link=links.find(item=>decodeURIComponent(item.getAttribute("href").slice(1))===id);
  links.forEach(item=>{const selected=item===link;item.classList.toggle("active",selected);if(selected)item.setAttribute("aria-current","page");else item.removeAttribute("aria-current");});
  if(title)title.textContent=link?link.textContent.replace(link.querySelector("span")?.textContent||"","").trim():"Overview";
  if(options.updateHash!==false&&location.hash!=="#"+id)history.pushState({view:id},"","#"+id);
  window.dispatchEvent(new CustomEvent("quantnex:view-changed",{detail:{view:id}}));
 };
 if(previous&&animate)window.setTimeout(show,105);else show();
 return true;
}
for(const view of views.values()){const active=view.dataset.workspaceView==="overview";view.hidden=!active;if(!active)view.setAttribute("aria-hidden","true");}
window.quantnexNavigate=id=>activate(id);
document.addEventListener("click",event=>{
 const link=event.target.closest?.('.sidebar-nav .nav-link[href^="#"]');if(!link)return;
 const id=decodeURIComponent(link.getAttribute("href").slice(1));if(!views.has(id))return;
 event.preventDefault();activate(id);
});
window.addEventListener("popstate",()=>{const id=decodeURIComponent(location.hash.slice(1))||"overview";activate(views.has(id)?id:"overview",{updateHash:false});});
const initial=decodeURIComponent(location.hash.slice(1))||"overview";
activate(views.has(initial)?initial:"overview",{animate:false,updateHash:false});
})();