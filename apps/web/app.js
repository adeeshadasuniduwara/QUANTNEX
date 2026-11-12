const $ = (id) => document.getElementById(id);
const storageKey = "quantnex.journal.v2";
function loadTrades(){try{const rows=JSON.parse(localStorage.getItem(storageKey)||"[]");return Array.isArray(rows)?rows:[];}catch{return[];}}
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