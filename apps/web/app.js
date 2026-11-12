const $ = (id) => document.getElementById(id);
const storageKey = "quantnex.journal.v2";
function loadTrades(){
  try{
    const current=JSON.parse(localStorage.getItem(storageKey)||"null");
    if(Array.isArray(current)&&current.length)return current;
    const legacy=JSON.parse(localStorage.getItem("quantnex.phase2.journal.v1")||"[]");
    if(Array.isArray(legacy)&&legacy.length){
      const migrated=legacy.map(t=>({date:t.date||"",symbol:String(t.symbol||"").toUpperCase(),direction:t.direction||"Buy",outcome:t.outcome||"Breakeven",pnl:Number(t.pnl)||0,notes:String(t.notes||"")}));
      localStorage.setItem(storageKey,JSON.stringify(migrated));
      return migrated;
    }
    return Array.isArray(current)?current:[];
  }catch{return[];}
}
function saveTrades(rows){localStorage.setItem(storageKey,JSON.stringify(rows));}
function money(value){return (value<0?"−":"")+"$"+Math.abs(value).toFixed(2);}
function renderJournal(){
  const rows=loadTrades(), body=$("journalRows");
  body.replaceChildren();
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.className="empty-row";td.textContent="No journal records yet.";tr.append(td);body.append(tr);}
  rows.slice().reverse().forEach((trade,index)=>{
    const tr=document.createElement("tr");
    [trade.date,trade.symbol,trade.direction,trade.outcome,money(Number(trade.pnl))].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});
    const action=document.createElement("td"),button=document.createElement("button");button.className="delete-btn";button.textContent="Delete";button.setAttribute("aria-label","Delete journal record");button.addEventListener("click",()=>{const current=loadTrades();current.splice(current.length-1-index,1);saveTrades(current);renderJournal();});action.append(button);tr.append(action);body.append(tr);
  });
  $("metricTrades").textContent=String(rows.length);
  $("metricPnl").textContent=money(rows.reduce((sum,t)=>sum+Number(t.pnl||0),0));
}
$("calculate").addEventListener("click",()=>{
  const equity=Number($("equity").value),risk=Number($("risk").value),stop=Number($("stop").value),pip=Number($("pipvalue").value),out=$("lotResult");
  if(![equity,risk,stop,pip].every(Number.isFinite)||equity<=0||risk<=0||risk>100||stop<=0||pip<=0){out.textContent="Enter valid positive values. Risk must be above 0 and no more than 100%.";return;}
  const amount=equity*risk/100,lots=amount/(stop*pip);
  out.replaceChildren();const strong=document.createElement("strong");strong.textContent=lots.toFixed(3)+" lots";out.append(strong,document.createTextNode("Risk amount "+money(amount)+" · Estimated stop loss "+money(lots*stop*pip)));
});
$("saveTrade").addEventListener("click",()=>{
  const symbol=$("symbol").value.trim().toUpperCase(),pnl=Number($("pnl").value);
  if(!symbol||symbol.length>20||$("pnl").value.trim()===""||!Number.isFinite(pnl)){window.alert("Enter a valid symbol and P&L amount.");return;}
  const rows=loadTrades();rows.push({date:new Date().toLocaleDateString("en-CA"),symbol,direction:$("direction").value,outcome:$("outcome").value,pnl,notes:$("notes").value.trim()});
  try{saveTrades(rows);$("symbol").value="";$("pnl").value="";$("notes").value="";renderJournal();}catch{window.alert("Could not save journal data. Browser storage may be full or disabled.");}
});
$("exportJournal").addEventListener("click",()=>{
  const rows=loadTrades();if(!rows.length){window.alert("There are no journal records to export yet.");return;}
  const quote=value=>'"'+String(value??"").replaceAll('"','""')+'"';
  const csv=[["Date","Symbol","Direction","Outcome","PnL","Notes"],...rows.map(t=>[t.date,t.symbol,t.direction,t.outcome,t.pnl,t.notes])].map(row=>row.map(quote).join(",")).join("\r\n");
  const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})),link=document.createElement("a");link.href=url;link.download="quantnex-trading-journal.csv";link.click();URL.revokeObjectURL(url);
});
renderJournal();
// Local QUANTNEX updater: the CMD-launched Python server downloads, extracts and installs releases.
const updateButton = $("webCheckUpdate");
const installButton = $("webInstallUpdate");
const releaseVersionLabel = $("webReleaseVersion");
const releaseNotesLink = $("webReleaseNotes");
let checkedRelease = null;
let updatePolling = false;

