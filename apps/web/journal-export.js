(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.QuantnexJournalExport=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  function csvCell(value){
    const isNumber=typeof value==="number"&&Number.isFinite(value);
    let text=isNumber?String(value):String(value??"");
    if(!isNumber&&/^[\u0000-\u0020\uFEFF]*[=+\-@]/.test(text))text="'"+text;
    return '"'+text.replaceAll('"','""')+'"';
  }
  function toCsv(rows){
    if(!Array.isArray(rows)||rows.length===0)throw new Error("There are no journal records to export yet.");
    const header=["Date","Symbol","Direction","Outcome","PnL","Notes"];
    const data=rows.map(trade=>[trade.date,trade.symbol,trade.direction,trade.outcome,trade.pnl,trade.notes]);
    return [header,...data].map(row=>row.map(csvCell).join(",")).join("\r\n");
  }
  return Object.freeze({toCsv});
});
