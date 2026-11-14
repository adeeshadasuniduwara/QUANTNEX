/* QUANTNEX Phases 12–20 local paper platform UI. */
(()=>{"use strict";
const $=id=>document.getElementById(id);
const api=async(path,options={})=>{
 const response=await fetch("http://127.0.0.1:8000"+path,{...options,headers:{"Content-Type":"application/json",Accept:"application/json",...(options.headers||{})},cache:"no-store"});
 const data=await response.json().catch(()=>null);
 if(!response.ok)throw new Error(typeof data?.detail==="string"?data.detail:(data?.detail?.message||"Request failed ("+response.status+")."));
 return data;
};
const money=v=>v==null?"—":(Number(v)<0?"−":"")+"$"+Math.abs(Number(v)).toFixed(2);
const fmt=(v,d=4)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const status=(message,bad=false)=>{const n=$("paperEngineStatus");if(n){n.textContent=message;n.className=bad?"p7-note p7-status-error":"p7-note";}};
const cell=(row,value)=>{const td=document.createElement("td");td.textContent=value==null?"—":String(value);row.append(td);};
let settings={enabled:false};
function readForm(){return {
 enabled:settings.enabled,
 paper_equity:Number($("paperEngineEquity").value),
 risk_percent:Number($("paperEngineRisk").value),
 max_daily_loss_percent:Number($("paperEngineDailyLoss").value),
 max_drawdown_percent:Number($("paperEngineDrawdown").value),
 max_open_positions:Number($("paperEngineMaxOpen").value),
 interval_seconds:Number($("paperEngineInterval").value),
 min_score:Number($("paperEngineScore").value),
 symbols:["BTCUSDT","ETHUSDT","SOLUSDT"]
};}
function fillForm(s){const v=s.settings||s;settings=v;
 $("paperEngineEquity").value=v.paper_equity??10000;
 $("paperEngineRisk").value=v.risk_percent??.25;
 $("paperEngineDailyLoss").value=v.max_daily_loss_percent??2;
 $("paperEngineDrawdown").value=v.max_drawdown_percent??5;
 $("paperEngineMaxOpen").value=v.max_open_positions??3;
 $("paperEngineInterval").value=v.interval_seconds??180;
 $("paperEngineScore").value=String(v.min_score??8);
 const enabled=!!v.enabled;
 $("paperEngineState").textContent=enabled?"RUNNING · PAPER":"DISABLED";
 $("paperEngineToggle").textContent=enabled?"Pause paper mode":"Start paper mode";
 const risk=s.risk||{};
 const root=$("paperEngineRiskCards");root.replaceChildren();
 [["Entry gate",risk.entry_allowed===false?"BLOCKED":"READY"],["Daily P&L incl. floating",money(risk.realized_plus_unrealized_pnl_today_utc)],["Daily loss stop",money(risk.daily_loss_limit)],["Observed drawdown",money(risk.max_drawdown_observed)],["Open positions",(risk.open_positions??0)+" / "+(risk.max_open_positions??v.max_open_positions??3)]].forEach(([k,val])=>{
  const card=document.createElement("article");card.className="workspace-page-card";const label=document.createElement("span");label.textContent=k;const strong=document.createElement("strong");strong.textContent=val;card.append(label,strong);root.append(card);
 });
 if(risk.blocks?.length)status("Risk Guardian blocked new entries: "+risk.blocks.join(", ")+".",true);
 else if(s.last_error)status("Last scan issue: "+s.last_error,true);
 else status(enabled?"Paper autopilot is enabled. It will scan while the local API is running.":"Paper autopilot is disabled. Settings are saved locally.");
}
async function loadState(){try{const data=await api("/api/v1/paper-engine");fillForm(data);}catch(e){status("Paper engine status unavailable: "+e.message,true);}}
async function saveSettings(enabled=settings.enabled){
 const payload=readForm();payload.enabled=enabled;
 try{const data=await api("/api/v1/paper-engine",{method:"PUT",body:JSON.stringify(payload)});settings=data.settings;await loadState();status(enabled?"Paper autopilot enabled. No broker orders are possible.":"Paper engine settings saved; autopilot remains paused.");}
 catch(e){status("Could not save paper engine settings: "+e.message,true);}
}
async function loadPerformance(){try{
 const data=await api("/api/v1/paper-engine/performance"),root=$("paperEnginePerformance");root.replaceChildren();
 [["Closed trades",data.closed_trades],["Win rate",data.win_rate_percent==null?"—":fmt(data.win_rate_percent,2)+"%"],["Profit factor",data.profit_factor??"—"],["Net recorded P&L",money(data.net_realized_pnl)],["Expectancy",money(data.expectancy_per_trade)],["Max drawdown",money(data.max_drawdown_amount)]].forEach(([k,v])=>{const c=document.createElement("article");c.className="workspace-page-card";const a=document.createElement("span");a.textContent=k;const b=document.createElement("strong");b.textContent=v??"—";c.append(a,b);root.append(c);});
 }catch(e){status("Performance unavailable: "+e.message,true);}}
async function loadMonitor(){const body=$("paperEnginePositions");try{
 const data=await api("/api/v1/paper-engine/monitor");body.replaceChildren();
 if(!data.positions.length){const tr=document.createElement("tr");const td=document.createElement("td");td.colSpan=6;td.textContent="No open paper positions.";tr.append(td);body.append(tr);return;}
 data.positions.forEach(p=>{const tr=document.createElement("tr");[p.symbol,p.side,fmt(p.entry_price),fmt(p.mark_price),money(p.unrealized_pnl_estimate),p.data_health?.status].forEach(v=>cell(tr,v));if(p.data_health?.trading_safe===false)tr.className="workspace-page-status-bad";body.append(tr);});
 }catch(e){status("Position monitor unavailable: "+e.message,true);}}
async function loadEvents(){const body=$("paperEngineEvents");try{
 const rows=await api("/api/v1/paper-engine/events?limit=100");body.replaceChildren();
 if(!rows.length){const tr=document.createElement("tr");const td=document.createElement("td");td.colSpan=6;td.textContent="No paper events yet.";tr.append(td);body.append(tr);return;}
 rows.forEach(x=>{const tr=document.createElement("tr");[new Date(x.created_at).toLocaleString(),x.trade_id,x.event_type,fmt(x.price),fmt(x.quantity,6),money(x.pnl)].forEach(v=>cell(tr,v));body.append(tr);});
 }catch(e){status("Event ledger unavailable: "+e.message,true);}}
async function discoverUniverse(){const body=$("paperUniverseRows");$("paperUniverseRefresh").disabled=true;try{
 const data=await api("/api/v1/market/universe?limit=1000");body.replaceChildren();
 data.symbols.slice(0,25).forEach(x=>{const tr=document.createElement("tr");[x.symbol,x.base_asset,x.quote_asset,x.status].forEach(v=>cell(tr,v));body.append(tr);});
 $("paperUniverseStatus").textContent=data.complete_count+" eligible USDT Spot pairs discovered · "+(data.truncated?"display limited":"complete list returned")+" · "+new Date(data.timestamp).toLocaleTimeString()+".";
 }catch(e){$("paperUniverseStatus").textContent="Universe discovery failed: "+e.message;}finally{$("paperUniverseRefresh").disabled=false;}}
async function runWalkForward(){const button=$("paperWalkForwardRun");button.disabled=true;try{
 const data=await api("/api/v1/strategy-lab/walk-forward",{method:"POST",body:JSON.stringify({symbol:$("paperWalkForwardSymbol").value,timeframe:$("paperWalkForwardTimeframe").value,strategy:{fast_ema:9,slow_ema:21,risk_reward:2},train_ratio:.7})});
 $("paperWalkForwardResult").textContent="Training: "+data.training.trade_count+" trades · "+fmt(data.training.win_rate,1)+"% win rate · Out-of-sample: "+data.out_of_sample.trade_count+" trades · "+fmt(data.out_of_sample.win_rate,1)+"% win rate. "+data.warning;
 }catch(e){$("paperWalkForwardResult").textContent="Validation unavailable: "+e.message;}finally{button.disabled=false;}}
function init(){
 $("paperEngineSave")?.addEventListener("click",()=>saveSettings(settings.enabled));
 $("paperEngineToggle")?.addEventListener("click",()=>saveSettings(!settings.enabled));
 $("paperEngineRefresh")?.addEventListener("click",async()=>{await loadState();await loadPerformance();});
 $("paperEngineMonitor")?.addEventListener("click",loadMonitor);
 $("paperEngineEventsRefresh")?.addEventListener("click",loadEvents);
 $("paperUniverseRefresh")?.addEventListener("click",discoverUniverse);
 $("paperWalkForwardRun")?.addEventListener("click",runWalkForward);
 if(!$("paperEngineToggle"))return;
 loadState();loadPerformance();loadMonitor();loadEvents();
 window.setInterval(()=>{if(document.visibilityState==="visible"&&location.hash==="#paper-autopilot"){loadState();loadMonitor();loadEvents();}},60000);
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
})();