function showUpdateToast(message){
  let toast=$("quantnexUpdateToast");
  if(!toast){
    toast=document.createElement("div");toast.id="quantnexUpdateToast";
    toast.setAttribute("role","status");toast.style.cssText="position:fixed;right:22px;bottom:22px;z-index:9999;max-width:360px;padding:15px 18px;border:1px solid #777;border-radius:12px;background:#f2f2f2;color:#090909;box-shadow:0 12px 45px #0009;font:600 13px/1.5 system-ui;animation:rise .3s ease both";
    document.body.append(toast);
  }
  toast.textContent=message;
  window.setTimeout(()=>toast.remove(),7000);
}
if(sessionStorage.getItem("quantnex.webUpdateComplete")==="1"){
  sessionStorage.removeItem("quantnex.webUpdateComplete");
  window.addEventListener("load",()=>showUpdateToast("✓ QUANTNEX Web has been updated. You are now using the latest workspace."));
}

async function checkLocalUpdate(){
  const status=$("webUpdateStatus"),progress=$("webUpdateProgress");
  updateButton.disabled=true;updateButton.textContent="Checking…";progress.hidden=false;
  status.textContent="Checking the latest published QUANTNEX release…";
  try{
    const response=await fetch("/__quantnex/check",{cache:"no-store"});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Local updater is not running.");}
    checkedRelease=await response.json();
    $("webInstalledVersion").textContent=String(checkedRelease.installed).startsWith("v")?checkedRelease.installed:"v"+checkedRelease.installed;
    releaseVersionLabel.textContent=checkedRelease.latest;
    if(checkedRelease.release_notes)releaseNotesLink.href=checkedRelease.release_notes;
    if(checkedRelease.update_available){
      status.textContent="New version "+checkedRelease.latest+" is ready. Install it automatically; QUANTNEX will extract the release, refresh this browser and reopen the updated workspace.";
      installButton.hidden=false;
      installButton.disabled=false;
    }else{
      status.textContent="You already have the latest published release ("+checkedRelease.latest+").";
      installButton.hidden=true;
    }
  }catch(error){
    checkedRelease=null;installButton.hidden=true;
    status.textContent="Automatic updates are available when QUANTNEX is launched using run_quantnex.bat → Start Web Workspace. "+error.message;
  }finally{
    updateButton.disabled=false;updateButton.textContent="Check for updates";progress.hidden=true;
  }
}
if(updateButton)updateButton.addEventListener("click",checkLocalUpdate);

