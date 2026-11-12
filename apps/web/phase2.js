// QUANTNEX Phase 02 — local-only tools. No broker integration or order execution.
const byId = (id) => document.getElementById(id);
byId("calculate").addEventListener("click", () => {
  const equity = Number(byId("equity").value);
  const riskPct = Number(byId("risk").value);
  const stop = Number(byId("stop").value);
  const pipValue = Number(byId("pipvalue").value);
  const out = byId("lotResult");
  if (![equity,riskPct,stop,pipValue].every(Number.isFinite) || equity<=0 || riskPct<=0 || riskPct>100 || stop<=0 || pipValue<=0) {
    out.textContent = "Please enter valid positive values. Risk must be between 0 and 100%.";
    return;
  }
  const riskAmount = equity * riskPct / 100;
  const lots = riskAmount / (stop * pipValue);
  out.innerHTML = '<strong>' + lots.toFixed(3) + ' lots</strong>Risk amount: $' + riskAmount.toFixed(2) + ' · Estimated loss at stop: $' + (lots*stop*pipValue).toFixed(2);
});
const storageKey = "quantnex.phase2.journal.v1";
function loadTrades(){ try { const v=JSON.parse(localStorage.getItem(storageKey)||"[]"); return Array.isArray(v)?v:[]; } catch { return []; } }
function renderTrades(){
  const list=byId("journalList"); list.replaceChildren();
  const trades=loadTrades();
  if(!trades.length){const p=document.createElement("p");p.className="hint";p.textContent="No journal entries yet.";list.append(p);return;}
  trades.slice().reverse().forEach((t)=>{
    const row=document.createElement("div");row.className="p2-entry";
    const left=document.createElement("span");left.textContent=t.symbol+" · "+t.direction+" · "+t.outcome+" · "+t.date;
    const right=document.createElement("strong");right.textContent=(t.pnl<0?"−":"+")+"$"+Math.abs(t.pnl).toFixed(2);
    row.append(left,right);list.append(row);
  });
}
byId("saveTrade").addEventListener("click",()=>{
  const symbol=byId("symbol").value.trim().toUpperCase();
  const pnl=Number(byId("pnl").value);
  if(!symbol || !Number.isFinite(pnl)){window.alert("Enter a symbol and a valid P&L amount.");return;}
  const trades=loadTrades();
  trades.push({symbol,direction:byId("direction").value,outcome:byId("outcome").value,pnl,notes:byId("notes").value.trim(),date:new Date().toISOString().slice(0,10)});
  try{localStorage.setItem(storageKey,JSON.stringify(trades));byId("symbol").value="";byId("pnl").value="";byId("notes").value="";renderTrades();}
  catch{window.alert("Could not save journal data in this browser.");}
});
renderTrades();