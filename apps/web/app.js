const $ = (id) => document.getElementById(id);
const storageKey = "quantnex.journal.v2";
const journalSourceKey = "quantnex.journal.import_source.v1";
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
function setJournalStatus(message,error=false){
  const status=$("journalStatus");
  if(status){status.textContent=message;status.dataset.state=error?"error":"ok";}
}
function mapServerTrade(item){
  const rawDate=String(item.created_at||"");
  const date=new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(rawDate)?rawDate:rawDate+"Z");
  const title=value=>String(value||"").charAt(0).toUpperCase()+String(value||"").slice(1).toLowerCase();
  return {id:item.id,date:Number.isNaN(date.getTime())?"":date.toLocaleDateString("en-CA"),
    symbol:String(item.symbol||""),direction:title(item.direction),outcome:title(item.outcome),
    pnl:Number(item.pnl)||0,notes:String(item.notes||"")};
}
let journalRowsCache=loadTrades();
function renderJournal(){
  const rows=journalRowsCache, body=$("journalRows");
  body.replaceChildren();
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.className="empty-row";td.textContent="No journal records yet.";tr.append(td);body.append(tr);}
  rows.slice().reverse().forEach((trade,index)=>{
    const tr=document.createElement("tr");
    [trade.date,trade.symbol,trade.direction,trade.outcome,money(Number(trade.pnl))].forEach(value=>{const td=document.createElement("td");td.textContent=value;tr.append(td);});
    const action=document.createElement("td"),button=document.createElement("button");button.className="delete-btn";button.textContent="Delete";button.setAttribute("aria-label","Delete journal record");
    button.addEventListener("click",async()=>{
      const target=journalRowsCache[journalRowsCache.length-1-index];
      if(target?.id){
        try{await apiRequest("/api/v1/journal/"+target.id,{method:"DELETE"});}
        catch(error){setJournalStatus("Could not delete journal record: "+error.message,true);return;}
      }
      if(target?.id){
        journalRowsCache=journalRowsCache.filter(row=>row.id!==target.id);
      }else{
        const current=journalRowsCache.slice();current.splice(current.length-1-index,1);journalRowsCache=current;
      }
      try{saveTrades(journalRowsCache);}catch{}
      renderJournal();setJournalStatus("Journal record deleted.");
    });
    action.append(button);tr.append(action);
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
$("saveTrade").addEventListener("click",async()=>{
  const symbol=$("symbol").value.trim().toUpperCase(),pnl=Number($("pnl").value);
  if(!symbol||symbol.length>20||$("pnl").value.trim()===""||!Number.isFinite(pnl)){window.alert("Enter a valid symbol and P&L amount.");return;}
  const trade={client_ref:newJournalRef(),record_wallet:true,date:new Date().toLocaleDateString("en-CA"),symbol,direction:$("direction").value,outcome:$("outcome").value,pnl,notes:$("notes").value.trim()};
  let saved;
  try{
    saved=await apiRequest("/api/v1/journal",{method:"POST",body:JSON.stringify({
      symbol:trade.symbol,direction:trade.direction.toLowerCase(),outcome:trade.outcome.toLowerCase(),pnl:trade.pnl,notes:trade.notes,
      created_at:new Date(trade.date+"T12:00:00").toISOString(),client_ref:trade.client_ref
    })});
  }catch(error){
    journalRowsCache.push(trade);
    try{saveTrades(journalRowsCache);}catch{}
    renderJournal();setJournalStatus("Backend unavailable. Trade is safely queued in the browser recovery copy for later sync.",true);
    $("symbol").value="";$("pnl").value="";$("notes").value="";
    return;
  }
  const savedRow=mapServerTrade(saved);
  if(!journalRowsCache.some(row=>row.id===savedRow.id))journalRowsCache.push(savedRow);
  try{saveTrades(journalRowsCache);}catch{}
  renderJournal();setJournalStatus("Trade saved to the local QUANTNEX database.");
  $("symbol").value="";$("pnl").value="";$("notes").value="";
});
$("exportJournal").addEventListener("click",()=>{
  const rows=journalRowsCache;if(!rows.length){window.alert("There are no journal records to export yet.");return;}
  const csv=window.QuantnexJournalExport.toCsv(rows);
  const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})),link=document.createElement("a");link.href=url;link.download="quantnex-trading-journal.csv";link.click();URL.revokeObjectURL(url);
});
renderJournal();
// Local QUANTNEX updater. New versions are announced first; installation always needs user approval.
const updateButton=$("webCheckUpdate");
const installButton=$("webInstallUpdate");
const releaseVersionLabel=$("webReleaseVersion");
const releaseNotesLink=$("webReleaseNotes");
const updateModal=$("webUpdateModal");
const modalInstallButton=$("webUpdateModalInstall");
let updatePolling=false;
let updateChecking=false;
let latestUpdateCommit="";

function showUpdateToast(message){
  let toast=$("quantnexUpdateToast");
  if(!toast){
    toast=document.createElement("div");toast.id="quantnexUpdateToast";
    toast.setAttribute("role","status");
    toast.style.cssText="position:fixed;right:22px;bottom:22px;z-index:9999;max-width:360px;padding:15px 18px;border:1px solid #777;border-radius:12px;background:#f2f2f2;color:#090909;box-shadow:0 12px 45px #0009;font:600 13px/1.5 system-ui;animation:rise .3s ease both";
    document.body.append(toast);
  }
  toast.textContent=message;
  window.setTimeout(()=>toast.remove(),7000);
}

function updateDismissed(sha){
  try{return sessionStorage.getItem("quantnex.updateNoticeDismissed")===sha;}catch{return false;}
}
function rememberUpdateDismissed(sha){
  try{sessionStorage.setItem("quantnex.updateNoticeDismissed",sha);}catch{}
}
function renderUpdateDetails(result,announce=true){
  const details=$("webUpdateDetails"),summary=$("webUpdateSummary"),list=$("webUpdateChanges"),meta=$("webUpdateMeta");
  const messages=Array.isArray(result.changes)?result.changes.filter(Boolean).slice(0,8):[];
  summary.textContent=result.latest_message||"A new QUANTNEX source update is available.";
  list.replaceChildren();
  messages.forEach(message=>{
    const item=document.createElement("li");item.textContent=String(message);list.append(item);
  });
  if(!messages.length){const item=document.createElement("li");item.textContent="Workspace improvements and fixes.";list.append(item);}
  const commits=Number(result.commits_behind)||0,files=Number(result.files_changed)||0;
  meta.textContent=(commits?commits+" commit"+(commits===1?"":"s"):"Latest commit")+(files?" · "+files+" files changed":"")+" · Source verified from GitHub main";
  details.hidden=false;
  $("webUpdateModalSummary").textContent=summary.textContent;
  const modalList=$("webUpdateModalChanges");modalList.replaceChildren();
  messages.forEach(message=>{const item=document.createElement("li");item.textContent=String(message);modalList.append(item);});
  if(!messages.length){const item=document.createElement("li");item.textContent="Workspace improvements and fixes.";modalList.append(item);}
  $("webUpdateModalMeta").textContent=meta.textContent;
  $("webUpdateModalVersion").textContent=result.latest||"Latest version";
  if(announce)window.QuantnexOnboarding?.showRelease(result);
}
function openUpdateModal(result){
  if(window.QuantnexOnboarding?.isReleaseOpen())return;
  if(!updateModal)return;
  const sha=result.commit_sha||result.latest||"";
  if(updateDismissed(sha))return;
  updateModal.hidden=false;
  document.body.classList.add("web-update-modal-open");
  if(typeof window.quantnexNavigate==="function")window.quantnexNavigate("updates");
  else $("updates")?.scrollIntoView({behavior:"smooth",block:"start"});
  window.setTimeout(()=>modalInstallButton?.focus(),180);
}
function closeUpdateModal(remindLater=true){
  if(!updateModal)return;
  if(remindLater&&latestUpdateCommit)rememberUpdateDismissed(latestUpdateCommit);
  updateModal.hidden=true;
  document.body.classList.remove("web-update-modal-open");
  installButton?.focus();
}
$("webUpdateModalClose")?.addEventListener("click",()=>closeUpdateModal(true));
$("webUpdateModalLater")?.addEventListener("click",()=>closeUpdateModal(true));
updateModal?.addEventListener("click",event=>{if(event.target===updateModal)closeUpdateModal(true);});
window.addEventListener("keydown",event=>{if(event.key==="Escape"&&updateModal&&!updateModal.hidden)closeUpdateModal(true);});

if(sessionStorage.getItem("quantnex.webUpdateComplete")==="1"){
  sessionStorage.removeItem("quantnex.webUpdateComplete");
  const installedVersion=sessionStorage.getItem("quantnex.webUpdateVersion")||"latest";
  const installedHeadline=sessionStorage.getItem("quantnex.webUpdateHeadline")||"QUANTNEX Web update";
  sessionStorage.removeItem("quantnex.webUpdateVersion");
  sessionStorage.removeItem("quantnex.webUpdateHeadline");
  const announceInstalledUpdate=()=>{
    showUpdateToast("✓ QUANTNEX has been updated successfully.");
    const safeVersion=String(installedVersion||"latest").slice(0,80);
    const safeHeadline=String(installedHeadline||"Workspace improvements").replace(/\s+/g," ").slice(0,120);
    const message=[
      "✦ QUANTNEX",
      "WEB UPDATE INSTALLED",
      "",
      "Version: "+safeVersion,
      "Update: "+safeHeadline,
      "",
      "✓ Workspace updated successfully",
      "✓ Wallet, journal and settings preserved",
      "",
      "You're all set. Trade responsibly."
    ].join("\n");
    // The local API uses the user's existing encrypted bot credentials. A missing
    // Telegram connection is an intentional opt-out and does not affect the update.
    apiRequest("/api/v1/telegram/notify",{method:"POST",body:JSON.stringify({message})}).catch(()=>{});
  };
  if(document.readyState==="complete")announceInstalledUpdate();
  else window.addEventListener("load",announceInstalledUpdate,{once:true});
}

async function watchUpdateInstall(){
  if(updatePolling)return;
  updatePolling=true;
  const status=$("webUpdateStatus"),progress=$("webUpdateProgress");
  progress.hidden=false;
  updateButton.disabled=true;
  if(installButton)installButton.disabled=true;
  if(modalInstallButton)modalInstallButton.disabled=true;
  const started=Date.now();
  try{
    while(Date.now()-started<180000){
      await new Promise(resolve=>window.setTimeout(resolve,1200));
      const response=await fetch("/__quantnex/status",{cache:"no-store"});
      const state=await response.json();
      if(state.status==="complete"){
        status.textContent=state.message||"Update installed. Refreshing workspace…";
        sessionStorage.setItem("quantnex.webUpdateComplete","1");
        sessionStorage.setItem("quantnex.webUpdateVersion",latestUpdateCommit||"");
        sessionStorage.setItem("quantnex.webUpdateHeadline",$("webUpdateSummary")?.textContent||"QUANTNEX Web update");
        window.setTimeout(()=>window.location.replace(window.location.pathname+"?updated="+Date.now()),900);
        return;
      }
      if(state.status==="error")throw new Error(state.message||"Update installation failed.");
      if(state.status==="installing"||state.status==="starting")status.textContent=state.message||"Downloading and installing the verified GitHub update…";
    }
    throw new Error("The update is taking longer than expected. Check the QUANTNEX Web Server CMD window.");
  }catch(error){
    status.textContent="Update did not finish: "+error.message;
    showUpdateToast("Update could not be installed. Your current workspace is unchanged.");
  }finally{
    progress.hidden=true;updatePolling=false;
    updateButton.disabled=false;updateButton.textContent="Check for updates";
    if(installButton)installButton.disabled=false;
    if(modalInstallButton)modalInstallButton.disabled=false;
  }
}

