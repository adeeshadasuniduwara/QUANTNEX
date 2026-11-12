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
// Local QUANTNEX updater. It checks the latest main-branch commit and installs it safely.
const updateButton=$("webCheckUpdate");
const releaseVersionLabel=$("webReleaseVersion");
const releaseNotesLink=$("webReleaseNotes");
let updatePolling=false;

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
  window.addEventListener("load",()=>showUpdateToast("✓ QUANTNEX Web is now updated to the latest verified GitHub commit."));
}

async function watchUpdateInstall(){
  if(updatePolling)return;
  updatePolling=true;
  const status=$("webUpdateStatus"),progress=$("webUpdateProgress");
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
        window.setTimeout(()=>window.location.replace(window.location.pathname+"?updated="+Date.now()),900);
        return;
      }
      if(state.status==="error")throw new Error(state.message||"Update installation failed.");
      if(state.status==="installing"||state.status==="starting")status.textContent=state.message||"Downloading and installing the verified GitHub update…";
    }
    throw new Error("The update is taking longer than expected. Check the QUANTNEX Web Server CMD window.");
  }catch(error){
    status.textContent="Update did not finish: "+error.message;
  }finally{
    progress.hidden=true;updatePolling=false;
    updateButton.disabled=false;updateButton.textContent="Check & install updates";
  }
}

async function installLatestCommit(){
  const status=$("webUpdateStatus");
  status.textContent="Starting the verified GitHub update…";
  const response=await fetch("/__quantnex/install",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.error||"Could not start update.");
  await watchUpdateInstall();
}

async function checkLocalUpdate(){
  const status=$("webUpdateStatus"),progress=$("webUpdateProgress");
  updateButton.disabled=true;updateButton.textContent="Checking…";progress.hidden=false;
  status.textContent="Checking the latest QUANTNEX main-branch commit on GitHub…";
  try{
    const response=await fetch("/__quantnex/check",{cache:"no-store"});
    if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Local updater is not running.");}
    const result=await response.json();
    $("webInstalledVersion").textContent=result.installed;
    releaseVersionLabel.textContent=result.latest;
    if(result.release_notes)releaseNotesLink.href=result.release_notes;
    if(result.update_available){
      status.textContent="New GitHub update found: "+result.latest+". "+(result.latest_message||"")+" Starting automatic installation…";
      progress.hidden=false;
      await installLatestCommit();
    }else{
      status.textContent="You are already using the latest GitHub source ("+result.latest+").";
    }
  }catch(error){
    status.textContent="Automatic update check failed safely: "+error.message;
  }finally{
    progress.hidden=true;
    if(!updatePolling){updateButton.disabled=false;updateButton.textContent="Check & install updates";}
  }
}
if(updateButton)updateButton.addEventListener("click",checkLocalUpdate);
if(updateButton&&location.hostname==="127.0.0.1"&&location.port==="5500"){
  checkLocalUpdate();
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
function renderWalletTransactions(rows){
  const body=$("walletRows");body.replaceChildren();
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=4;td.className="empty-row";td.textContent="No wallet transactions yet.";tr.append(td);body.append(tr);return;}
  rows.forEach(item=>{const tr=document.createElement("tr");const date=new Date(item.created_at).toLocaleString();const amount=Number(item.amount);[date,item.transaction_type.replaceAll("_"," "),item.description||"—",money(amount)].forEach((value,index)=>{const td=document.createElement("td");td.textContent=value;if(index===3)td.className=amount<0?"negative":"positive";tr.append(td);});body.append(tr);});
}
async function refreshWallet(){
  const [summary,transactions]=await Promise.all([apiRequest("/api/v1/wallet/summary"),apiRequest("/api/v1/wallet/transactions?limit=100")]);
  $("walletBalance").textContent=money(summary.balance);$("walletDeposits").textContent=money(summary.deposits);$("walletWithdrawals").textContent=money(summary.withdrawals);$("walletPnl").textContent=money(summary.trading_pnl);renderWalletTransactions(transactions);
}
async function recordWalletTransaction(type){
  const amountInput=$(type==="deposit"?"depositAmount":"withdrawAmount"),descriptionInput=$(type==="deposit"?"depositDescription":"withdrawDescription"),amount=Number(amountInput.value);
  if(!Number.isFinite(amount)||amount<=0){setAccountMessage("Enter an amount greater than zero.",true);return;}
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

// Phase 06.3 local system health, backup and audit UI.
(function initSystemSecurity(){
  const panel=$("system-security");
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
  $("refreshSystemHealth").addEventListener("click",refreshHealth);
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
