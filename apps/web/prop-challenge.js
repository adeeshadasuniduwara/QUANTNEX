/* Prop Firm Challenge UI. MT5 secrets are sent once and never stored in browser storage. */
(()=>{
"use strict";
const $=id=>document.getElementById(id);if(!$("pcCreateForm"))return;
const base="http://127.0.0.1:8000";
const fmt=value=>value==null||!Number.isFinite(Number(value))?"—":Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
const money=(value,currency="USD")=>{if(value==null||!Number.isFinite(Number(value)))return "—";try{return new Intl.NumberFormat(undefined,{style:"currency",currency}).format(Number(value));}catch{return "$"+fmt(value);}};
const setStatus=(message,bad=false)=>{const node=$("pcStatus");node.textContent=message;node.className=bad?"p7-note p7-status-error":"p7-note";};
const api=async(path,method="GET",payload)=>{
 const response=await fetch(base+path,{method,headers:{"Accept":"application/json",...(payload?{"Content-Type":"application/json"}:{})},body:payload?JSON.stringify(payload):undefined,cache:"no-store"});
 const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||"Local challenge API request failed ("+response.status+").");return data;
};
let current=null,mt5={connected:false},busy=false;
function render(data){
 current=data.challenge;mt5=data.mt5||{connected:false};
 const challenge=current,metrics=data.metrics||{},badge=$("pcStateBadge");
 badge.textContent=challenge?.status||"NOT STARTED";badge.dataset.state=challenge?.status||"NONE";
 const currency=challenge?.currency||mt5.currency||"USD";
 $("pcStartingBalance").textContent=challenge?money(challenge.starting_balance,currency):"—";
 $("pcEquity").textContent=challenge?money(metrics.equity??challenge.equity,currency):"—";
 $("pcDailyLoss").textContent=challenge?money(metrics.daily_loss_amount,currency):"—";
 $("pcDailyLossMeta").textContent=challenge?"Limit "+money(metrics.daily_loss_limit,currency)+" · "+fmt(metrics.daily_loss_used_pct)+"% used":"Daily limit";
 $("pcTargetRemaining").textContent=challenge?money(metrics.profit_target_remaining,currency):"—";
 $("pcTargetMeta").textContent=challenge?"Target "+money(metrics.profit_target_equity,currency):"Profit target";
 $("pcStatus").textContent=challenge?(challenge.status_reason||"Challenge loaded."):"No challenge created yet. Configure the rules below to begin.";
 $("pcCreateButton").disabled=!!challenge&&challenge.status==="ACTIVE";
 $("pcCreateButton").textContent=challenge&&challenge.status==="ACTIVE"?"Active challenge exists":"Create challenge";
 $("pcReset").hidden=!challenge;
 $("pcVirtualPractice").hidden=!(challenge&&challenge.mode==="virtual"&&challenge.status==="ACTIVE");
 $("pcMt5ConnectForm").hidden=!(challenge&&challenge.mode==="mt5_demo"&&challenge.status==="ACTIVE"&&!mt5.connected);
 $("pcMt5ConnectedActions").hidden=!mt5.connected;
 $("pcMt5Status").textContent=mt5.connected?"Connected · DEMO · "+mt5.login+" · "+mt5.server+" · "+money(mt5.equity,mt5.currency):challenge?.mode==="mt5_demo"?"Not connected. Connect an MT5 DEMO account to start monitoring.":"Select MT5 Demo mode when creating a challenge to connect a terminal.";
 $("pcMt5AccountSummary").textContent=mt5.connected?"DEMO account "+mt5.login+" · "+mt5.server+" · Balance "+money(mt5.balance,mt5.currency)+" · Equity "+money(mt5.equity,mt5.currency):"";
 const rows=$("pcTradeRows");rows.replaceChildren();const trades=data.recent_trades||[];
 if(!trades.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=4;td.className="empty-row";td.textContent="No virtual practice trades recorded. MT5 demo deals are monitored by the local Guardian.";tr.append(td);rows.append(tr);}
 else trades.slice().reverse().forEach(item=>{const tr=document.createElement("tr");[item.time?new Date(item.time).toLocaleString():"—",item.symbol,money(item.pnl,currency),money(item.balance_after,currency)].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});rows.append(tr);});
 $("pcHistoryMeta").textContent=trades.length?trades.length+" recent virtual practice result(s).":challenge?.mode==="mt5_demo"?"MT5 deal history is read from the connected demo terminal.":"No virtual trades recorded.";
 const guardian=challenge?.guardian_action;
 if(guardian){const failed=(guardian.failures||[]).length;$("pcGuardianNote").textContent="Guardian close attempt: "+guardian.closed+"/"+guardian.attempted+" positions closed."+ (failed?" "+guardian.failures.join(" "):"");}
 else if(challenge?.status==="FAILED")$("pcGuardianNote").textContent="Challenge failed and is locked. MT5 Guardian attempts to close DEMO positions after a breach; verify the broker's terminal and trade history.";
}
async function refresh(){if(busy)return;busy=true;try{render(await api("/api/v1/prop-challenge/state"));}catch(error){setStatus("Challenge service unavailable: "+error.message,true);}finally{busy=false;}}
$("pcCreateForm").addEventListener("submit",async event=>{
 event.preventDefault();const payload={mode:$("pcMode").value,starting_balance:Number($("pcStartingInput").value),profit_target_pct:Number($("pcTargetInput").value),daily_loss_pct:Number($("pcDailyInput").value),max_loss_pct:Number($("pcMaxInput").value),minimum_trading_days:Number($("pcDaysInput").value),drawdown_type:$("pcDrawdownInput").value,timezone:$("pcTimezoneInput").value};
 try{await api("/api/v1/prop-challenge/challenge","POST",payload);setStatus("Challenge created. Review the rules and connect MT5 DEMO if selected.");await refresh();}catch(error){setStatus(error.message,true);}
});
$("pcVirtualTradeForm").addEventListener("submit",async event=>{
 event.preventDefault();const pnlInput=$("pcVirtualPnl"),payload={pnl:Number(pnlInput.value),symbol:$("pcVirtualSymbol").value.trim().toUpperCase()};
 try{await api("/api/v1/prop-challenge/virtual-trades","POST",payload);pnlInput.value="";await refresh();}catch(error){setStatus(error.message,true);}
});
$("pcMt5ConnectForm").addEventListener("submit",async event=>{
 event.preventDefault();const password=$("pcMt5Password"),payload={login:Number($("pcMt5Login").value),server:$("pcMt5Server").value.trim(),password:password.value,terminal_path:$("pcMt5Path").value.trim()||null};
 $("pcMt5ConnectButton").disabled=true;
 try{const result=await api("/api/v1/prop-challenge/mt5/connect","POST",payload);setStatus("Connected to MT5 DEMO account "+result.login+". Password was not saved.");password.value="";await refresh();}
 catch(error){password.value="";setStatus(error.message,true);}
 finally{$("pcMt5ConnectButton").disabled=false;}
});
$("pcMt5Disconnect").addEventListener("click",async()=>{try{await api("/api/v1/prop-challenge/mt5/disconnect","POST",{});await refresh();}catch(error){setStatus(error.message,true);}});
$("pcReset").addEventListener("click",async()=>{if(!window.confirm("Reset this challenge and clear its local practice history?"))return;try{await api("/api/v1/prop-challenge/reset","POST",{});await refresh();}catch(error){setStatus(error.message,true);}});
$("pcRefresh").addEventListener("click",refresh);
window.addEventListener("quantnex:view-changed",event=>{if(event.detail?.view==="prop-challenge")refresh();});
window.setInterval(()=>{if(document.visibilityState!=="visible")return;const view=document.querySelector('[data-workspace-view="prop-challenge"]');if(view&&!view.hidden&&current?.mode==="mt5_demo"&&mt5.connected)refresh();},2000);
refresh();
})();