async function installLatestCommit(){
  if(updatePolling)return;
  closeUpdateModal(false);
  const status=$("webUpdateStatus");
  status.textContent="Preparing the verified GitHub update…";
  if(installButton){installButton.disabled=true;installButton.textContent="Installing…";}
  const response=await fetch("/__quantnex/install",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){
    if(installButton){installButton.disabled=false;installButton.textContent="Download & install now";}
    throw new Error(data.error||"Could not start update.");
  }
  await watchUpdateInstall();
}
modalInstallButton?.addEventListener("click",()=>installLatestCommit().catch(error=>showUpdateToast(error.message)));
installButton?.addEventListener("click",()=>installLatestCommit().catch(error=>showUpdateToast(error.message)));

async function checkLocalUpdate(options={}){
  if(updateChecking||updatePolling)return;
  updateChecking=true;
  const silent=Boolean(options.silent);
  const status=$("webUpdateStatus"),progress=$("webUpdateProgress");
  updateButton.disabled=true;
  if(!silent){updateButton.textContent="Checking…";progress.hidden=false;status.textContent="Checking the latest QUANTNEX version on GitHub…";}
  try{
    const response=await fetch("/__quantnex/check",{cache:"no-store"});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Local updater is not running.");}
    const result=await response.json();
    if(result.managed_by_supervisor){
      $("webInstalledVersion").textContent=result.installed||"Supervisor managed";
      releaseVersionLabel.textContent=result.latest||"Automatic source updates";
      $("webUpdateDetails").hidden=true;
      if(installButton)installButton.hidden=true;
      status.textContent=result.message||"Full source updates are handled by the QUANTNEX supervisor.";
      return;
    }
    $("webInstalledVersion").textContent=result.installed||"Unknown";
    releaseVersionLabel.textContent=result.latest||"Not available";
    if(result.release_notes)releaseNotesLink.href=result.release_notes;
    if(result.update_available){
      latestUpdateCommit=result.commit_sha||result.latest||"";
      renderUpdateDetails(result,false);
      status.textContent="New update detected: "+result.latest+". QUANTNEX is installing it automatically…";
      if(installButton)installButton.hidden=false;
      // Startup and five-minute background checks install the pinned main commit
      // automatically. The existing manual button remains available if a retry is needed.
      await installLatestCommit();
    }else{
      latestUpdateCommit="";
      $("webUpdateDetails").hidden=true;
      if(installButton)installButton.hidden=true;
      status.textContent="You are using the latest QUANTNEX version ("+result.latest+").";
    }
  }catch(error){
    if(!silent)status.textContent="Update check failed safely: "+error.message;
  }finally{
    updateChecking=false;
    progress.hidden=true;
    updateButton.disabled=false;updateButton.textContent="Check for updates";
  }
}
if(updateButton)updateButton.addEventListener("click",()=>checkLocalUpdate());
if(updateButton&&["127.0.0.1","localhost"].includes(location.hostname)&&location.port==="5500"){
  checkLocalUpdate();
  window.setInterval(()=>{
    if(document.visibilityState==="visible")checkLocalUpdate({silent:true});
  },300000);
}
// Local-only wallet API. The backend listens on loopback and has no login/session system.
const accountMessage = $("accountMessage");
function setAccountMessage(message, error=false){ accountMessage.textContent=message; accountMessage.dataset.state=error?"error":"ok"; }
async function apiRequest(path, options={}){
  const headers={"Accept":"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(options.headers||{})};
  const response=await fetch("http://127.0.0.1:8000"+path,{...options,headers,cache:"no-store"});
  const payload=response.status===204?null:await response.json().catch(()=>null);
  if(!response.ok) throw new Error(payload?.detail||("API request failed ("+response.status+")."));
  return payload;
}
let journalSyncing=false;
function newJournalRef(){
  return window.crypto?.randomUUID?.()||("qnx-row-"+Date.now()+"-"+Math.random().toString(16).slice(2));
}
async function syncJournal(){
  if(journalSyncing)return;
  journalSyncing=true;
  try{
    const pending=journalRowsCache.filter(row=>!row.id);
    if(pending.length){
      let sourceId=localStorage.getItem(journalSourceKey);
      if(!sourceId){
        sourceId=window.crypto?.randomUUID?.()||("qnx-"+Date.now()+"-"+Math.random().toString(16).slice(2));
        localStorage.setItem(journalSourceKey,sourceId);
      }
      pending.forEach((row,index)=>{if(!row.client_ref)row.client_ref="legacy-"+sourceId+"-"+String(index).padStart(6,"0");});
      try{saveTrades(journalRowsCache);}catch{}
      const normalized=pending.map(row=>{
        const dateText=String(row.date||"").slice(0,10);
        const parsed=dateText?new Date(dateText+"T12:00:00"):null;
        return {
          source_ref:row.client_ref,
          date:parsed&&!Number.isNaN(parsed.getTime())?parsed.toISOString():"",
          symbol:String(row.symbol||"").trim().toUpperCase().slice(0,20),
          direction:["buy","sell"].includes(String(row.direction||"").toLowerCase())?String(row.direction).toLowerCase():"buy",
          outcome:["win","loss","breakeven"].includes(String(row.outcome||"").toLowerCase())?String(row.outcome).toLowerCase():"breakeven",
          pnl:Number.isFinite(Number(row.pnl))?Number(row.pnl):0,
          notes:String(row.notes||"").slice(0,2000),
          record_wallet:row.record_wallet===true
        };
      });
      for(let offset=0;offset<normalized.length;offset+=500){
        await apiRequest("/api/v1/journal/import",{method:"POST",body:JSON.stringify({
          source_id:sourceId,rows:normalized.slice(offset,offset+500)
        })});
      }
    }
    const remote=await apiRequest("/api/v1/journal?limit=500");
    journalRowsCache=remote.slice().reverse().map(mapServerTrade);
    saveTrades(journalRowsCache);renderJournal();
    setJournalStatus("Journal synced with the local QUANTNEX database. A browser recovery copy is retained.");
  }catch(error){
    renderJournal();
    setJournalStatus("Showing the browser recovery copy. Database sync failed: "+error.message,true);
  }finally{
    journalSyncing=false;
  }
}
window.addEventListener("online",()=>syncJournal());
window.addEventListener("quantnex:workspace-resync",()=>syncJournal());
window.addEventListener("quantnex:workspace-event",event=>{
  if(event.detail?.type==="journal.changed")syncJournal();
});
async function refreshWallet(){
  const [summary,transactions]=await Promise.all([apiRequest("/api/v1/wallet/summary"),apiRequest("/api/v1/wallet/transactions?limit=100")]);
  $("walletBalance").textContent=money(summary.balance);$("walletDeposits").textContent=money(summary.deposits);$("walletWithdrawals").textContent=money(summary.withdrawals);$("walletPnl").textContent=money(summary.trading_pnl);renderWalletTransactions(transactions);
}
window.addEventListener("quantnex:workspace-event",event=>{
  if(event.detail?.type==="wallet.changed")refreshWallet().catch(error=>setAccountMessage("Wallet refresh failed: "+error.message,true));
});
window.addEventListener("quantnex:workspace-resync",()=>refreshWallet().catch(error=>setAccountMessage("Wallet refresh failed: "+error.message,true)));
async function recordWalletTransaction(type){
  const amountInput=$(type==="deposit"?"depositAmount":"withdrawAmount"),descriptionInput=$(type==="deposit"?"depositDescription":"withdrawDescription"),amount=Number(amountInput.value);
  if(!Number.isFinite(amount)||amount<=0||amount>1000000000){setAccountMessage("Enter a finite amount greater than zero and no more than $1,000,000,000.",true);return;}
  try{await apiRequest("/api/v1/wallet/transactions",{method:"POST",body:JSON.stringify({transaction_type:type,amount,description:descriptionInput.value.trim()})});amountInput.value="";descriptionInput.value="";await refreshWallet();setAccountMessage(type==="deposit"?"Deposit record saved locally.":"Withdrawal record saved locally.");}
  catch(error){setAccountMessage(error.message,true);}
}
$("walletDeposit").addEventListener("click",()=>recordWalletTransaction("deposit"));
$("walletWithdraw").addEventListener("click",()=>recordWalletTransaction("withdrawal"));
refreshWallet().then(()=>setAccountMessage("Local wallet loaded. Your data stays on this computer.")).catch(error=>setAccountMessage("Local API unavailable: "+error.message,true));


// Resilient market overview. Prices are sourced by the local API with provider fallbacks.
(function initMarketOverview(){
  const $id=id=>document.getElementById(id);
  const usd=value=>value==null?"Unavailable":"$"+Number(value).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
  const lkr=value=>value==null?"Unavailable":"LKR "+Number(value).toLocaleString("en-LK",{minimumFractionDigits:2,maximumFractionDigits:2});
  async function refresh(){
    try{
      const response=await fetch("http://127.0.0.1:8000/api/v1/market/overview",{cache:"no-store"});
      if(!response.ok)throw new Error("Market API returned HTTP "+response.status);
      const data=await response.json();
      $id("btcLivePrice").textContent=usd(data.btc_usd);
      $id("goldLivePrice").textContent=usd(data.gold_usd_oz);
      $id("goldLkrGram").textContent=lkr(data.gold_lkr_gram);
      $id("goldLkrEight").textContent=lkr(data.gold_lkr_8g);
      $id("usdLkrRate").textContent=data.usd_lkr==null?"Unavailable":"LKR "+Number(data.usd_lkr).toFixed(2);
      const stamp=data.timestamp?new Date(data.timestamp).toLocaleTimeString():"";
      const sources=data.sources||{};
      const eventTime=data.timestamp?Date.parse(data.timestamp):Date.now();
      [["XAUUSD",data.gold_usd_oz,sources.gold]].forEach(([symbol,price,source])=>{
        if(Number.isFinite(Number(price))&&Number(price)>0){
          window.dispatchEvent(new CustomEvent("quantnex:market-tick",{detail:{symbol,price:Number(price),eventTime,kind:"provider_quote",source:source||"Market provider"}}));
        }
      });
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

;

// Live BTC/XAUUSD gross P&L estimate from the latest available market events.
(function initLivePnlCalculator(){
  const symbolInput=$("livePnlSymbol");
  if(!symbolInput)return;
  const prices=new Map();
  const money=value=>(value<0?"−":"+")+"$"+Math.abs(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const priceText=value=>"$"+Number(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  function update(){
    const symbol=symbolInput.value,price=prices.get(symbol);
    const unit=$("livePnlUnit"),quantity=$("livePnlQuantity");
    if(unit)unit.textContent=symbol==="BTCUSDT"?"BTC":"lots";
    if(quantity)quantity.placeholder=symbol==="BTCUSDT"?"0.001":"0.01";
    const contractWrap=$("livePnlContractSizeWrap");
    if(contractWrap)contractWrap.hidden=symbol!=="XAUUSD";
    $("livePnlCurrent").textContent=Number.isFinite(price)?priceText(price):"Waiting for quote…";
    if(!Number.isFinite(price)){
      $("livePnlUpdated").textContent="Waiting for "+(symbol==="BTCUSDT"?"Binance trade feed":"Gold provider quote");
      $("livePnlResult").textContent="—";$("livePnlMove").textContent="Live price not available";return;
    }
    const entry=Number($("livePnlEntry").value),qty=Number(quantity.value),direction=$("livePnlSide").value==="LONG"?1:-1;
    const contractSize=symbol==="XAUUSD"?Number($("livePnlContractSize").value):1;
    if(!Number.isFinite(entry)||entry<=0||!Number.isFinite(qty)||qty<=0||!Number.isFinite(contractSize)||contractSize<=0){
      $("livePnlResult").textContent="—";$("livePnlMove").textContent="Enter valid entry, quantity and contract size";return;
    }
    const pnl=(price-entry)*qty*contractSize*direction,pct=((price-entry)/entry)*direction*100;
    $("livePnlResult").textContent=money(pnl);
    $("livePnlResult").className=pnl>=0?"positive":"negative";
    $("livePnlMove").textContent=(pct>=0?"+":"")+pct.toFixed(3)+"% price move · gross estimate";
  }
  window.addEventListener("quantnex:market-tick",event=>{
    const data=event.detail||{},symbol=String(data.symbol||"").toUpperCase(),price=Number(data.price);
    if((symbol==="BTCUSDT"||symbol==="XAUUSD")&&Number.isFinite(price)&&price>0){
      prices.set(symbol,price);
      if(symbol===symbolInput.value){
        $("livePnlUpdated").textContent=(data.source||"Market feed")+" · "+new Date(Number(data.eventTime)||Date.now()).toLocaleTimeString();
        update();
      }
    }
  });
  [symbolInput,$("livePnlSide"),$("livePnlEntry"),$("livePnlQuantity"),$("livePnlContractSize")].forEach(input=>{
    input.addEventListener("input",update);input.addEventListener("change",update);
  });
  update();
})();

// Phase 06.3 local system health, backup and audit UI.
(function initSystemSecurity(){
  const panel=document.querySelector(".system-security-panel");
  if(!panel)return;
  const status=$("systemSecurityMessage");
  const setStatus=(message,error=false)=>{status.textContent=message;status.dataset.state=error?"error":"ok";};
  const bytes=value=>{
    if(value==null)return "—";
    const units=["B","KB","MB","GB","TB"];let n=Number(value),i=0;
    while(n>=1024&&i<units.length-1){n/=1024;i++;}
    return n.toFixed(i===0?0:1)+" "+units[i];
  };
  const cell=(row,value,className="")=>{
    const td=document.createElement("td");td.textContent=value??"—";if(className)td.className=className;row.append(td);return td;
  };
  async function refreshHealth(){
    try{
      const data=await apiRequest("/api/v1/system/health");
      $("systemDbStatus").textContent=data.database.connected?"Connected":"Unavailable";
      $("systemDbSize").textContent=data.database.size_bytes==null?"Size not available":bytes(data.database.size_bytes);
      $("systemCpu").textContent=Number(data.system.cpu_percent).toFixed(0)+"%";
      $("systemMemory").textContent=Number(data.system.memory_percent).toFixed(0)+"%";
      $("systemDisk").textContent=bytes(data.system.disk_free_bytes);
      $("systemDiskTotal").textContent=bytes(data.system.disk_total_bytes)+" total";
      $("systemHealthStatus").textContent="Healthy · "+data.backups.count+" local backups · latest "+(data.backups.latest?"recorded":"not yet created");
    }catch(error){
      $("systemHealthStatus").textContent="Local API unavailable: "+error.message;
      $("systemDbStatus").textContent="Offline";
    }
  }
  async function refreshBackups(){
    const body=$("systemBackupRows");body.replaceChildren();
    try{
      const data=await apiRequest("/api/v1/system/backups");
      if(!data.items.length){const tr=document.createElement("tr");cell(tr,"No backups yet. Create one now or wait for the daily backup worker.","empty-row").colSpan=5;body.append(tr);return;}
      data.items.forEach(item=>{
        const tr=document.createElement("tr");
        cell(tr,item.filename);
        cell(tr,item.created_at?new Date(item.created_at).toLocaleString():"—");
        cell(tr,bytes(item.size_bytes));
        cell(tr,item.verified?"Verified":"Needs verification",item.verified?"positive":"negative");
        const actions=cell(tr,"");
        const verify=document.createElement("button");verify.className="secondary-btn compact-btn";verify.textContent="Verify";
        verify.addEventListener("click",async()=>{
          try{await apiRequest("/api/v1/system/backups/"+encodeURIComponent(item.filename)+"/verify",{method:"POST"});setStatus("Backup integrity check passed: "+item.filename);await refreshBackups();}
          catch(error){setStatus("Backup verification failed: "+error.message,true);await refreshBackups();}
        });
        actions.append(verify);
        if(item.verified){
          const restore=document.createElement("button");restore.className="secondary-btn compact-btn restore-btn";restore.textContent="Restore";
          restore.addEventListener("click",async()=>{
            if(!window.confirm("Restore this backup? QUANTNEX will first create a separate backup of the current database. The current wallet and journal will be replaced with the selected snapshot."))return;
            try{
              restore.disabled=true;setStatus("Restoring database safely…");
              const result=await apiRequest("/api/v1/system/backups/"+encodeURIComponent(item.filename)+"/restore",{method:"POST"});
              setStatus("Restore complete. Safety backup: "+(result.pre_restore_backup||"not needed")+". Refreshing workspace…");
              await Promise.all([refreshHealth(),refreshBackups(),refreshAudit()]);
            }catch(error){setStatus("Restore failed: "+error.message,true);}
            finally{restore.disabled=false;}
          });
          actions.append(restore);
        }
        body.append(tr);
      });
    }catch(error){
      const tr=document.createElement("tr");cell(tr,"Could not load backups: "+error.message,"empty-row").colSpan=5;body.append(tr);
    }
  }
  async function refreshAudit(){
    const body=$("systemAuditRows");body.replaceChildren();
    try{
      const data=await apiRequest("/api/v1/system/audit?limit=100");
      if(!data.items.length){const tr=document.createElement("tr");cell(tr,"No audit events recorded yet.","empty-row").colSpan=4;body.append(tr);return;}
      data.items.forEach(item=>{
        const tr=document.createElement("tr");
        cell(tr,new Date(item.created_at).toLocaleString());
        cell(tr,item.event_type);
        cell(tr,item.severity,item.severity==="warning"?"negative":"");
        cell(tr,item.details);
        body.append(tr);
      });
    }catch(error){
      const tr=document.createElement("tr");cell(tr,"Could not load audit log: "+error.message,"empty-row").colSpan=4;body.append(tr);
    }
  }
  $("refreshSystemBackups").addEventListener("click",refreshBackups);
  $("refreshSystemAudit").addEventListener("click",refreshAudit);
  $("createSystemBackup").addEventListener("click",async()=>{
    try{
      $("createSystemBackup").disabled=true;setStatus("Creating a consistent SQLite snapshot and checking its integrity…");
      const result=await apiRequest("/api/v1/system/backups",{method:"POST"});
      setStatus("Backup created and verified: "+result.filename);
      await Promise.all([refreshHealth(),refreshBackups(),refreshAudit()]);
    }catch(error){setStatus("Backup failed: "+error.message,true);}
    finally{$("createSystemBackup").disabled=false;}
  });
  refreshHealth();refreshBackups();refreshAudit();
})();


// Phase 07 — multi-market intelligence and paper-only trading UI.
(function initPhase07(){
  const ids=["p7RefreshMarkets","p7RunScan","p7LoadBook","p7LoadNews","p7OpenPaper","p7CalculateRisk"];
  if(!$(ids[0]))return;
  const fmt=(value,digits=2)=>value==null||!Number.isFinite(Number(value))?"—":Number(value).toLocaleString(undefined,{maximumFractionDigits:digits});
  const priceDigits=symbol=>symbol==="XAUUSD"?2:["EURUSD","GBPUSD","USDJPY"].includes(symbol)?5:symbol==="BTCUSDT"?2:4;
  const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
  const setMessage=(id,message,error=false)=>{const el=$(id);if(!el)return;el.textContent=message;el.className=error?"p7-note p7-status-error":"p7-note p7-status-ok";};
  const activeWorkspaceView=()=>document.querySelector(".workspace-view:not([hidden])")?.dataset.workspaceView||"overview";
  const isWorkspaceViewActive=(...views)=>!document.hidden&&views.includes(activeWorkspaceView());
  const addCell=(row,text)=>row.append(node("td",text));
  let lastSignal=null;
  const marketCards=new Map();
  async function loadMarkets(){
    const root=$("p7MarketCards");
    try{
      const data=await apiRequest("/api/v1/intelligence/markets");
      root.replaceChildren();marketCards.clear();
      data.items.forEach(item=>{
        const card=node("article",undefined,"p7-market-card");
        const top=node("div",undefined,"p7-symbol");top.append(node("span",item.symbol),node("span",item.kind.toUpperCase()));card.append(top);
        card.append(node("small",item.label));
        const price=node("strong",item.status==="ok"?fmt(item.price,priceDigits(item.symbol)):"Unavailable");
        const change=Number(item.change_percent||0);
        const changeNode=node("small",item.status==="ok"?(change>=0?"+":"")+fmt(change,2)+"% · 24h change":item.reason,item.status==="ok"?(change>=0?"positive":"negative"):"unavailable");
        const range=node("small",item.status==="ok"?"High "+fmt(item.high_24h,priceDigits(item.symbol))+" · Low "+fmt(item.low_24h,priceDigits(item.symbol)):"");
        const source=node("small",item.status==="ok"?item.provider+" · "+new Date(item.timestamp).toLocaleTimeString():"");
        card.append(price,changeNode,range,source);root.append(card);
        marketCards.set(item.symbol,{price,change:changeNode,range,source,item});
      });
      $("p7MarketNote").textContent=data.note+" Crypto prices update from Binance WebSocket; Gold/Forex refresh according to provider availability.";
    }catch(error){if(!root.children.length)root.replaceChildren(node("div","Market feed unavailable: "+error.message,"p7-empty"));}
  }
  let tickerSocket=null,tickerRetry=null,tickerReconnectAttempts=0,tickerLastMessageAt=0,tickerWatchdog=null;
  let bookSocket=null,bookRetry=null,bookReconnectAttempts=0,bookLastMessageAt=0,bookWatchdog=null;
  let bookGeneration=0,bookHistory=[],latestBookData=null,bookRenderTimer=null,lastBookTableAt=0;
  function scheduleTickerReconnect(){
    if(tickerRetry||document.hidden)return;
    const delay=Math.min(30000,1000*Math.pow(2,Math.min(tickerReconnectAttempts,5)));
    tickerReconnectAttempts=Math.min(tickerReconnectAttempts+1,6);
    window.dispatchEvent(new CustomEvent("quantnex:stream-status",{detail:{feed:"crypto",status:"reconnecting",retry_in_ms:delay,attempt:tickerReconnectAttempts}}));
    tickerRetry=setTimeout(()=>{tickerRetry=null;connectCryptoTicker();},delay);
  }
  function connectCryptoTicker(){
    if(document.hidden||tickerSocket||!window.WebSocket)return;
    try{
      tickerSocket=new WebSocket("wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/solusdt@trade/btcusdt@ticker/ethusdt@ticker/solusdt@ticker");
      tickerSocket.onopen=()=>{tickerLastMessageAt=Date.now();window.dispatchEvent(new CustomEvent("quantnex:stream-status",{detail:{feed:"crypto",status:"connected"}}));};
      tickerSocket.onmessage=event=>{
        tickerLastMessageAt=Date.now();
        try{
          const packet=JSON.parse(event.data),data=packet.data||packet;tickerReconnectAttempts=0;
          const symbol=String(data.s||"").toUpperCase(),refs=marketCards.get(symbol);
          const isTrade=data.e==="trade";
          const price=Number(isTrade?data.p:data.c),change=Number(data.P),high=Number(data.h),low=Number(data.l);
          const eventTime=Number(isTrade?data.T:data.E)||Date.now();
          if(refs){
            if(Number.isFinite(price))refs.price.textContent=fmt(price,priceDigits(symbol));
            if(!isTrade){
              refs.change.textContent=(change>=0?"+":"")+fmt(change,2)+"% · 24h change";
              refs.change.className=change>=0?"positive":"negative";
              refs.range.textContent="High "+fmt(high,priceDigits(symbol))+" · Low "+fmt(low,priceDigits(symbol));
            }
            refs.source.textContent="Binance WebSocket · "+new Date(eventTime).toLocaleTimeString();
          }
          if(symbol==="BTCUSDT"&&Number.isFinite(price)&&$("btcLivePrice")){
            $("btcLivePrice").textContent=fmt(price,2);
            $("btcLiveUpdated").textContent="Live trade · "+new Date(eventTime).toLocaleTimeString()+" · Binance";
          }
          window.dispatchEvent(new CustomEvent("quantnex:market-tick",{detail:{symbol,price,eventTime,kind:isTrade?"trade":"ticker",volume:isTrade?Number(data.q||0):0,source:"Binance WebSocket"}}));
        }catch{}
      };
      tickerSocket.onclose=()=>{if(tickerWatchdog){clearInterval(tickerWatchdog);tickerWatchdog=null;}tickerSocket=null;if(!document.hidden)scheduleTickerReconnect();};
      tickerSocket.onerror=()=>{try{tickerSocket?.close();}catch{}};
      tickerWatchdog=setInterval(()=>{if(!document.hidden&&tickerSocket&&tickerSocket.readyState===WebSocket.OPEN&&tickerLastMessageAt&&Date.now()-tickerLastMessageAt>30000){window.dispatchEvent(new CustomEvent("quantnex:stream-status",{detail:{feed:"crypto",status:"stale"}}));try{tickerSocket.close();}catch{}}},10000);
    }catch{tickerSocket=null;scheduleTickerReconnect();}
  }
  function stopCryptoTicker(){
    clearTimeout(tickerRetry);tickerRetry=null;
    if(tickerWatchdog){clearInterval(tickerWatchdog);tickerWatchdog=null;}
    if(tickerSocket){tickerSocket.onclose=null;tickerSocket.close();tickerSocket=null;}
  }
  function renderBookmap(symbol,bids,asks){
    latestBookData={symbol,bids:bids.slice(0,20).map(row=>[Number(row[0]),Number(row[1])]),asks:asks.slice(0,20).map(row=>[Number(row[0]),Number(row[1])]),receivedAt:Date.now()};
    bookHistory.push(latestBookData);
    if(bookHistory.length>120)bookHistory.shift();
    if(bookRenderTimer===null)bookRenderTimer=setTimeout(drawBookmap,90);
  }
  function drawBookmap(){
    bookRenderTimer=null;
    const root=$("p7Bookmap"),canvas=$("p7BookmapCanvas");
    if(!root||!canvas||!latestBookData)return;
    const width=Math.max(1,root.clientWidth),height=Math.max(180,root.clientHeight||280);
    const ratio=Math.min(window.devicePixelRatio||1,1.25);
    const pixelWidth=Math.round(width*ratio),pixelHeight=Math.round(height*ratio);
    if(canvas.width!==pixelWidth||canvas.height!==pixelHeight){canvas.width=pixelWidth;canvas.height=pixelHeight;}
    canvas.style.width=width+"px";canvas.style.height=height+"px";
    const ctx=canvas.getContext("2d");if(!ctx)return;
    ctx.setTransform(ratio,0,0,ratio,0,0);
    ctx.fillStyle="#090d0b";ctx.fillRect(0,0,width,height);
    const priceRows=bookHistory.flatMap(snap=>[...snap.bids,...snap.asks].map(row=>row[0])).filter(Number.isFinite);
    if(!priceRows.length)return;
    let minPrice=Math.min(...priceRows),maxPrice=Math.max(...priceRows);
    if(maxPrice<=minPrice){minPrice-=0.5;maxPrice+=0.5;}
    const quantityRows=bookHistory.flatMap(snap=>[...snap.bids,...snap.asks].map(row=>row[1])).filter(v=>Number.isFinite(v)&&v>0);
    const maxQty=Math.max(1,...quantityRows);
    const leftPad=2,topPad=20,bottomPad=12,plotHeight=height-topPad-bottomPad;
    const colWidth=(width-leftPad)/Math.max(1,bookHistory.length);
    const rowHeight=Math.max(2,plotHeight/64);
    bookHistory.forEach((snap,index)=>{
      const x=leftPad+index*colWidth;
      const drawSide=(rows,isBid)=>{
        rows.forEach(([price,quantity])=>{
          if(!Number.isFinite(price)||!Number.isFinite(quantity)||quantity<=0)return;
          const y=topPad+(maxPrice-price)/(maxPrice-minPrice)*plotHeight;
          const intensity=Math.min(0.88,0.10+Math.sqrt(quantity/maxQty)*0.78);
          ctx.fillStyle=isBid?"rgba(37,190,130,"+intensity+")":"rgba(230,82,94,"+intensity+")";
          ctx.fillRect(x,y-rowHeight/2,Math.max(1,colWidth+0.5),rowHeight);
        });
      };
      drawSide(snap.bids,true);drawSide(snap.asks,false);
    });
    const bestBid=latestBookData.bids[0]?.[0],bestAsk=latestBookData.asks[0]?.[0];
    if(Number.isFinite(bestBid)&&Number.isFinite(bestAsk)){
      const mid=(bestBid+bestAsk)/2,y=topPad+(maxPrice-mid)/(maxPrice-minPrice)*plotHeight;
      ctx.strokeStyle="rgba(255,255,255,.58)";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();
    }
    ctx.fillStyle="rgba(245,245,245,.78)";ctx.font="10px sans-serif";
    ctx.fillText("ASK LIQUIDITY",8,13);ctx.fillText("BID LIQUIDITY",8,height-3);
    const now=Date.now();
    if(now-lastBookTableAt>=500){
      lastBookTableAt=now;
      const bids=latestBookData.bids,asks=latestBookData.asks;
      const totalBid=bids.reduce((sum,row)=>sum+row[1],0),totalAsk=asks.reduce((sum,row)=>sum+row[1],0);
      const total=totalBid+totalAsk,imbalance=total?(totalBid-totalAsk)/total*100:0;
      $("p7BookImbalance").textContent="Live depth imbalance "+imbalance.toFixed(1)+"%";
      $("p7BookLiveStatus").textContent="LIVE · 100ms Binance depth · "+new Date(latestBookData.receivedAt).toLocaleTimeString();
      $("p7BookLiveStatus").className="p7-live-indicator";
      [["p7Bids",bids],["p7Asks",asks]].forEach(([id,rows])=>{
        const body=$(id);body.replaceChildren();
        rows.slice(0,12).forEach(([price,qty])=>{const tr=node("tr");addCell(tr,fmt(price,priceDigits(latestBookData.symbol)));addCell(tr,fmt(qty,6));body.append(tr);});
      });
      $("p7BookNote").textContent="Rolling 12-second liquidity history from Binance Spot top-20 partial-depth snapshots. Resting orders only; not executed volume or guaranteed liquidity.";
    }
  }
  function scheduleBookReconnect(generation){
    if(bookRetry||document.hidden||generation!==bookGeneration)return;
    const delay=Math.min(30000,1000*Math.pow(2,Math.min(bookReconnectAttempts,5)));
    bookReconnectAttempts=Math.min(bookReconnectAttempts+1,6);
    $("p7BookLiveStatus").textContent="Depth reconnecting in "+Math.ceil(delay/1000)+"s · attempt "+bookReconnectAttempts;
    bookRetry=setTimeout(()=>{bookRetry=null;if(!document.hidden&&generation===bookGeneration)loadBook(true);},delay);
  }
  function loadBook(reconnect=false){
    const symbol=$("p7BookSymbol").value.toLowerCase();
    if(!reconnect)bookReconnectAttempts=0;
    const generation=++bookGeneration;
    clearTimeout(bookRetry);bookRetry=null;
    if(bookWatchdog){clearInterval(bookWatchdog);bookWatchdog=null;}
    if(bookRenderTimer!==null){clearTimeout(bookRenderTimer);bookRenderTimer=null;}
    bookHistory=[];latestBookData=null;lastBookTableAt=0;
    if(bookSocket){bookSocket.onclose=null;bookSocket.close();bookSocket=null;}
    $("p7BookLiveStatus").textContent="Connecting to "+symbol.toUpperCase()+" depth stream…";
    const canvas=$("p7BookmapCanvas");
    if(canvas){const ctx=canvas.getContext("2d");if(ctx)ctx.clearRect(0,0,canvas.width,canvas.height);}
    if(!window.WebSocket||document.hidden)return;
    try{
      bookSocket=new WebSocket("wss://stream.binance.com:9443/ws/"+symbol+"@depth20@100ms");
      bookSocket.onopen=()=>{if(generation===bookGeneration){bookLastMessageAt=Date.now();$("p7BookLiveStatus").textContent="Connected · waiting for depth";}};
      bookSocket.onmessage=event=>{
        if(generation!==bookGeneration)return;
        bookLastMessageAt=Date.now();
        try{const data=JSON.parse(event.data);bookReconnectAttempts=0;renderBookmap(symbol.toUpperCase(),data.bids||[],data.asks||[]);}catch{}
      };
      bookSocket.onerror=()=>{try{bookSocket?.close();}catch{}};
      bookSocket.onclose=()=>{if(generation!==bookGeneration)return;if(bookWatchdog){clearInterval(bookWatchdog);bookWatchdog=null;}bookSocket=null;if(!document.hidden){$("p7BookLiveStatus").textContent="Stream disconnected · reconnecting…";scheduleBookReconnect(generation);}};
      bookWatchdog=setInterval(()=>{if(!document.hidden&&generation===bookGeneration&&bookSocket&&bookSocket.readyState===WebSocket.OPEN&&bookLastMessageAt&&Date.now()-bookLastMessageAt>30000){$("p7BookLiveStatus").textContent="Depth feed stale · reconnecting…";try{bookSocket.close();}catch{}}},10000);
    }catch(error){bookSocket=null;$("p7BookLiveStatus").textContent="Live depth unavailable: "+error.message;scheduleBookReconnect(generation);}
  }
  window.addEventListener("resize",()=>{if(latestBookData)drawBookmap();});
  function renderSignal(data){
    const root=$("p7SignalResult");root.replaceChildren();
    const signal=data.signal;
    const header=node("div",undefined,"p7-signal-heading");
    header.append(node("strong",data.symbol+" · "+(signal?signal.side:"WAIT"),signal?(signal.side==="BUY"?"buy":"sell"):"wait"));
    header.append(node("span","Confluence "+data.confluence_score+"/10 · "+data.status));
    root.append(header);
    root.append(node("p",data.message+" "+data.score_note,"p7-note"));
    if(signal){
      const levels=node("div",undefined,"p7-signal-levels");
      [["Entry",signal.entry],["Stop Loss",signal.stop_loss],["TP1",signal.tp1],["TP2 / TP3",signal.tp2+" / "+signal.tp3]].forEach(([label,value])=>{
        const box=node("div");box.append(node("span",label),node("b",String(value)));levels.append(box);
      });
      root.append(levels);
      root.append(node("p","Confirmations: "+signal.confirmations.join(" · "),"p7-note"));
    }
    const frames=$("p7SignalFrames");frames.replaceChildren();
    Object.entries(data.timeframes||{}).forEach(([tf,item])=>{
      const tr=node("tr");
      [tf,item.bias,fmt(item.close,priceDigits(data.symbol)),fmt(item.rsi,1),fmt(item.adx,1),fmt(item.atr,5)].forEach(x=>addCell(tr,String(x)));
      frames.append(tr);
    });
    lastSignal=signal||null;$("p7SignalTicket").hidden=!signal;
  }
  async function scan(){
    const button=$("p7RunScan");button.disabled=true;button.textContent="Analyzing…";
    try{
      const data=await apiRequest("/api/v1/intelligence/signals/scan",{method:"POST",body:JSON.stringify({
        symbol:$("p7SignalSymbol").value,min_score:Number($("p7SignalThreshold").value)
      })});
      renderSignal(data);
    }catch(error){$("p7SignalResult").replaceChildren(node("p",error.message,"p7-status-error"));}
    finally{button.disabled=false;button.textContent="Scan market";}
  }
  async function loadBook(){
    const symbol=$("p7BookSymbol").value;
    $("p7BookNote").textContent="Loading configured provider order-book snapshot…";
    try{
      const data=await apiRequest("/api/v1/intelligence/market/"+symbol+"/orderbook");
      if(!data.supported){$("p7Bids").replaceChildren();$("p7Asks").replaceChildren();$("p7BookNote").textContent=data.reason;return;}
      [["p7Bids",data.bids],["p7Asks",data.asks]].forEach(([id,rows])=>{
        const body=$(id);body.replaceChildren();
        rows.slice(0,12).forEach(item=>{const tr=node("tr");addCell(tr,fmt(item.price,priceDigits(symbol)));addCell(tr,fmt(item.quantity,6));body.append(tr);});
      });
      $("p7BookImbalance").textContent="Bid/ask imbalance "+(data.imbalance*100).toFixed(1)+"%";
      $("p7BookNote").textContent=data.note+" Snapshot: "+new Date(data.timestamp).toLocaleTimeString();
    }catch(error){$("p7BookNote").textContent="Order book unavailable: "+error.message;}
  }
  async function loadNews(){
    $("p7NewsStatus").textContent="Loading economic calendar…";
    const body=$("p7NewsRows");body.replaceChildren();
    try{
      const data=await apiRequest("/api/v1/intelligence/news?days="+$("p7NewsDays").value);
      $("p7NewsStatus").textContent=data.note;
      if(!data.configured||!data.events?.length){
        const tr=node("tr");const td=node("td",data.configured?"No events returned for this date range.":"Add FINNHUB_API_KEY to backend/.env and restart QUANTNEX to enable the economic calendar.","empty-row");td.colSpan=7;tr.append(td);body.append(tr);return;
      }
      data.events.forEach(event=>{
        const tr=node("tr");
        const rawTime=event.time||event.date||"—";
        const stamp=typeof rawTime==="number"||/^\d{10,13}$/.test(String(rawTime))?new Date(Number(rawTime)*(String(rawTime).length===13?1:1000)).toLocaleString():String(rawTime);
        [stamp,event.country,event.event,event.impact,event.actual,event.estimate,event.prev].forEach(v=>addCell(tr,v==null?"—":String(v)));
        body.append(tr);
      });
    }catch(error){$("p7NewsStatus").textContent="Calendar unavailable: "+error.message;}
  }
  async function loadPaper(){
    try{
      const [summary,trades]=await Promise.all([
        apiRequest("/api/v1/paper-trading/summary"),
        apiRequest("/api/v1/paper-trading/trades?limit=100")
      ]);
      const kpis=$("p7PaperSummary");kpis.replaceChildren();
      [["Open trades",summary.open_trades],["Closed trades",summary.closed_trades],
       ["Win rate",summary.win_rate==null?"—":fmt(summary.win_rate,1)+"%"],
       ["Realized P&L","$"+fmt(summary.realized_pnl,2)]].forEach(([label,value])=>{
        const card=node("article");card.append(node("span",label),node("strong",String(value)));kpis.append(card);
      });
      const body=$("p7PaperRows");body.replaceChildren();
      if(!trades.length){const tr=node("tr");const td=node("td","No paper trades yet.","empty-row");td.colSpan=9;tr.append(td);body.append(tr);}
      trades.forEach(item=>{
        const tr=node("tr");
        [new Date(item.created_at).toLocaleString(),item.symbol,item.side,fmt(item.quantity,6),
         fmt(item.entry_price,priceDigits(item.symbol)),fmt(item.stop_loss,priceDigits(item.symbol)),
         fmt(item.take_profit,priceDigits(item.symbol)),item.status].forEach(v=>addCell(tr,String(v)));
        const action=node("td");
        if(item.status==="OPEN"){
          const button=node("button","Close","p7-action-btn");
          button.addEventListener("click",async()=>{
            button.disabled=true;
            try{await apiRequest("/api/v1/paper-trading/trades/"+item.id+"/close",{method:"POST"});setMessage("p7PaperStatus","Paper position closed using a fresh provider quote.");await refreshAnalytics();}
            catch(error){setMessage("p7PaperStatus",error.message,true);button.disabled=false;}
          });
          action.append(button);
        }else addCell(tr,"");
        tr.append(action);body.append(tr);
      });
    }catch(error){setMessage("p7PaperStatus","Paper ledger unavailable: "+error.message,true);}
  }
  async function loadPerformance(){
    try{
      const data=await apiRequest("/api/v1/intelligence/performance");
      const root=$("p7PerformanceKpis");root.replaceChildren();
      [["Closed trades",data.total_trades],["Win rate",data.win_rate==null?"—":fmt(data.win_rate,1)+"%"],
       ["Profit factor",data.profit_factor==null?"—":fmt(data.profit_factor,2)],
       ["Net P&L","$"+fmt(data.net_pnl,2)]].forEach(([label,value])=>{
        const card=node("article");card.append(node("span",label),node("strong",String(value)));root.append(card);
      });
      $("p7PerformanceNote").textContent="Wins "+data.wins+" · Losses "+data.losses+" · Breakeven "+data.breakeven+
        " · Gross profit $"+fmt(data.gross_profit,2)+" · Gross loss $"+fmt(data.gross_loss,2)+". "+data.note;
    }catch(error){$("p7PerformanceNote").textContent="Performance data unavailable: "+error.message;}
  }
  async function refreshAnalytics(){
    const tasks=[];
    if(isWorkspaceViewActive("paper-trading"))tasks.push(loadPaper());
    if(isWorkspaceViewActive("performance-lab"))tasks.push(loadPerformance());
    await Promise.all(tasks);
  }
  window.addEventListener("quantnex:workspace-event",event=>{if(event.detail?.type==="paper_trade.changed")refreshAnalytics();});
  window.addEventListener("quantnex:workspace-resync",refreshAnalytics);
  async function openPaper(){
    const button=$("p7OpenPaper");button.disabled=true;button.textContent="Opening…";
    try{
      const result=await apiRequest("/api/v1/paper-trading/trades",{method:"POST",body:JSON.stringify({
        symbol:$("p7PaperSymbol").value,side:$("p7PaperSide").value,
        quantity:Number($("p7PaperQty").value),stop_loss:Number($("p7PaperSL").value),
        take_profit:Number($("p7PaperTP").value)
      })});
      setMessage("p7PaperStatus","Paper trade #"+result.id+" opened at "+fmt(result.entry_price,priceDigits(result.symbol))+". No broker order was placed.");
      await refreshAnalytics();
    }catch(error){setMessage("p7PaperStatus",error.message,true);}
    finally{button.disabled=false;button.textContent="Open paper trade";}
  }
  async function calculateRisk(){
    const button=$("p7CalculateRisk");button.disabled=true;
    try{
      const data=await apiRequest("/api/v1/intelligence/risk/calculate",{method:"POST",body:JSON.stringify({
        equity:Number($("p7RiskEquity").value),risk_percent:Number($("p7RiskPercent").value),
        entry:Number($("p7RiskEntry").value),stop_loss:Number($("p7RiskStop").value)
      })});
      const root=$("p7RiskResult");root.replaceChildren();
      root.append(node("strong","Maximum planned loss: $"+fmt(data.risk_amount,2)));
      root.append(node("p","Estimated position size: "+fmt(data.estimated_units,6)+" base units · Price distance: "+fmt(data.price_distance,6),"p7-note"));
      root.append(node("p",data.note,"p7-note"));
    }catch(error){$("p7RiskResult").replaceChildren(node("p",error.message,"p7-status-error"));}
    finally{button.disabled=false;}
  }
  $("p7RefreshMarkets").addEventListener("click",loadMarkets);
  $("p7RunScan").addEventListener("click",scan);
  $("p7LoadBook").addEventListener("click",loadBook);
  $("p7LoadNews").addEventListener("click",loadNews);
  $("p7OpenPaper").addEventListener("click",openPaper);
  $("p7RefreshPaper").addEventListener("click",refreshAnalytics);
  $("p7CalculateRisk").addEventListener("click",calculateRisk);
  $("p7UseSignal").addEventListener("click",()=>{
    if(!lastSignal)return;
    $("p7PaperSymbol").value=lastSignal.symbol;$("p7PaperSide").value=lastSignal.side;
    $("p7PaperSL").value=lastSignal.stop_loss;$("p7PaperTP").value=lastSignal.tp1;
    location.hash="#paper-trading";
    $("p7PaperQty").focus();
  });
  $("p7BookSymbol").addEventListener("change",loadBook);
  function stopBookFeed(){
    clearTimeout(bookRetry);bookRetry=null;
    if(bookWatchdog){clearInterval(bookWatchdog);bookWatchdog=null;}
    if(bookRenderTimer!==null){clearTimeout(bookRenderTimer);bookRenderTimer=null;}
    bookGeneration++;
    if(bookSocket){bookSocket.onclose=null;bookSocket.close();bookSocket=null;}
  }
  function syncWorkspaceView(){
    if(isWorkspaceViewActive("market-intelligence")){loadMarkets();connectCryptoTicker();}
    else stopCryptoTicker();
    if(isWorkspaceViewActive("orderflow-liquidity"))loadBook();
    else stopBookFeed();
    if(isWorkspaceViewActive("paper-trading"))refreshAnalytics();
    if(isWorkspaceViewActive("performance-lab"))loadPerformance();
    if(isWorkspaceViewActive("news-intelligence"))loadNews();
  }
  window.addEventListener("quantnex:view-changed",syncWorkspaceView);
  document.addEventListener("visibilitychange",()=>{
    if(document.hidden){stopCryptoTicker();stopBookFeed();}
    else syncWorkspaceView();
  });
  // Keep network work scoped to the visible workspace. Hidden panels stay idle.
  setInterval(()=>{if(isWorkspaceViewActive("market-intelligence"))loadMarkets();},60000);
  setInterval(()=>{if(isWorkspaceViewActive("paper-trading"))loadPaper();},20000);
  setInterval(()=>{if(isWorkspaceViewActive("performance-lab"))loadPerformance();},30000);
  setInterval(()=>{if(isWorkspaceViewActive("news-intelligence"))loadNews();},900000);
})();


// Phase 08 — Strategy Laboratory. All evaluations remain research / paper-only.
(function initPhase08(){
  if(!$("p8Backtest"))return;
  const fmt=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
  let replay=[],cursor=0,replayTimer=null;
  const config=()=>({name:"EMA Trend Cross",fast_ema:Number($("p8Fast").value),slow_ema:Number($("p8Slow").value),risk_reward:Number($("p8RR").value)});
  const market=()=>({symbol:$("p8Symbol").value,timeframe:$("p8Timeframe").value});
  const status=(message,error=false)=>{const n=$("p8Status");n.textContent=message;n.className=error?"p7-note p7-status-error":"p7-note p7-status-ok";};
  const renderKpis=(data)=>{const root=$("p8Kpis");root.replaceChildren();
    [["Backtest trades",data.trade_count],["Win rate",data.win_rate==null?"—":fmt(data.win_rate,1)+"%"],
     ["Profit factor",data.profit_factor==null?"—":data.profit_factor==="infinite"?"∞":fmt(data.profit_factor,2)],
     ["Net P&L",fmt(data.net_pnl,5)]].forEach(([a,b])=>{const card=el("article");card.append(el("span",a),el("strong",b));root.append(card);});
  };
  const runBacktest=async()=>{
    const b=$("p8Backtest");b.disabled=true;b.textContent="Testing…";
    try{
      const data=await apiRequest("/api/v1/strategy-lab/backtest",{method:"POST",body:JSON.stringify({...market(),strategy:config()})});
      renderKpis(data);const root=$("p8Result");root.replaceChildren();
      root.append(el("p",data.strategy.name+" · EMA "+data.strategy.fast_ema+"/"+data.strategy.slow_ema+" · "+data.strategy.risk_reward+"R","p8-result-title"));
      root.append(el("p","Historical candles: "+data.candle_count+" · Wins: "+data.wins+" · Losses: "+data.losses+" · Maximum drawdown: "+fmt(data.max_drawdown,5),"p7-note"));
      root.append(el("p",data.limitations,"p7-note"));
      const table=document.createElement("table"),head=document.createElement("tr");
      ["Side","Entry","Stop","Target","Exit","P&L","Reason"].forEach(x=>head.append(el("th",x)));
      const thead=document.createElement("thead");thead.append(head);table.append(thead);
      const body=document.createElement("tbody");
      data.trades.slice(-20).reverse().forEach(t=>{const tr=document.createElement("tr");
        [t.side,fmt(t.entry,5),fmt(t.stop_loss,5),fmt(t.take_profit,5),fmt(t.exit,5),fmt(t.pnl,5),t.exit_reason].forEach(x=>tr.append(el("td",x)));body.append(tr);});
      table.append(body);const wrap=el("div",undefined,"p7-table-wrap");wrap.append(table);root.append(wrap);
      status("Backtest saved to local Strategy Research history. This is an in-sample simulation, not a future performance promise.");
      await loadResearch();
    }catch(e){status("Backtest failed: "+e.message,true);}
    finally{b.disabled=false;b.textContent="Run backtest";}
  };
  const runOptimizer=async()=>{
    const b=$("p8Optimize");b.disabled=true;b.textContent="Testing combinations…";
    try{
      const data=await apiRequest("/api/v1/strategy-lab/optimize",{method:"POST",body:JSON.stringify(market())});
      const root=$("p8Result");root.replaceChildren(el("p",data.tested+" parameter combinations tested","p8-result-title"));
      const table=document.createElement("table"),head=document.createElement("tr");
      ["Rank","Fast / Slow EMA","R:R","Trades","Win rate","Net P&L","Profit factor"].forEach(x=>head.append(el("th",x)));
      const thead=document.createElement("thead");thead.append(head);table.append(thead);
      const body=document.createElement("tbody");
      data.ranked.forEach((x,i)=>{const tr=document.createElement("tr");
        [i+1,x.strategy.fast_ema+" / "+x.strategy.slow_ema,x.strategy.risk_reward,x.trade_count,x.win_rate==null?"—":x.win_rate+"%",fmt(x.net_pnl,5),x.profit_factor??"—"].forEach(v=>tr.append(el("td",v)));body.append(tr);});
      table.append(body);const wrap=el("div",undefined,"p7-table-wrap");wrap.append(table);root.append(wrap);root.append(el("p",data.warning,"p7-note"));
      status("Optimizer run saved. Select candidate settings and validate on unseen candles before forward observation.");await loadResearch();
    }catch(e){status("Optimization failed: "+e.message,true);}
    finally{b.disabled=false;b.textContent="Optimize settings";}
  };
  const runForward=async()=>{
    const b=$("p8Forward");b.disabled=true;b.textContent="Evaluating…";
    try{const data=await apiRequest("/api/v1/strategy-lab/forward/evaluate",{method:"POST",body:JSON.stringify({...market(),strategy:config()})});
      status("Forward observation: "+data.symbol+" "+data.timeframe+" · "+data.side+" at "+fmt(data.price,5)+". "+data.note);
      await loadResearch();
    }catch(e){status("Forward observation failed: "+e.message,true);}
    finally{b.disabled=false;b.textContent="Forward evaluate";}
  };
  const renderReplay=()=>{
    const candle=replay[cursor];if(!candle)return;
    $("p8ReplayIndex").textContent=(cursor+1)+" / "+replay.length+" candles";
    $("p8ReplayCandle").textContent="O "+fmt(candle.open,5)+" · H "+fmt(candle.high,5)+" · L "+fmt(candle.low,5)+" · C "+fmt(candle.close,5)+" · "+candle.time;
    $("p8ReplayPrev").disabled=cursor<=0;$("p8ReplayNext").disabled=cursor>=replay.length-1;$("p8ReplayPlay").disabled=!replay.length;
    const body=$("p8ReplayRows");body.replaceChildren();
    replay.slice(Math.max(0,cursor-4),cursor+1).reverse().forEach(x=>{const tr=document.createElement("tr");
      [x.time,fmt(x.open,5),fmt(x.high,5),fmt(x.low,5),fmt(x.close,5)].forEach(v=>tr.append(el("td",v)));body.append(tr);});
  };
  const loadReplay=async()=>{
    const b=$("p8ReplayLoad");b.disabled=true;
    try{const data=await apiRequest("/api/v1/strategy-lab/replay?"+new URLSearchParams(market()));
      replay=data.candles;cursor=0;renderReplay();status("Market replay loaded: "+data.count+" "+data.timeframe+" candles from "+data.symbol+".");}
    catch(e){status("Replay unavailable: "+e.message,true);}
    finally{b.disabled=false;}
  };
  const loadResearch=async()=>{
    try{const data=await apiRequest("/api/v1/strategy-lab/research"),body=$("p8ResearchRows");body.replaceChildren();
      $("p8ResearchSummary").textContent="Closed paper trades: "+data.paper_trades.closed+" · Wins: "+data.paper_trades.wins+
        " · Losses: "+data.paper_trades.losses+" · Win rate: "+(data.paper_trades.win_rate==null?"—":data.paper_trades.win_rate+"%")+
        " · Net P&L: "+fmt(data.paper_trades.net_pnl,2)+". "+data.guidance;
      if(!data.runs.length){body.append(el("tr"));body.lastChild.append(el("td","No research runs yet."));body.lastChild.firstChild.colSpan=5;return;}
      data.runs.forEach(x=>{const tr=el("tr");const result=x.result||{};
        [x.type,x.symbol,x.timeframe,new Date(x.created_at).toLocaleString(),
         x.type==="BACKTEST"?"Trades "+(result.trade_count??"—")+" · Win "+(result.win_rate??"—")+"%":
         x.type==="OPTIMIZER"?(result.tested??"—")+" combinations":(result.side??"—")+" @ "+fmt(result.price,5)
        ].forEach(v=>tr.append(el("td",v)));body.append(tr);});
    }catch(e){$("p8ResearchSummary").textContent="Research history unavailable: "+e.message;}
  };
  $("p8Backtest").addEventListener("click",runBacktest);
  $("p8Optimize").addEventListener("click",runOptimizer);
  $("p8Forward").addEventListener("click",runForward);
  $("p8ReplayLoad").addEventListener("click",loadReplay);
  $("p8ReplayPrev").addEventListener("click",()=>{cursor=Math.max(0,cursor-1);renderReplay();});
  $("p8ReplayPlay").addEventListener("click",()=>{if(replayTimer){clearInterval(replayTimer);replayTimer=null;$("p8ReplayPlay").textContent="Play";return;}if(cursor>=replay.length-1)cursor=0;$("p8ReplayPlay").textContent="Pause";replayTimer=setInterval(()=>{if(cursor>=replay.length-1){clearInterval(replayTimer);replayTimer=null;$("p8ReplayPlay").textContent="Play";return;}cursor++;renderReplay();},700);});
  $("p8ReplayNext").addEventListener("click",()=>{cursor=Math.min(replay.length-1,cursor+1);renderReplay();});
  $("p8ResearchRefresh").addEventListener("click",loadResearch);
  loadResearch();
})();


// Phase 09 — portfolio risk, drawdown guardian and paper-only smart sizing.
(function initPhase09(){
  if(!$("p9Refresh"))return;
  const fmt=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  const val=id=>Number($(id).value);
  const cfg=()=>({equity:val("p9Equity"),daily_loss_limit_percent:val("p9DailyLimit"),
    max_drawdown_percent:val("p9MaxDD"),max_consecutive_losses:val("p9LossStreak")});
  const status=(s,bad=false)=>{const n=$("p9Status");n.textContent=s;n.className=bad?"p7-note p7-status-error":"p7-note p7-status-ok";};
  const render=(root,data)=>{root.replaceChildren();const pre=document.createElement("pre");pre.className="p9-report";pre.textContent=JSON.stringify(data,null,2);root.append(pre);};
  async function refresh(){
    try{
      const data=await apiRequest("/api/v1/risk/portfolio");
      const k=$("p9PortfolioKpis");k.replaceChildren();
      [["Open positions",data.open_positions],["Gross notional estimate","$"+fmt(data.gross_notional_estimate)],
       ["Planned stop risk","$"+fmt(data.planned_stop_risk_estimate)],["Symbols",Object.keys(data.by_symbol_notional||{}).length]
      ].forEach(([a,b])=>{const card=document.createElement("article");card.append(document.createElement("span"),document.createElement("strong"));card.firstChild.textContent=a;card.lastChild.textContent=b;k.append(card);});
      const body=$("p9Positions");body.replaceChildren();
      if(!data.positions.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.className="empty-row";td.textContent="No open paper positions.";tr.append(td);body.append(tr);}
      data.positions.forEach(p=>{const tr=document.createElement("tr");[p.id,p.symbol,p.side,fmt(p.quantity,6),fmt(p.notional_estimate,4),fmt(p.planned_stop_risk_estimate,4)].forEach(v=>{const td=document.createElement("td");td.textContent=v;tr.append(td);});body.append(tr);});
      render($("p9Result"),{by_symbol_notional:data.by_symbol_notional,concentration_percent:data.symbol_concentration_percent,limitations:data.limitations});
      status("Portfolio snapshot refreshed from the local paper ledger.");
    }catch(e){status("Portfolio unavailable: "+e.message,true);}
  }
  async function guardian(){
    try{const data=await apiRequest("/api/v1/risk/guardian",{method:"POST",body:JSON.stringify(cfg())});
      render($("p9Result"),data);status(data.trading_allowed?"Risk Guardian: no configured limit is currently breached.":"Risk Guardian blocked smart paper entries: "+data.triggers.join(", "),!data.trading_allowed);
    }catch(e){status("Guardian failed: "+e.message,true);}
  }
  async function stress(){
    try{const data=await apiRequest("/api/v1/risk/stress",{method:"POST",body:JSON.stringify({})});
      render($("p9Result"),data);status("Stress scenarios calculated using the displayed parallel-shock assumptions.");
    }catch(e){status("Stress test failed: "+e.message,true);}
  }
  async function size(){
    try{const data=await apiRequest("/api/v1/risk/position-size",{method:"POST",body:JSON.stringify({
      equity:val("p9Equity"),risk_percent:val("p9RiskPercent"),entry:val("p9Entry")||0,
      stop_loss:val("p9Stop"),contract_multiplier:val("p9Multiplier")
    })});render($("p9Result"),data);status("Sizing complete. Set entry via live quote by using Smart Paper Open; this preview requires a valid entry.");
    }catch(e){status("Sizing failed: "+e.message,true);}
  }
  async function smartOpen(){
    const b=$("p9SmartOpen");b.disabled=true;
    try{
      const data=await apiRequest("/api/v1/paper-trading/smart-open",{method:"POST",body:JSON.stringify({
        ...cfg(),symbol:$("p9Symbol").value,side:$("p9Side").value,risk_percent:val("p9RiskPercent"),
        stop_loss:val("p9Stop"),take_profit:val("p9Target"),contract_multiplier:val("p9Multiplier")
      })});
      render($("p9Result"),data);status("Risk-checked paper trade #"+data.id+" opened. No broker order was sent.");await refresh();
    }catch(e){status("Smart paper entry rejected: "+e.message,true);}
    finally{b.disabled=false;}
  }
  $("p9Refresh").addEventListener("click",refresh);
  $("p9Guardian").addEventListener("click",guardian);
  $("p9Stress").addEventListener("click",stress);
  $("p9Size").addEventListener("click",size);
  $("p9SmartOpen").addEventListener("click",smartOpen);
  refresh();
})();

 
// Phase 10 — Market Data Reliability dashboard.
(function initPhase10(){
  if(!$("p10ScanMarkets"))return;
  const fmt=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  const el=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;if(cls)n.className=cls;return n;};
  const status=(message,bad=false)=>{const n=$("p10Status");n.textContent=message;n.className=bad?"p7-note p7-status-error":"p7-note p7-status-ok";};
  function renderDetail(data){
    const root=$("p10DetailResult");root.replaceChildren();
    const header=el("div",data.symbol+" · "+data.status,"p10-detail-heading "+(data.trading_safe?"safe":"unsafe"));root.append(header);
    const quote=data.quote||{},candles=data.candles||{};
    const lines=[
      "Quote age: "+fmt(quote.age_seconds)+" sec · limit "+fmt(quote.max_age_seconds)+" sec",
      "Provider timestamp: "+(quote.provider_timestamp||"Unavailable"),
      "Candles checked: "+fmt(candles.count,0)+" · gaps: "+fmt(candles.gap_count,0),
      "Latest candle: "+(candles.latest_candle_timestamp||"Unavailable"),
      "Issues: "+((data.issues||[]).join(", ")||"None"),
      "Warnings: "+((data.warnings||[]).join(", ")||"None")
    ];
    lines.forEach(x=>root.append(el("p",x,"p7-note")));
  }
  async function scan(){
    const button=$("p10ScanMarkets");button.disabled=true;
    status("Checking source timestamps and market availability…");
    try{
      const data=await apiRequest("/api/v1/data-reliability/markets");
      const rows=data.items||[],counts={HEALTHY:0,DEGRADED:0,UNSAFE:0};
      const body=$("p10MarketRows");body.replaceChildren();
      rows.forEach(item=>{
        counts[item.status]=(counts[item.status]||0)+1;
        const tr=document.createElement("tr"),health=item.health||{};
        const age=health.age_seconds;
        [item.symbol,item.provider||"—",item.status,fmt(item.price,5),fmt(age),[...(health.issues||item.issues||[]),...(health.warnings||[])].join(", ")||"None"].forEach((v,i)=>{
          const td=el("td",String(v));if(i===2)td.className=item.status==="HEALTHY"?"p10-health-good":item.status==="DEGRADED"?"p10-health-warn":"p10-health-bad";tr.append(td);
        });
        body.append(tr);
      });
      const k=$("p10Kpis");k.replaceChildren();
      [["Healthy",counts.HEALTHY],["Degraded",counts.DEGRADED],["Unsafe",counts.UNSAFE],["Safe to paper-enter",rows.every(x=>x.trading_safe)?"YES":"NO"]].forEach(([label,value])=>{
        const card=el("article");card.append(el("span",label),el("strong",String(value)));k.append(card);
      });
      status("Scan complete · "+counts.HEALTHY+" healthy · "+counts.DEGRADED+" degraded · "+counts.UNSAFE+" unsafe. "+(data.trading_safe?"All returned feeds passed quote checks.":"At least one feed is unavailable or unsafe; affected symbols cannot open new paper positions."));
    }catch(error){status("Reliability scan failed: "+error.message,true);}
    finally{button.disabled=false;}
  }
  async function detail(){
    const button=$("p10CheckCandles");button.disabled=true;
    try{
      const symbol=$("p10Symbol").value,tf=$("p10Timeframe").value;
      const data=await apiRequest("/api/v1/data-reliability/market/"+encodeURIComponent(symbol)+"?timeframe="+encodeURIComponent(tf));
      renderDetail(data);status(symbol+" candle integrity check: "+data.status,data.status==="UNSAFE");
    }catch(error){
      const root=$("p10DetailResult");root.replaceChildren(el("p","Validation unavailable: "+error.message,"p7-status-error"));
      status("Detailed market check failed. Paper entry remains blocked when provider timestamps cannot be verified.",true);
    }finally{button.disabled=false;}
  }
  $("p10ScanMarkets").addEventListener("click",scan);
  $("p10CheckCandles").addEventListener("click",detail);
  scan();
  // Low-frequency background health refresh; skips hidden tabs and overlapping requests.
  setInterval(()=>{if(!document.hidden&&!$("p10ScanMarkets").disabled)scan();},300000);
})();

(function initPhase11(){
  if(!$("p11Refresh"))return;
  const fmt=(v,d=2)=>v==null||!Number.isFinite(Number(v))?"—":Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
  const node=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=String(value);if(cls)n.className=cls;return n;};
  const status=(message,bad=false)=>{const n=$("p11Status");n.textContent=message;n.className=bad?"p7-note p7-status-error":"p7-note";};
  const svgNS="http://www.w3.org/2000/svg";
  function svg(tag,attrs={}){const n=document.createElementNS(svgNS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));return n;}
  function empty(root,message){root.replaceChildren(node("p",message,"p7-note"));}
  function renderEquity(rows){
    const root=$("p11EquityChart");root.replaceChildren();
    if(!rows.length){empty(root,"No closed paper trades in this period.");return;}
    const values=[0,...rows.map(x=>Number(x.cumulative_pnl))],min=Math.min(...values),max=Math.max(...values);
    const range=Math.max(max-min,1),width=700,height=230,pad=24;
    const points=values.map((v,i)=>(pad+i*(width-2*pad)/Math.max(values.length-1,1))+","+(height-pad-(v-min)/range*(height-2*pad))).join(" ");
    const chart=svg("svg",{viewBox:"0 0 "+width+" "+height,role:"img","aria-label":"Cumulative realized paper trade profit and loss chart"});
    const zeroY=height-pad-(0-min)/range*(height-2*pad);
    chart.append(svg("line",{x1:pad,y1:zeroY,x2:width-pad,y2:zeroY,stroke:"#666","stroke-dasharray":"5 5"}));
    chart.append(svg("polyline",{points:points,fill:"none",stroke:"#e5e5e5","stroke-width":3,"stroke-linecap":"round","stroke-linejoin":"round"}));
    values.forEach((v,i)=>{if(i===0)return;const x=pad+i*(width-2*pad)/Math.max(values.length-1,1),y=height-pad-(v-min)/range*(height-2*pad);const dot=svg("circle",{cx:x,cy:y,r:3,fill:"#fff"});const title=svg("title");title.textContent="Trade "+i+": "+fmt(v);dot.append(title);chart.append(dot);});
    root.append(chart,node("div","Start $0.00 · End $"+fmt(values[values.length-1])+" · Peak $"+fmt(max),"p11-chart-caption"));
  }
  function renderDaily(rows){
    const root=$("p11DailyChart");root.replaceChildren();
    if(!rows.length){empty(root,"No daily results yet.");return;}
    const width=700,height=230,pad=25,values=rows.map(x=>Number(x.pnl)),limit=Math.max(...values.map(Math.abs),1),zero=height/2;
    const chart=svg("svg",{viewBox:"0 0 "+width+" "+height,role:"img","aria-label":"Daily realized paper profit and loss bar chart"});
    chart.append(svg("line",{x1:pad,y1:zero,x2:width-pad,y2:zero,stroke:"#777"}));
    const step=(width-2*pad)/rows.length,bar=Math.max(3,Math.min(24,step*.55));
    rows.forEach((item,i)=>{const v=Number(item.pnl),h=Math.abs(v)/limit*(height/2-pad),x=pad+i*step+(step-bar)/2,y=v>=0?zero-h:zero;const rect=svg("rect",{x:x,y:y,width:bar,height:h,rx:2,fill:v>=0?"#cfcfcf":"#777"});const title=svg("title");title.textContent=item.date+": $"+fmt(v);rect.append(title);chart.append(rect);});
    root.append(chart,node("div",rows.length+" trading day(s) · positive and negative daily totals","p11-chart-caption"));
  }
  function renderSymbols(data){
    const body=$("p11SymbolRows");body.replaceChildren();
    const entries=Object.entries(data||{});
    if(!entries.length){const tr=node("tr"),td=node("td","No closed trades by market.","empty-row");td.colSpan=5;tr.append(td);body.append(tr);return;}
    entries.forEach(([symbol,row])=>{const tr=node("tr");[symbol,row.trades,row.win_rate==null?"—":fmt(row.win_rate,1)+"%","$"+fmt(row.net_pnl),row.profit_factor==="infinite"?"∞":fmt(row.profit_factor,2)].forEach(v=>tr.append(node("td",v)));body.append(tr);});
  }
  function renderConsistency(data){
    const root=$("p11Consistency");root.replaceChildren();
    const items=[["Largest win",data.largest_win==null?"—":"$"+fmt(data.largest_win)],["Largest loss",data.largest_loss==null?"—":"$"+fmt(data.largest_loss)],["Maximum win streak",data.max_consecutive_wins],["Maximum loss streak",data.max_consecutive_losses],["R-multiple sample",data.r_multiple_sample],["Best trade",data.best_trade?data.best_trade.symbol+" · $"+fmt(data.best_trade.pnl):"—"],["Worst trade",data.worst_trade?data.worst_trade.symbol+" · $"+fmt(data.worst_trade.pnl):"—"]];
    items.forEach(([label,value])=>{const row=node("div",undefined,"p11-stat-row");row.append(node("span",label),node("strong",String(value)));root.append(row);});
  }
  async function refresh(){
    const button=$("p11Refresh");button.disabled=true;
    try{
      const period=Number($("p11Period").value);
      const data=await apiRequest("/api/v1/performance/advanced?period_days="+period);
      const root=$("p11ExtraKpis");root.replaceChildren();
      [["Expectancy / trade",data.expectancy_per_trade==null?"—":"$"+fmt(data.expectancy_per_trade)],["Average R (estimate)",data.average_r_multiple==null?"—":fmt(data.average_r_multiple,3)+"R"],["Max drawdown","$"+fmt(data.max_drawdown_amount)],["Average hold",data.average_holding_minutes==null?"—":fmt(data.average_holding_minutes,1)+" min"]].forEach(([label,value])=>{const card=node("article");card.append(node("span",label),node("strong",String(value)));root.append(card);});
      renderEquity(data.equity_curve||[]);renderDaily(data.daily_pnl||[]);renderSymbols(data.by_symbol||{});renderConsistency(data);
      $("p11Methodology").textContent=data.total_trades+" closed paper trades · "+data.wins+" wins · "+data.losses+" losses · "+data.breakeven+" breakeven. "+(data.methodology?.r_multiple||"")+" "+(data.methodology?.drawdown||"")+" "+(data.methodology?.limitations||"");
      status("Advanced analytics refreshed · "+(period===0?"all history":"last "+period+" days")+".");
    }catch(error){status("Advanced analytics unavailable: "+error.message,true);}
    finally{button.disabled=false;}
  }
  $("p11Refresh").addEventListener("click",refresh);
  $("p11Period").addEventListener("change",refresh);
  refresh();
})();


// One-second local CPU/RAM telemetry. Poll only while the health panel is visible.
(function initLiveSystemMeters(){
  const panel=document.querySelector(".system-security-panel");
  if(!panel||!$("systemCpu"))return;
  let busy=false,panelVisible=false;
  const update=async()=>{
    if(busy||document.hidden||!panelVisible)return;
    busy=true;
    try{
      const data=await apiRequest("/api/v1/system/metrics");
      const cpu=Math.max(0,Math.min(100,Number(data.cpu_percent)||0));
      const mem=Math.max(0,Math.min(100,Number(data.memory_percent)||0));
      $("systemCpu").textContent=cpu.toFixed(0)+"%";
      $("systemMemory").textContent=mem.toFixed(0)+"%";
      if($("systemCpuBar"))$("systemCpuBar").style.width=cpu+"%";
      if($("systemMemoryBar"))$("systemMemoryBar").style.width=mem+"%";
      if($("systemCpuMeta"))$("systemCpuMeta").textContent=cpu.toFixed(1)+"%";
      if($("systemMemoryMeta"))$("systemMemoryMeta").textContent=(data.memory_used_bytes/1073741824).toFixed(1)+" / "+(data.memory_total_bytes/1073741824).toFixed(1)+" GB";
    }catch(error){if($("systemHealthStatus"))$("systemHealthStatus").textContent="Live telemetry unavailable: "+error.message;}
    finally{busy=false;}
  };
  if("IntersectionObserver" in window){
    const observer=new IntersectionObserver(entries=>{
      panelVisible=entries.some(entry=>entry.isIntersecting);
      if(panelVisible)update();
    },{threshold:0.05});
    observer.observe(panel);
  }else panelVisible=true;
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&panelVisible)update();});
  update();window.setInterval(update,1000);
})();


/* Finnhub economic calendar workspace. API credentials stay on the local backend. */
(function initFinnhubEconomicCalendar(){
  const $id=id=>document.getElementById(id);
  const rows=$id("calendarRows"),status=$id("calendarStatus"),panel=$id("economic-calendar")?.nextElementSibling;
  if(!rows||!status||!panel)return;
  let events=[],busy=false,loaded=false,visible=false,lastLoadedAt=null;
  const currencyByCountry={US:"USD","UNITED STATES":"USD",EU:"EUR",EMU:"EUR",GB:"GBP",UK:"GBP","UNITED KINGDOM":"GBP",JP:"JPY",JAPAN:"JPY",AU:"AUD",AUSTRALIA:"AUD",CA:"CAD",CANADA:"CAD",NZ:"NZD",CH:"CHF",SW:"CHF",CN:"CNY",CHINA:"CNY",IN:"INR",SG:"SGD"};
  const make=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
  const cell=(tr,value)=>tr.append(make("td",value==null||value===""?"—":String(value)));
  const eventCurrency=e=>String(e.currency||currencyByCountry[String(e.country||"").trim().toUpperCase()]||"OTHER").toUpperCase();
  const impactLevel=e=>{const v=String(e.impact??"").toLowerCase();if(v.includes("high")||v==="3")return"high";if(v.includes("medium")||v==="2")return"medium";if(v.includes("low")||v==="1")return"low";return"unknown";};
  const eventDate=e=>{const raw=e.time||e.date||"";if(typeof raw==="number"||/^\d{10,13}$/.test(String(raw)))return new Date(Number(raw)*(String(raw).length===13?1:1000));const value=String(raw).trim();if(/^\d{4}-\d{2}-\d{2}$/.test(value))return new Date(value+"T00:00:00Z");if(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/.test(value))return new Date(value.replace(" ","T")+"Z");return new Date(value);};
  const formatTime=e=>{const raw=e.time||e.date||"";const date=eventDate(e);if(!Number.isFinite(date.getTime()))return String(raw||"—");const dateOnly=/^\d{4}-\d{2}-\d{2}$/.test(String(raw));return new Intl.DateTimeFormat("en-LK",{timeZone:"Asia/Colombo",day:"2-digit",month:"short",year:"numeric",...(dateOnly?{}:{hour:"2-digit",minute:"2-digit",hour12:true})}).format(date);};
  function render(){
    const currency=$id("calendarCurrency").value,impact=$id("calendarImpact").value,query=$id("calendarSearch").value.trim().toLowerCase();
    const filtered=events.filter(e=>(currency==="ALL"||(currency==="OTHER"?eventCurrency(e)==="OTHER":eventCurrency(e)===currency))&&(impact==="ALL"||impactLevel(e)===impact)&&(!query||[e.event,e.country,eventCurrency(e)].some(v=>String(v||"").toLowerCase().includes(query))));
    const high=events.filter(e=>impactLevel(e)==="high").length;
    const currencies=new Set(events.map(eventCurrency).filter(x=>x!=="OTHER"));
    const kpis=$id("calendarKpis");kpis.replaceChildren();
    [["Total events",events.length],["High impact",high],["Currencies",currencies.size]].forEach(([label,value])=>{const card=make("article");card.append(make("span",label),make("strong",String(value)));kpis.append(card);});
    status.textContent="Finnhub · "+filtered.length+" shown / "+events.length+" events · Times: Sri Lanka (UTC+5:30) · Updated "+(lastLoadedAt?lastLoadedAt.toLocaleTimeString("en-LK"):"—")+".";
    rows.replaceChildren();
    if(!filtered.length){const tr=make("tr"),td=make("td",events.length?"No events match the selected filters.":"No events returned by Finnhub for this date range.","empty-row");td.colSpan=7;tr.append(td);rows.append(tr);return;}
    filtered.sort((a,b)=>eventDate(a)-eventDate(b));
    filtered.forEach(e=>{
      const tr=make("tr"),when=cell(tr,formatTime(e));
      cell(tr,eventCurrency(e)==="OTHER"?String(e.country||"—"):eventCurrency(e));
      cell(tr,e.event);
      const impactCell=make("td"),level=impactLevel(e),badge=make("span",level==="unknown"?"N/A":level.toUpperCase(),"calendar-impact impact-"+level);impactCell.append(badge);tr.append(impactCell);
      cell(tr,e.actual);cell(tr,e.estimate);cell(tr,e.prev);
      if(level==="high")tr.classList.add("calendar-high-row");
      rows.append(tr);
    });
  }
  async function refresh(){
    if(busy)return;busy=true;const button=$id("calendarRefresh");button.disabled=true;status.textContent="Fetching Finnhub economic events…";
    const sharedBase=String(window.QUANTNEX_SHARED_NEWS_API_URL||"").trim().replace(/\/+$/,"");
    try{
      let data;
      if(sharedBase){
        const response=await fetch(sharedBase+"/api/economic-calendar?days="+encodeURIComponent($id("calendarDays").value),{headers:{"Accept":"application/json"},cache:"no-store"});
        data=await response.json().catch(()=>null);
        if(!response.ok)throw new Error(data?.detail||("Shared news service returned "+response.status+"."));
      }else{
        data=await apiRequest("/api/v1/intelligence/news?days="+encodeURIComponent($id("calendarDays").value));
      }
      if(!data?.configured){events=[];rows.replaceChildren();const tr=make("tr"),td=make("td",data?.note||"Finnhub news service is not configured yet. See docs/SHARED-NEWS-SERVICE.md for setup.","empty-row");td.colSpan=7;tr.append(td);rows.append(tr);$id("calendarKpis").replaceChildren();status.textContent=data?.note||"Finnhub API key is not configured.";return;}
      events=Array.isArray(data.events)?data.events:[];lastLoadedAt=new Date();render();
      if(sharedBase)status.textContent="Shared Finnhub feed · "+events.length+" events · Times: Sri Lanka (UTC+5:30) · Updated "+lastLoadedAt.toLocaleTimeString("en-LK")+".";

    }catch(error){status.textContent="Calendar unavailable: "+error.message;rows.replaceChildren();const tr=make("tr"),td=make("td",sharedBase?"Could not load the shared Finnhub feed. Check the shared service URL, deployment status and provider quota.":"Could not load Finnhub events. Check your local API key, internet connection and provider quota.","empty-row");td.colSpan=7;tr.append(td);rows.append(tr);}
    finally{busy=false;button.disabled=false;}
  }
  $id("calendarRefresh").addEventListener("click",refresh);
  $id("calendarDays").addEventListener("change",refresh);
  ["calendarCurrency","calendarImpact"].forEach(id=>$id(id).addEventListener("change",render));
  $id("calendarSearch").addEventListener("input",render);
  const observer=("IntersectionObserver" in window)?new IntersectionObserver(entries=>{visible=entries.some(x=>x.isIntersecting);if(visible&&!loaded){loaded=true;refresh();}},{threshold:.08}):null;
  if(observer)observer.observe(panel);else{visible=true;loaded=true;refresh();}
  window.setInterval(()=>{if(visible&&!document.hidden)refresh();},15*60*1000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden&&visible&&loaded&&lastLoadedAt&&Date.now()-lastLoadedAt.getTime()>15*60*1000)refresh();});
})();

// Smooth workspace zoom: Ctrl + mouse wheel (kept local to this browser).
(function initQuantnexSmoothZoom(){
  const key="quantnex.uiZoom";
  const min=0.8,max=1.2,step=0.05;
  let zoom=1;
  try{
    const saved=Number(localStorage.getItem(key));
    if(Number.isFinite(saved)&&saved>=min&&saved<=max)zoom=saved;
  }catch{}
  const apply=()=>{
    document.documentElement.style.zoom=String(zoom);
    try{localStorage.setItem(key,String(zoom));}catch{}
  };
  apply();
  window.addEventListener("wheel",event=>{
    if(!event.ctrlKey)return;
    event.preventDefault();
    const direction=event.deltaY<0?1:-1;
    const next=Math.max(min,Math.min(max,Math.round((zoom+direction*step)*100)/100));
    if(next===zoom)return;
    zoom=next;
    apply();
  },{passive:false});
})();
