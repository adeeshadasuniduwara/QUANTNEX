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
const updateButton = $("webCheckUpdate");
if (updateButton) updateButton.addEventListener("click", async () => {
  const status = $("webUpdateStatus"), progress = $("webUpdateProgress");
  updateButton.disabled = true; updateButton.textContent = "Checking…"; progress.hidden = false;
  status.textContent = "Connecting to the official QUANTNEX release channel…";
  try {
    const response = await fetch("https://api.github.com/repos/adeeshadasuniduwara/QUANTNEX/releases/latest", {headers:{"Accept":"application/vnd.github+json"}});
    if (response.status === 404) { status.textContent = "No published release is available yet. Check back when the next release is published."; return; }
    if (!response.ok) throw new Error("Release service returned " + response.status);
    const release = await response.json();
    const tag = release.tag_name || "Latest";
    status.textContent = "Latest published release: " + tag + ". Open release notes to review available downloads. Web updates are installed manually; Windows desktop updates use the built-in updater.";
    const link = document.createElement("a"); link.href = release.html_url; link.target = "_blank"; link.rel = "noreferrer"; link.className = "secondary-btn link-btn"; link.textContent = "Open " + tag + " release";
    const actions = document.querySelector(".update-actions"); const old = actions.querySelector(".release-link"); if(old) old.remove(); link.classList.add("release-link"); actions.append(link);
  } catch (error) { status.textContent = "Could not check updates: " + error.message + ". You can open the official releases page instead."; }
  finally { updateButton.disabled = false; updateButton.textContent = "Check for updates"; progress.hidden = true; }
});


// Authenticated shared API wallet. Access tokens stay in this browser tab's session storage.
const API_BASE_KEY = "quantnex.apiBase.v1";
const TOKEN_KEY = "quantnex.sessionToken.v1";
const apiBaseInput = $("apiBase");
const accountMessage = $("accountMessage");
const walletArea = $("walletArea");
apiBaseInput.value = localStorage.getItem(API_BASE_KEY) || "http://127.0.0.1:8000";
function apiBase(){ return apiBaseInput.value.trim().replace(/\\/+$/, ""); }
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
    sessionStorage.setItem(TOKEN_KEY,result.access_token);$("accountPassword").value="";setSignedIn(true);await refreshWallet();setAccountMessage("Signed in. Wallet data loaded from the shared API.");
  }catch(error){setAccountMessage(error.message,true);}
}
$("saveApiBase").addEventListener("click",()=>{try{const url=new URL(apiBase());if(!["http:","https:"].includes(url.protocol))throw new Error();localStorage.setItem(API_BASE_KEY,url.origin+url.pathname.replace(/\\/+$/,""));setAccountMessage("API server URL saved for this browser.");}catch{setAccountMessage("Enter a valid HTTP or HTTPS API URL.",true);}});
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
