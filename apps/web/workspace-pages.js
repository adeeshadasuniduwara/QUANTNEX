/* Dedicated workspace pages. All values come from local APIs or real provider events. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);
const api=async(path)=>{
 const response=await fetch("http://127.0.0.1:8000"+path,{headers:{Accept:"application/json"},cache:"no-store"});
 const body=await response.json().catch(()=>null);
 if(!response.ok)throw new Error(body?.detail?.message||body?.detail||("API request failed ("+response.status+")."));
 return body;
};
const fmt=(value,digits=2)=>value==null||!Number.isFinite(Number(value))?"—":Number(value).toLocaleString(undefined,{maximumFractionDigits:digits});
const money=value=>value==null?"—":(Number(value)<0?"−":"")+"$"+Math.abs(Number(value)).toFixed(2);
const el=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined&&value!==null)n.textContent=String(value);if(cls)n.className=cls;return n;};
const setStatus=(id,message,bad=false)=>{const n=$(id);if(n){n.textContent=message;n.className=bad?"p7-note p7-status-error":"p7-note";}};
const cell=(row,value)=>row.append(el("td",value==null?"—":value));
const empty=(body,cols,message)=>{body.replaceChildren();const tr=el("tr"),td=el("td",message,"empty-row");td.colSpan=cols;tr.append(td);body.append(tr);};
const digits=s=>s==="XAUUSD"?2:["EURUSD","GBPUSD"].includes(s)?5:s==="USDJPY"?3:2;
let latestMarkets=new Map();
let marketBoardCache=null,marketBoardFetchedAt=0,marketBoardPromise=null;
let alerts=[];
const ALERT_KEY="quantnex.price-alerts.v1";
function loadAlerts(){try{const v=JSON.parse(localStorage.getItem(ALERT_KEY)||"[]");return Array.isArray(v)?v.filter(x=>x&&typeof x.id==="string"&&typeof x.symbol==="string"&&Number.isFinite(Number(x.target))):[];}catch{return[];}}
function saveAlerts(){try{localStorage.setItem(ALERT_KEY,JSON.stringify(alerts));}catch{setStatus("alertStatus","Could not save alerts: browser storage is unavailable or full.",true);}}
function checkAlert(alert,price,source){
 if(alert.triggered||!Number.isFinite(Number(price)))return false;
 const crossed=alert.condition==="above"?Number(price)>=Number(alert.target):Number(price)<=Number(alert.target);
 if(!crossed)return false;
 alert.triggered=true;alert.triggeredAt=new Date().toISOString();alert.triggerPrice=Number(price);alert.triggerSource=source;
 setStatus("alertStatus","ALERT · "+alert.symbol+" reached "+fmt(price,digits(alert.symbol))+" ("+alert.condition+" "+fmt(alert.target,digits(alert.symbol))+").");
 window.dispatchEvent(new CustomEvent("quantnex:price-alert",{detail:{...alert}}));
 if(typeof showUpdateToast==="function")showUpdateToast("Price alert · "+alert.symbol+" reached "+fmt(price,digits(alert.symbol))+".");
 return true;
}
function renderAlerts(){
 const body=$("alertRows");if(!body)return;body.replaceChildren();
 if(!alerts.length){empty(body,5,"No local alerts created.");return;}
 alerts.forEach(alert=>{
  const tr=el("tr");[alert.symbol,alert.condition==="above"?"Above":"Below",fmt(alert.target,digits(alert.symbol)),
   alert.triggered?"Triggered · "+(alert.triggeredAt?new Date(alert.triggeredAt).toLocaleTimeString():""):"Active"].forEach(v=>cell(tr,v));
  const action=el("td"),button=el("button","Remove","secondary-btn compact-btn");
  button.addEventListener("click",()=>{alerts=alerts.filter(x=>x.id!==alert.id);saveAlerts();renderAlerts();});
  action.append(button);tr.append(action);body.append(tr);
 }); 
}
async function loadMarketBoard(force=false){
 const now=Date.now();
 if(!force&&marketBoardCache&&now-marketBoardFetchedAt<5000)return marketBoardCache;
 if(!force&&marketBoardPromise)return marketBoardPromise;
 marketBoardPromise=(async()=>{
 const data=await api("/api/v1/intelligence/markets");
 marketBoardCache=data;marketBoardFetchedAt=Date.now();
 latestMarkets=new Map((data.items||[]).map(item=>[item.symbol,item]));
 let triggered=false;
 (data.items||[]).filter(item=>item.status==="ok"&&item.kind!=="crypto").forEach(item=>{
  alerts.filter(alert=>alert.symbol===item.symbol).forEach(alert=>{
   if(checkAlert(alert,item.price,item.provider||"provider refresh"))triggered=true;
  });
 });
 if(triggered){saveAlerts();renderAlerts();}
 return data;
 })();
 try{return await marketBoardPromise;}finally{marketBoardPromise=null;}
}
function renderMarketRows(body,items,cols=6){
 body.replaceChildren();
 if(!items.length){empty(body,cols,"No provider data is currently available.");return;}
 items.forEach(item=>{
  const tr=el("tr"),price=item.status==="ok"?fmt(item.price,digits(item.symbol)):"Unavailable";
  const change=item.status==="ok"?(Number(item.change_percent)>=0?"+":"")+fmt(item.change_percent,2)+"%":item.reason||"Unavailable";
  [item.symbol,item.kind||"—",price,change,item.provider||"—",item.timestamp?new Date(item.timestamp).toLocaleTimeString():"—"].forEach(v=>cell(tr,v));
  if(item.status!=="ok")tr.className="workspace-page-status-bad";
  body.append(tr);
 });
}
async function refreshWatchlist(force=false){
 try{const data=await loadMarketBoard(force);renderMarketRows($("watchlistRows"),data.items||[]);setStatus("watchlistStatus","Updated "+new Date(data.timestamp||Date.now()).toLocaleTimeString()+" · "+(data.items||[]).filter(x=>x.status==="ok").length+"/"+(data.items||[]).length+" providers available.");}
 catch(e){setStatus("watchlistStatus","Watchlist unavailable: "+e.message,true);}
}
async function renderDeskCards(containerId,statusId,kind,force=false){
 try{
  const data=await loadMarketBoard(force),items=(data.items||[]).filter(x=>x.kind===kind),root=$(containerId);root.replaceChildren();
  if(!items.length)root.append(el("p","No "+kind+" instruments are configured.","workspace-page-empty"));
  items.forEach(item=>{
   const card=el("article",undefined,"workspace-page-card");
   card.append(el("span",item.symbol+" · "+item.provider));
   card.append(el("strong",item.status==="ok"?fmt(item.price,digits(item.symbol)):"Unavailable"));
   card.append(el("small",item.status==="ok"?(Number(item.change_percent)>=0?"+":"")+fmt(item.change_percent,2)+"% · 24h change":item.reason,""+(item.status==="ok"?"workspace-page-status-good":"workspace-page-status-bad")));
   card.append(el("small",item.status==="ok"?"High "+fmt(item.high_24h,digits(item.symbol))+" · Low "+fmt(item.low_24h,digits(item.symbol))+" · "+new Date(item.timestamp).toLocaleTimeString():"No verified quote"));
   root.append(card);
   if(kind==="gold"&&item.status==="ok")$("goldDeskStatus").textContent="XAUUSD quote received from "+item.provider+" at "+new Date(item.timestamp).toLocaleTimeString()+".";
   if(kind==="forex"&&item.status!=="ok")setStatus(statusId,"One or more Forex quotes are unavailable. Check Twelve Data key, plan and market hours.",true);
  });
  if(kind==="forex"&&!items.some(x=>x.status==="ok"))setStatus(statusId,"Forex feed unavailable. A valid local Twelve Data key and eligible plan may be required.",true);
  else setStatus(statusId,items.filter(x=>x.status==="ok").length+"/"+items.length+" "+kind+" instruments have provider quotes.");
 }catch(e){setStatus(statusId,kind+" desk unavailable: "+e.message,true);}
}
async function loadGoldCandles(){
 const button=$("goldDeskCandles");button.disabled=true;
 try{
  const tf=$("goldDeskTimeframe").value,data=await api("/api/v1/intelligence/market/XAUUSD/candles?timeframe="+encodeURIComponent(tf));
  const body=$("goldDeskCandleRows");body.replaceChildren();
  (data.candles||[]).slice(-12).reverse().forEach(x=>{
   const tr=el("tr");[x.time?new Date(x.time).toLocaleString():"—",fmt(x.open,2),fmt(x.high,2),fmt(x.low,2),fmt(x.close,2)].forEach(v=>cell(tr,v));body.append(tr);
  });
  if(!body.children.length)empty(body,5,"Provider returned no candles.");
  setStatus("goldDeskStatus","Loaded "+data.count+" "+tf+" candles from "+data.provider+".");
 }catch(e){empty($("goldDeskCandleRows"),5,"Candles unavailable: "+e.message);setStatus("goldDeskStatus","Gold candle feed unavailable: "+e.message,true);}
 finally{button.disabled=false;}
}
async function loadCalendar(){
 const button=$("calendarRefresh");button.disabled=true;
 try{
  const data=await api("/api/v1/intelligence/news?days="+encodeURIComponent($("calendarDays").value));
  const body=$("calendarRows");body.replaceChildren();
  if(!data.configured||!(data.events||[]).length)empty(body,7,data.note||"No calendar events returned.");
  else data.events.forEach(event=>{
   const tr=el("tr");
   const raw=event.time??event.timestamp??event.datetime;
   let when="—";if(typeof raw==="number")when=new Date(raw*1000).toLocaleString();else if(raw)when=new Date(raw).toLocaleString();
   [when,event.country||"—",event.event||event.title||"—",event.impact||"—",event.actual??"—",event.estimate??event.forecast??"—",event.prev??event.previous??"—"].forEach(v=>cell(tr,v));
   body.append(tr);
  });
  setStatus("calendarStatus",data.configured?"Loaded "+(data.events||[]).length+" events from "+data.provider+".":data.note||"Calendar provider not configured.",!data.configured);
 }catch(e){empty($("calendarRows"),7,"Calendar unavailable: "+e.message);setStatus("calendarStatus","Calendar request failed: "+e.message,true);}
 finally{button.disabled=false;}
}
async function loadTradeHistory(){
 try{
  const [paper,journal]=await Promise.all([api("/api/v1/paper-trading/trades?limit=200"),api("/api/v1/journal?limit=200")]);
  const pb=$("historyPaperRows");pb.replaceChildren();
  if(!paper.length)empty(pb,8,"No paper trades recorded.");
  else paper.forEach(x=>{
   const tr=el("tr");[x.created_at?new Date(x.created_at).toLocaleString():"—",x.symbol,x.side,fmt(x.quantity,6),fmt(x.entry_price,digits(x.symbol)),fmt(x.exit_price,digits(x.symbol)),x.realized_pnl==null?"—":fmt(x.realized_pnl,4),x.status].forEach(v=>cell(tr,v));pb.append(tr);
  });
  const jb=$("historyJournalRows");jb.replaceChildren();
  if(!journal.length)empty(jb,6,"No journal entries recorded.");
  else journal.forEach(x=>{const tr=el("tr");[x.created_at?new Date(x.created_at).toLocaleDateString():"—",x.symbol,x.direction,x.outcome,fmt(x.pnl,2),x.notes||"—"].forEach(v=>cell(tr,v));jb.append(tr);});
  setStatus("historyStatus","Loaded "+paper.length+" paper trade(s) and "+journal.length+" journal record(s). Paper ledger and manual journal remain separate.");
 }catch(e){setStatus("historyStatus","Trade history unavailable: "+e.message,true);}
}
async function loadStrategyLibrary(){
 try{
  const data=await api("/api/v1/strategy-lab/research"),summary=$("strategyLibrarySummary");summary.replaceChildren();
  const p=data.paper_trades||{};
  [["Saved research runs",(data.runs||[]).length],["Closed paper trades",p.closed||0],["Paper win rate",p.win_rate==null?"—":fmt(p.win_rate,1)+"%"],["Net P&L · unconverted",fmt(p.net_pnl,4)]].forEach(([label,value])=>{
   const card=el("article",undefined,"workspace-page-card");card.append(el("span",label),el("strong",value));summary.append(card);
  });
  const body=$("strategyLibraryRows");body.replaceChildren();
  if(!(data.runs||[]).length)empty(body,5,"No saved research runs yet. Use AI Strategy Laboratory to create a backtest, optimizer or forward evaluation.");
  else data.runs.forEach(run=>{
   const result=run.result||{},description=run.type==="BACKTEST"?"Trades "+(result.trade_count??"—")+" · Win "+(result.win_rate==null?"—":fmt(result.win_rate,1)+"%")+" · Net "+money(result.net_pnl):
    run.type==="OPTIMIZER"?"Candidates tested "+(result.tested??"—"):(result.side||"WAIT")+" · "+(result.note||"Forward observation");
   const tr=el("tr");[run.type,run.symbol,run.timeframe,new Date(run.created_at).toLocaleString(),description].forEach(v=>cell(tr,v));body.append(tr);
  });
  setStatus("strategyLibraryStatus","Loaded "+(data.runs||[]).length+" saved research run(s). "+(data.guidance||""));
 }catch(e){setStatus("strategyLibraryStatus","Strategy library unavailable: "+e.message,true);}
}
async function loadPortfolioMonitor(){
 try{
  const data=await api("/api/v1/risk/portfolio"),cards=$("portfolioMonitorCards");cards.replaceChildren();
  [["Open positions",data.open_positions],["Gross notional · unconverted",fmt(data.gross_notional_estimate,4)],["Planned stop risk · unconverted",fmt(data.planned_stop_risk_estimate,4)],["Markets represented",Object.keys(data.by_symbol_notional||{}).length]].forEach(([label,value])=>{
   const card=el("article",undefined,"workspace-page-card");card.append(el("span",label),el("strong",value??"—"));cards.append(card);
  });
  const body=$("portfolioMonitorRows");body.replaceChildren();
  if(!(data.positions||[]).length)empty(body,6,"No open paper positions.");
  else data.positions.forEach(p=>{const tr=el("tr");[p.id,p.symbol,p.side,fmt(p.quantity,6),fmt(p.notional_estimate,4),fmt(p.planned_stop_risk_estimate,4)].forEach(v=>cell(tr,v));body.append(tr);});
  setStatus("portfolioMonitorStatus","Portfolio snapshot refreshed. Amounts are unconverted price × quantity estimates. Cross-currency totals, contract multipliers and broker margin are not inferred.");
 }catch(e){setStatus("portfolioMonitorStatus","Portfolio monitor unavailable: "+e.message,true);}
}
async function loadIntegrations(){
 try{
  const [ai,telegram,signals]=await Promise.all([
   api("/api/v1/ai/status"),api("/api/v1/telegram/status"),api("/api/v1/signals/status")
  ]);
  const root=$("integrationCards");root.replaceChildren();
  const items=[
   ["AI assistant",ai.configured?"Configured":"Not configured",ai.configured?"Model "+(ai.model||"available"):"Optional server-side AI provider is disabled.",ai.configured],
   ["Telegram bot",telegram.connected?"Connected":"Not connected",telegram.connected?"Local bot connection is active.":"Connect from Signal Lab; bot token stays encrypted locally.",telegram.connected],
   ["XAUUSD signal feed",signals.configured?"Configured":"Not configured",signals.note||"Twelve Data configuration status.",signals.configured],
   ["Trading execution","Disabled","No broker connection or live order routing is enabled.",false],
   ["Workspace security","Local-only / no login","Loopback API and local device workspace.",true]
  ];
  items.forEach(([title,state,note,good])=>{
   const card=el("article",undefined,"workspace-page-card");card.append(el("span",title),el("strong",state,good?"workspace-page-status-good":"workspace-page-status-warn"),el("small",note));root.append(card);
  });
  setStatus("integrationStatus","Integration status refreshed. Secret values are never returned to this page.");
 }catch(e){setStatus("integrationStatus","Could not check every integration: "+e.message,true);}
}
function init(){
 const navLinks=[...document.querySelectorAll(".sidebar .nav-link")];
 const pageTitle=document.querySelector(".topbar h1");
 const syncActiveNav=()=>{
  const current=window.location.hash||"#overview";
  let activeLabel="Overview";
  navLinks.forEach(link=>{
   const active=link.getAttribute("href")===current;
   link.classList.toggle("active",active);
   if(active){link.setAttribute("aria-current","location");const label=link.cloneNode(true);label.querySelector("span")?.remove();activeLabel=label.textContent.trim();}else link.removeAttribute("aria-current");
  });
  if(pageTitle)pageTitle.textContent=activeLabel;
 };
 navLinks.forEach(link=>link.addEventListener("click",()=>{navLinks.forEach(item=>{item.classList.remove("active");item.removeAttribute("aria-current");});link.classList.add("active");link.setAttribute("aria-current","location");}));
 window.addEventListener("hashchange",syncActiveNav);
 syncActiveNav();
 alerts=loadAlerts();renderAlerts();
 if($("watchlistRefresh")){$("watchlistRefresh").addEventListener("click",()=>refreshWatchlist(true));refreshWatchlist();}
 if($("forexDeskRefresh")){$("forexDeskRefresh").addEventListener("click",()=>renderDeskCards("forexDeskCards","forexDeskStatus","forex",true));renderDeskCards("forexDeskCards","forexDeskStatus","forex");}
 if($("cryptoDeskRefresh")){$("cryptoDeskRefresh").addEventListener("click",()=>renderDeskCards("cryptoDeskCards","cryptoDeskStatus","crypto",true));renderDeskCards("cryptoDeskCards","cryptoDeskStatus","crypto");}
 if($("goldDeskRefresh")){$("goldDeskRefresh").addEventListener("click",()=>renderDeskCards("goldDeskCards","goldDeskStatus","gold",true));renderDeskCards("goldDeskCards","goldDeskStatus","gold");}
 if($("goldDeskCandles"))$("goldDeskCandles").addEventListener("click",loadGoldCandles);
 if($("calendarRefresh")){$("calendarRefresh").addEventListener("click",loadCalendar);loadCalendar();}
 if($("historyRefresh")){$("historyRefresh").addEventListener("click",loadTradeHistory);loadTradeHistory();}
 if($("strategyLibraryRefresh")){$("strategyLibraryRefresh").addEventListener("click",loadStrategyLibrary);loadStrategyLibrary();}
 if($("portfolioMonitorRefresh")){$("portfolioMonitorRefresh").addEventListener("click",loadPortfolioMonitor);loadPortfolioMonitor();}
 if($("integrationRefresh")){$("integrationRefresh").addEventListener("click",loadIntegrations);loadIntegrations();}
 if($("alertCreate"))$("alertCreate").addEventListener("click",()=>{
  const symbol=$("alertSymbol").value,target=Number($("alertTarget").value),condition=$("alertCondition").value;
  if(!Number.isFinite(target)||target<=0){setStatus("alertStatus","Enter a target price greater than zero.",true);return;}
  alerts.push({id:Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,8),symbol,condition,target,triggered:false,createdAt:new Date().toISOString()});
  saveAlerts();renderAlerts();$("alertTarget").value="";setStatus("alertStatus","Local alert saved for "+symbol+". It will trigger when a supported price event crosses the target.");
 });
 window.addEventListener("quantnex:workspace-event",event=>{
  const type=event.detail?.type;
  if(type==="journal.changed")loadTradeHistory();
  if(type==="paper_trade.changed"){loadTradeHistory();loadPortfolioMonitor();}
  if(type==="strategy.research.changed")loadStrategyLibrary();
  if(type==="preferences.changed"||type==="integration.changed")loadIntegrations();
 });
 window.addEventListener("quantnex:workspace-resync",()=>{
  loadTradeHistory();loadPortfolioMonitor();loadStrategyLibrary();loadIntegrations();
 });
 window.addEventListener("quantnex:stream-status",event=>{
  const detail=event.detail||{};
  if(detail.feed==="workspace")setStatus("integrationStatus","Local event stream: "+detail.status+". Workspace changes are broadcast within this computer.");
  if(detail.feed==="crypto"){
   const connected=detail.status==="connected";
   setStatus("cryptoDeskStatus",connected?"Binance Spot WebSocket connected · waiting for provider trade events.":"Binance Spot stream reconnecting · snapshot quotes remain available.",!connected);
  }
 });
 window.addEventListener("quantnex:market-tick",event=>{
  const detail=event.detail||{},symbol=String(detail.symbol||"").toUpperCase(),price=Number(detail.price);
  if(!symbol||!Number.isFinite(price))return;
  const item=latestMarkets.get(symbol);if(item){item.price=price;item.timestamp=new Date(Number(detail.eventTime)||Date.now()).toISOString();}
  if(symbol==="BTCUSDT"||symbol==="ETHUSDT"||symbol==="SOLUSDT"){
   const root=$("cryptoDeskCards");
   if(root){const card=[...root.children].find(x=>x.querySelector("span")?.textContent.startsWith(symbol));if(card){const strong=card.querySelector("strong");if(strong)strong.textContent=fmt(price,digits(symbol));const small=card.querySelectorAll("small");if(small.length>1)small[1].textContent="Binance "+(detail.kind==="trade"?"trade":"ticker")+" event · "+new Date(Number(detail.eventTime)||Date.now()).toLocaleTimeString();}}
   const body=$("watchlistRows");if(body){const row=[...body.rows].find(x=>x.cells[0]?.textContent===symbol);if(row){row.cells[2].textContent=fmt(price,digits(symbol));row.cells[5].textContent=new Date(Number(detail.eventTime)||Date.now()).toLocaleTimeString();}}
   let triggered=false;
   if(detail.kind==="trade")alerts.filter(x=>x.symbol===symbol&&!x.triggered).forEach(x=>{if(checkAlert(x,price,"Binance WebSocket trade"))triggered=true;});
   if(triggered){saveAlerts();renderAlerts();}
   setStatus("cryptoDeskStatus",symbol+" live "+(detail.kind==="trade"?"trade":"ticker")+" · "+fmt(price,digits(symbol))+" · "+new Date(Number(detail.eventTime)||Date.now()).toLocaleTimeString());
  }
 });
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();