async function watchUpdateInstall(){
  if(updatePolling)return;
  updatePolling=true;
  const status=$("webUpdateStatus");
  const progress=$("webUpdateProgress");
  progress.hidden=false;
  const started=Date.now();
  try{
    while(Date.now()-started<180000){
      await new Promise(resolve=>window.setTimeout(resolve,1200));
      const response=await fetch("/__quantnex/status",{cache:"no-store"});
      const state=await response.json();
      if(state.status==="complete"){
        status.textContent=state.message||"Update installed. Refreshing workspace…";
        sessionStorage.setItem("quantnex.webUpdateComplete","1");
        window.setTimeout(()=>{window.location.replace(window.location.pathname+"?updated="+Date.now());},900);
        return;
      }
      if(state.status==="error")throw new Error(state.message||"Update installation failed.");
      if(state.status==="installing")status.textContent=state.message||"Downloading and extracting update…";
    }
    throw new Error("The update is taking longer than expected. Check the QUANTNEX Web Server CMD window.");
  }catch(error){
    status.textContent="Update did not finish: "+error.message;
    installButton.disabled=false;installButton.textContent="Retry update";
  }finally{
    progress.hidden=true;updatePolling=false;
  }
}
if(installButton)installButton.addEventListener("click",async()=>{
  if(!checkedRelease||!checkedRelease.update_available){await checkLocalUpdate();return;}
  installButton.disabled=true;installButton.textContent="Installing…";
  $("webUpdateStatus").textContent="Starting automatic update…";
  try{
    const response=await fetch("/__quantnex/install",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(data.error||"Could not start update.");
    await watchUpdateInstall();
  }catch(error){
    $("webUpdateStatus").textContent="Could not start update: "+error.message;
    installButton.disabled=false;installButton.textContent="Install update & restart workspace";
  }
});
if(updateButton&&location.hostname==="127.0.0.1"&&location.port==="5500"){
  checkLocalUpdate();
}

// Authenticated shared API wallet. Access tokens stay in this browser tab's session storage.
const API_BASE_KEY = "quantnex.apiBase.v1";
const TOKEN_KEY = "quantnex.sessionToken.v1";
const apiBaseInput = $("apiBase");
const accountMessage = $("accountMessage");
const walletArea = $("walletArea");
apiBaseInput.value = localStorage.getItem(API_BASE_KEY) || "http://127.0.0.1:8000";
function apiBase(){ return apiBaseInput.value.trim().replace(/\/+$/, ""); }
function sessionToken(){ return sessionStorage.getItem(TOKEN_KEY); }
function setAccountMessage(message, error=false){ accountMessage.textContent=message; accountMessage.dataset.state=error?"error":"ok"; }
async function apiRequest(path, options={}){
  const headers={"Accept":"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(sessionToken()?{"Authorization":"Bearer "+sessionToken()}:{}),...(options.headers||{})};
  const response=await fetch(apiBase()+path,{...options,headers});
  const payload=response.status===204?null:await response.json().catch(()=>null);
  if(!response.ok) throw new Error(payload?.detail||("API request failed ("+response.status+")."));
  return payload;
}
function setSignedIn(signedIn){
  $("accountState").textContent=signedIn?"CONNECTED":"NOT CONNECTED";
  $("accountState").classList.toggle("connected",signedIn);
  walletArea.hidden=!signedIn;
  $("accountLogout").hidden=!signedIn;
  $("accountLogin").hidden=signedIn;
  $("accountRegister").hidden=signedIn;
}
function renderWalletTransactions(rows){
  const body=$("walletRows");body.replaceChildren();
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=4;td.className="empty-row";td.textContent="No wallet transactions yet.";tr.append(td);body.append(tr);return;}
  rows.forEach(item=>{const tr=document.createElement("tr");const date=new Date(item.created_at).toLocaleString();const amount=Number(item.amount);[date,item.transaction_type.replaceAll("_"," "),item.description||"—",money(amount)].forEach((value,index)=>{const td=document.createElement("td");td.textContent=value;if(index===3)td.className=amount<0?"negative":"positive";tr.append(td);});body.append(tr);});
}
async function refreshWallet(){
  const [summary,transactions]=await Promise.all([apiRequest("/api/v1/wallet/summary"),apiRequest("/api/v1/wallet/transactions?limit=100")]);
  $("walletBalance").textContent=money(summary.balance);$("walletDeposits").textContent=money(summary.deposits);$("walletWithdrawals").textContent=money(summary.withdrawals);$("walletPnl").textContent=money(summary.trading_pnl);renderWalletTransactions(transactions);
}
async function authenticate(mode){
  const email=$("accountEmail").value.trim(),password=$("accountPassword").value;
  if(!email||!password){setAccountMessage("Enter your email and password.",true);return;}
  if(password.length<12){setAccountMessage("Use a password with at least 12 characters.",true);return;}
  try{
    if(mode==="register") await apiRequest("/api/v1/auth/register",{method:"POST",body:JSON.stringify({email,password})});
    const result=await apiRequest("/api/v1/auth/login",{method:"POST",body:JSON.stringify({email,password})});
    sessionStorage.setItem(TOKEN_KEY,result.access_token);window.dispatchEvent(new Event("quantnex:auth"));$("accountPassword").value="";setSignedIn(true);await refreshWallet();setAccountMessage("Signed in. Wallet data loaded from the shared API.");
  }catch(error){setAccountMessage(error.message,true);}
}
$("saveApiBase").addEventListener("click",()=>{try{const url=new URL(apiBase());if(!["http:","https:"].includes(url.protocol))throw new Error();localStorage.setItem(API_BASE_KEY,url.origin+url.pathname.replace(/\/+$/,""));setAccountMessage("API server URL saved for this browser.");}catch{setAccountMessage("Enter a valid HTTP or HTTPS API URL.",true);}});
$("accountLogin").addEventListener("click",()=>authenticate("login"));
$("accountRegister").addEventListener("click",()=>authenticate("register"));
$("accountLogout").addEventListener("click",()=>{sessionStorage.removeItem(TOKEN_KEY);setSignedIn(false);setAccountMessage("Signed out. Your wallet records remain on the server.");});
async function recordWalletTransaction(type){
  const amountInput=$(type==="deposit"?"depositAmount":"withdrawAmount"),descriptionInput=$(type==="deposit"?"depositDescription":"withdrawDescription"),amount=Number(amountInput.value);
  if(!Number.isFinite(amount)||amount<=0){setAccountMessage("Enter an amount greater than zero.",true);return;}
  try{await apiRequest("/api/v1/wallet/transactions",{method:"POST",body:JSON.stringify({transaction_type:type,amount,description:descriptionInput.value.trim()})});amountInput.value="";descriptionInput.value="";await refreshWallet();setAccountMessage(type==="deposit"?"Deposit record saved.":"Withdrawal record saved.");}
  catch(error){setAccountMessage(error.message,true);}
}
$("walletDeposit").addEventListener("click",()=>recordWalletTransaction("deposit"));
$("walletWithdraw").addEventListener("click",()=>recordWalletTransaction("withdrawal"));
if(sessionToken()){
  setSignedIn(true);refreshWallet().then(()=>setAccountMessage("Restored this tab's session. Wallet data loaded.")).catch(error=>{sessionStorage.removeItem(TOKEN_KEY);setSignedIn(false);setAccountMessage("Session expired or API unavailable: "+error.message,true);});
}else setSignedIn(false);


// Resilient market overview. Prices are sourced by the local API with provider fallbacks.
(function initMarketOverview(){
  const $id=id=>document.getElementById(id);
  const usd=value=>value==null?"Unavailable":"$"+Number(value).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
  const lkr=value=>value==null?"Unavailable":"LKR "+Number(value).toLocaleString("en-LK",{minimumFractionDigits:2,maximumFractionDigits:2});
  async function refresh(){
    try{
      const base=($id("apiBase")?.value||"http://127.0.0.1:8000").trim().replace(/\/+$/,"");
      const response=await fetch(base+"/api/v1/market/overview",{cache:"no-store"});
      if(!response.ok)throw new Error("Market API returned HTTP "+response.status);
      const data=await response.json();
      $id("btcLivePrice").textContent=usd(data.btc_usd);
      $id("goldLivePrice").textContent=usd(data.gold_usd_oz);
      $id("goldLkrGram").textContent=lkr(data.gold_lkr_gram);
      $id("goldLkrEight").textContent=lkr(data.gold_lkr_8g);
      $id("usdLkrRate").textContent=data.usd_lkr==null?"Unavailable":"LKR "+Number(data.usd_lkr).toFixed(2);
      const stamp=data.timestamp?new Date(data.timestamp).toLocaleTimeString():"";
      const sources=data.sources||{};
      $id("btcLiveUpdated").textContent=(data.provider_status?.btc==="ok"?"Updated ":"Unavailable · ")+stamp+" · "+(sources.btc||"BTC provider");
      $id("goldLiveUpdated").textContent=(data.provider_status?.gold==="ok"?"Updated ":"Unavailable · ")+stamp+" · "+(sources.gold||"Gold provider");
      $id("goldLkrNote").textContent=data.note+" "+data.gold_calculation;
    }catch(error){
      ["btcLivePrice","goldLivePrice","goldLkrGram","goldLkrEight","usdLkrRate"].forEach(id=>{if($id(id))$id(id).textContent="Feed unavailable";});
      if($id("btcLiveUpdated"))$id("btcLiveUpdated").textContent="Start QUANTNEX API · "+error.message;
      if($id("goldLkrNote"))$id("goldLkrNote").textContent="BTC and Gold use keyless fallback providers; USD/LKR uses a daily reference rate. Check that the local QUANTNEX API is running.";
    }
  }
  if($id("btcLivePrice")){refresh();window.setInterval(refresh,30000);}
})();


// Responsive TradingView workspace: one renderer for market, timeframe and fullscreen controls.
(function initTradingViewWorkspace(){
  const host=$("xauTradingView"),market=$("tradingViewSymbol"),timeframe=$("tradingViewInterval"),fullscreen=$("chartFullscreen");
  if(!host||!market||!timeframe)return;
  const chartPanel=host.closest(".chart-workspace");
  const supportedIntervals=new Set(["1","5","15","30","60","240","D","W"]);
  function renderChart(options={}){
    const symbol=options.symbol||market.value||"OANDA:XAUUSD";
    const interval=String(options.interval||timeframe.value||"15");
    if(!supportedIntervals.has(interval))return false;
    market.value=symbol;timeframe.value=interval;
    host.replaceChildren();
    const widget=document.createElement("div");
    widget.className="tradingview-widget-container__widget";
    const script=document.createElement("script");
    script.type="text/javascript";script.async=true;
    script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.textContent=JSON.stringify({
      autosize:true,symbol,interval,timezone:"Etc/UTC",theme:"dark",style:"1",locale:"en",
      allow_symbol_change:true,calendar:false,details:false,hotlist:false,save_image:true,
      hide_side_toolbar:false,withdateranges:true,studies:[],support_host:"https://www.tradingview.com"
    });
    host.append(widget,script);
    return true;
  }
  market.addEventListener("change",()=>renderChart());
  timeframe.addEventListener("change",()=>renderChart());
  if(fullscreen&&chartPanel){
    fullscreen.addEventListener("click",async()=>{
      try{
        if(document.fullscreenElement)await document.exitFullscreen();
        else if(chartPanel.requestFullscreen)await chartPanel.requestFullscreen();
      }catch(error){console.warn("Fullscreen is not available:",error);}
    });
    document.addEventListener("fullscreenchange",()=>{
      const active=document.fullscreenElement===chartPanel;
      fullscreen.innerHTML=active?'⛶ <span>EXIT FULL SCREEN</span>':'⛶ <span>FULL SCREEN</span>';
      fullscreen.setAttribute("aria-label",active?"Exit fullscreen chart":"Enter fullscreen chart");
    });
  }
  window.quantnexRenderChart=renderChart;
  renderChart();
})();
