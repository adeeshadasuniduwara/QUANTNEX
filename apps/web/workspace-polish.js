(()=>{"use strict";
const nav=document.querySelector(".sidebar-nav"),sidebar=document.querySelector(".sidebar");
if(!nav||!sidebar)return;
const icons={
 overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
 tradingview:'<path d="M3 18V6m0 12h18"/><path d="m6 14 4-4 3 2 5-6"/><path d="M15 6h3v3"/>',
 tools:'<circle cx="9" cy="9" r="5"/><path d="m13 13 7 7M7 9h4M9 7v4"/>',
 journal:'<path d="M6 3h12a2 2 0 0 1 2 2v16H6a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3Z"/><path d="M7 3v18M11 8h5M11 12h5"/>',
 account:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h4"/>',
 signal:'<path d="M3 12h3l3-8 5 16 3-8h4"/>',
 updates:'<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 12-2L20 12M4 12l2.5 5a7 7 0 0 0 12-2"/>',
 market:'<path d="M3 3v18h18"/><path d="m7 14 4-4 3 3 6-7"/>',
 reliability:'<path d="M12 3 3.5 7v5c0 5 3.6 8 8.5 9 4.9-1 8.5-4 8.5-9V7L12 3Z"/><path d="m8 12 2.5 2.5L16 9"/>',
 orderflow:'<path d="M3 7h18M3 12h13M3 17h8"/><path d="m17 9 3 3-3 3"/>',
 news:'<path d="M5 4h14v16H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="M8 8h8M8 12h8M8 16h5"/>',
 paper:'<path d="M7 3h10l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M17 3v5h4M9 13h6M9 17h6"/>',
 autopilot:'<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
 performance:'<path d="M4 19V5m0 14h17"/><path d="M8 16v-4m4 4V7m4 9v-6m4 6V4"/>',
 risk:'<path d="M12 3 3 20h18L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
 desks:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 10v10"/>',
 calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18M8 14h3m2 0h3"/>',
 portfolio:'<path d="M3 7h18v13H3z"/><path d="M8 7V4h8v3M3 12h18m-11 0v2h4v-2"/>',
 strategy:'<path d="M4 19V5m0 14h16"/><path d="m7 15 4-5 3 3 5-7"/>',
 goals:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
 settings:'<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"/><path d="m19.4 15 .1.1 1.2 1-1.5 2.6-1.5-.5a8 8 0 0 1-1.5.9l-.3 1.6h-3l-.3-1.6a8 8 0 0 1-1.5-.9l-1.5.5-1.5-2.6 1.2-1a8 8 0 0 1 0-1.8l-1.2-1 1.5-2.6 1.5.5a8 8 0 0 1 1.5-.9l.3-1.6h3l.3 1.6a8 8 0 0 1 1.5.9l1.5-.5 1.5 2.6-1.2 1a8 8 0 0 1 0 1.8Z"/>'
};
const groups=[
["HOME",["overview","tradingview"]],
["TRADE",["signal-lab","ai-signal-center","tools","paper-trading","paper-autopilot"]],
["MARKETS",["market-intelligence","watchlist-desk","forex-desk","crypto-desk","gold-desk","price-alerts","orderflow-liquidity","news-intelligence","economic-calendar","data-reliability"]],
["RISK & PORTFOLIO",["risk-management","portfolio-monitor","performance-lab","account","trade-history","journal"]],
["RESEARCH",["strategy-library","strategy-laboratory"]],
["GOALS",["personal-goals"]],
["SYSTEM",["integrations-center","system-security","updates"]]
];
const links=[...nav.querySelectorAll("a.nav-link")],byTarget=new Map(links.map(a=>[a.getAttribute("href")?.slice(1),a]));
const extras=links.filter(a=>![...groups.flatMap(g=>g[1])].includes(a.getAttribute("href")?.slice(1)));
nav.replaceChildren();
const searchWrap=document.createElement("label");searchWrap.className="qx-nav-search";searchWrap.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></svg><input type="search" id="qxNavSearch" placeholder="Find a tool…" aria-label="Find a tool"><kbd>/</kbd>';nav.append(searchWrap);
const allGroups=[...groups];if(extras.length)allGroups.push(["MORE",extras.map(a=>a.getAttribute("href").slice(1))]);
allGroups.forEach(([title,targets],index)=>{
 const items=targets.map(t=>byTarget.get(t)).filter(Boolean);if(!items.length)return;
 const section=document.createElement("section");section.className="qx-nav-group";
 const heading=document.createElement("button");heading.type="button";heading.className="qx-nav-heading";heading.innerHTML='<span>'+title+'</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>';
 const list=document.createElement("div");list.className="qx-nav-items";
 heading.setAttribute("aria-expanded","true");heading.addEventListener("click",()=>{const open=heading.getAttribute("aria-expanded")==="true";heading.setAttribute("aria-expanded",String(!open));list.hidden=open;});
 items.forEach(a=>{
  const target=a.getAttribute("href").slice(1),old=a.querySelector("span"),label=a.textContent.trim();
  const key=target==="overview"?"overview":target==="tradingview"?"tradingview":target.includes("journal")?"journal":target.includes("account")?"account":target.includes("signal")?"signal":target.includes("update")?"updates":target.includes("market")?"market":target.includes("reliability")?"reliability":target.includes("orderflow")?"orderflow":target.includes("news")?"news":target.includes("autopilot")?"autopilot":target.includes("paper")?"paper":target.includes("performance")?"performance":target.includes("risk")?"risk":target.includes("desk")?"desks":target.includes("calendar")?"calendar":target.includes("portfolio")?"portfolio":target.includes("strategy")?"strategy":target.includes("goal")?"goals":target.includes("integration")||target.includes("security")?"settings":target.includes("history")?"journal":target==="tools"?"tools":"desks";
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");svg.innerHTML=icons[key]||icons.desks;
  const icon=document.createElement("span");icon.className="qx-nav-icon";icon.replaceChildren(svg);
  const text=document.createElement("span");text.className="qx-nav-label";text.textContent=label;
  a.replaceChildren(icon,text);a.dataset.search=(label+" "+title).toLowerCase();list.append(a);
 });
 section.append(heading,list);nav.append(section);
});
const input=searchWrap.querySelector("input");
input.addEventListener("input",()=>{const q=input.value.trim().toLowerCase();nav.querySelectorAll(".qx-nav-group").forEach(group=>{let shown=0;group.querySelectorAll(".nav-link").forEach(a=>{const match=!q||a.dataset.search.includes(q);a.hidden=!match;if(match)shown++;});group.hidden=shown===0;});});
document.addEventListener("keydown",e=>{if(e.key==="/"&&!/input|textarea|select/i.test(document.activeElement?.tagName||"")){e.preventDefault();input.focus();}});
const brand=sidebar.querySelector(".brand");if(brand&&!sidebar.querySelector(".qx-sidebar-caption")){const cap=document.createElement("div");cap.className="qx-sidebar-caption";cap.textContent="TRADING WORKSPACE";brand.after(cap);}
const bottom=sidebar.querySelector(".sidebar-bottom");if(bottom)bottom.innerHTML='<span class="live-dot"></span><span>LOCAL WORKSPACE</span>';
const active=()=>{const hash=location.hash.slice(1)||"overview";nav.querySelectorAll(".nav-link").forEach(a=>{const yes=a.getAttribute("href")==="#"+hash;a.classList.toggle("active",yes);if(yes){a.closest(".qx-nav-group")?.querySelector(".qx-nav-items").removeAttribute("hidden");a.closest(".qx-nav-group")?.querySelector(".qx-nav-heading")?.setAttribute("aria-expanded","true");}});};
window.addEventListener("hashchange",active);active();
})();