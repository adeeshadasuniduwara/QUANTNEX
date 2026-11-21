(() => {
  const $ = id => document.getElementById(id);
  const money = n => "$" + Number(n || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const price = n => Number(n).toLocaleString(undefined,{maximumFractionDigits:8});
  let busy = false, analyzeQueued = false;
  let replayKey = "", replayBusy = false, ledgerBusy = false;
  const isTradingViewActive=()=>!document.hidden&&document.querySelector(".workspace-view:not([hidden])")?.dataset.workspaceView==="tradingview";

  function setText(id,value){const el=$(id);if(el)el.textContent=value;}
  function selected(){return {symbol:$("qxSymbol")?.value||"BTCUSDT",interval:$("qxInterval")?.value||"15m",marketType:$("qxMarketType")?.value||"BINANCE_SPOT",min:6};}
  function setStatus(value){setText("qxIntelStatus",value);}
  function renderFeatures(f){
    setText("qxIndEma",price(f.ema20)+" / "+price(f.ema50)+" / "+price(f.ema200));
    setText("qxIndMomentum","RSI "+Number(f.rsi).toFixed(1)+" · MACD "+Number(f.macd_histogram).toFixed(4));
    setText("qxIndVolatility","ADX "+Number(f.adx).toFixed(1)+" · ATR "+price(f.atr));
    setText("qxIndVolume",Number(f.relative_volume).toFixed(2)+"× average");
    setText("qxIndStructure",f.structure.bos_mss+" · "+f.structure.liquidity_sweep);
    setText("qxIndLocation",f.structure.premium_discount+" · EQ "+price(f.structure.equilibrium));
  }
  function renderSignal(data){
    const rows=$("qxLiveSignalsRows"),status=$("qxLiveSignalsStatus");
    if(!rows)return;
    rows.replaceChildren();
    const signal=data.signal;
    if(!signal){
      const tr=document.createElement("tr"),td=document.createElement("td");
      td.colSpan=10;td.className="empty-row";
      td.textContent=data.message||"WAIT · No setup passed the selected confluence threshold. No forced trade.";
      tr.append(td);rows.append(tr);
      if(status)status.textContent=data.status==="ERROR"?"ANALYSIS ERROR":data.status==="FUTURES CHART ONLY"?"FUTURES CHART ONLY":"WAIT · NO QUALIFIED SETUP";
      window.quantnexViewSetTradePlan?.(null);
      return;
    }
    const entry=signal.entry_type==="MARKET"?"MARKET ("+price(signal.entry)+")":"LIMIT ("+price(signal.limit_price||signal.entry)+")";
    const values=[signal.symbol||data.symbol||"—",signal.side,signal.timeframe||data.interval||"—",entry,
      price(signal.stop_loss),price(signal.tp1),price(signal.tp2),price(signal.tp3),
      String(signal.score??data.confluence_score??"—")+"/20",data.status||"SIGNAL"];
    const tr=document.createElement("tr");
    values.forEach((value,index)=>{
      const td=document.createElement("td");td.textContent=String(value??"—");
      if(index===1)td.dataset.side=signal.side;
      if(index===9)td.dataset.status=data.status||"SIGNAL";
      tr.append(td);
    });
    rows.append(tr);
    const note=document.createElement("tr"),detail=document.createElement("td");
    detail.colSpan=10;detail.className="qx-live-signal-note";
    detail.textContent="Setup: "+(signal.confirmations||[]).join(" + ")+
      (signal.entry_reference_note?" · "+signal.entry_reference_note:"")+
      (signal.reasons?.length?" · "+signal.reasons.join(" · "):"");
    note.append(detail);rows.append(note);
    if(status)status.textContent="LIVE · "+signal.side+" · "+signal.symbol;
    window.quantnexViewSetTradePlan?.(signal);
  }
  let performanceBusy=false;
  const formatR=value=>{const n=Number(value)||0;return (n>0?"+":"")+n.toFixed(2)+"R";};
  function renderOverallPerformance(data){
    const set=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
    const direction=(id,value)=>{const el=$(id);if(el)el.dataset.direction=Number(value)>0?"positive":Number(value)<0?"negative":"neutral";};
    set("qxSignalOverallPnl",formatR(data.net_r)+(data.is_complete?"":"*"));
    set("qxSignalRealizedPnl",formatR(data.realized_r));
    set("qxSignalFloatingPnl",formatR(data.floating_r));
    set("qxSignalWinRate",Number(data.win_rate||0).toFixed(1)+"%");
    set("qxSignalTotalTrades",String(data.total_signals||0));
    direction("qxSignalOverallPnl",data.net_r);
    direction("qxSignalRealizedPnl",data.realized_r);
    direction("qxSignalFloatingPnl",data.floating_r);
    const status=$("qxSignalPerformanceStatus");
    if(status){status.textContent=data.is_complete?"ALL MARKETS · SYNCED":"PARTIAL · OPEN PRICE MISSING";status.dataset.state=data.is_complete?"ok":"warning";}
    const note=$("qxSignalOverallNote");
    if(note)note.textContent=data.is_complete
      ?"Includes realized outcomes plus floating P&L on open positions across all symbols. Values are in R (multiples of each signal's initial risk), not account currency."
      :"Net P&L includes all realized results and available floating marks. "+Number(data.unpriced_open_trades||0)+" open trade(s) have no current price, so the floating and net totals are incomplete.";
  }
  async function refreshOverallPerformance(){
    if(performanceBusy||!$("qxSignalOverallSummary"))return;
    performanceBusy=true;
    try{
      const data=await apiRequest("/api/v1/signals/performance");
      renderOverallPerformance(data);
    }catch(error){
      const status=$("qxSignalPerformanceStatus");
      if(status){status.textContent="PERFORMANCE UNAVAILABLE";status.dataset.state="error";}
      const note=$("qxSignalOverallNote");if(note)note.textContent="Could not calculate all-market P&L: "+error.message;
    }finally{performanceBusy=false;}
  }
  function renderLifecycleTrades(trades){
    const rows=$("qxSignalLedgerRows"),summary=$("qxSignalLedgerSummary");
    if(!rows||!summary)return;
    rows.replaceChildren();
    const counts={tracked:trades.length,tp1:trades.filter(x=>x.tp1_hit).length,tp2:trades.filter(x=>x.tp2_hit).length,complete:trades.filter(x=>x.status==="TARGETS_COMPLETE").length};
    summary.replaceChildren();
    [["Tracked",counts.tracked],["TP1",counts.tp1],["TP2",counts.tp2],["Completed",counts.complete]].forEach(([label,value])=>{
      const box=document.createElement("div"),name=document.createElement("span"),number=document.createElement("strong");
      name.textContent=label;number.textContent=String(value);box.append(name,number);summary.append(box);
    });
    if(!trades.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=10;td.className="empty-row";td.textContent="No signals tracked for this market yet.";tr.append(td);rows.append(tr);return;}
    const stamp=value=>value?new Date(value).toLocaleString():"—";
    trades.forEach(item=>{
      const tr=document.createElement("tr");
      const entry=item.entry_type==="MARKET"?"MARKET ("+price(item.entry_price)+")":"LIMIT ("+price(item.limit_price||item.entry_price)+")";
      const target=(n,hit)=>{const td=document.createElement("td");td.textContent=(hit?"✓ ":"")+price(n);if(hit)td.className="qx-ledger-hit";return td;};
      const cells=[stamp(item.signal_time),item.symbol,item.side,entry,price(item.stop_loss)+" / "+price(item.active_stop_loss)];
      cells.forEach(value=>{const td=document.createElement("td");td.textContent=String(value);tr.append(td);});
      tr.append(target(item.tp1,item.tp1_hit),target(item.tp2,item.tp2_hit),target(item.tp3,item.tp3_hit));
      const outcome=document.createElement("td");
      const recovery=item.recovery_status&&item.recovery_status!=="COMPLETE"?" · "+item.recovery_status.replaceAll("_"," ")+" HISTORY":"";
      outcome.textContent=item.status.replaceAll("_"," ")+recovery;outcome.className="qx-ledger-outcome";outcome.dataset.status=item.status;tr.append(outcome);
      const result=document.createElement("td");result.textContent=(Number(item.realized_r)>=0?"+":"")+Number(item.realized_r||0).toFixed(2)+"R";tr.append(result);
      rows.append(tr);
    });
  }
  async function refreshLifecycle(symbol=selected().symbol){
    if(selected().marketType!=="BINANCE_SPOT"){const status=$("qxSignalLedgerStatus");if(status){status.textContent="FUTURES SIGNAL LEDGER NOT ENABLED";status.dataset.state="warning";}return;}
    refreshOverallPerformance();
    if(ledgerBusy||!$("qxSignalLedgerRows"))return;ledgerBusy=true;
    try{
      const rows=await apiRequest("/api/v1/signals/trades?symbol="+encodeURIComponent(symbol)+"&limit=100");
      renderLifecycleTrades(rows);
      const status=$("qxSignalLedgerStatus");if(status){status.textContent="SYNCED · "+rows.length+" records";status.dataset.state="ok";}
    }catch(error){const status=$("qxSignalLedgerStatus");if(status){status.textContent="HISTORY UNAVAILABLE · "+error.message;status.dataset.state="error";}}
    finally{ledgerBusy=false;}
  }
  async function replayHistory(selection){
    if(selection.marketType!=="BINANCE_SPOT"){const note=$("qxSignalReplayNote");if(note)note.textContent="Futures chart is read-only. Futures signal replay is not enabled; Spot replay is not applied to a Futures chart.";return;}
    const day=new Date().toLocaleDateString("en-CA",{timeZone:"Asia/Colombo"});
    const key=[selection.symbol,selection.interval,selection.min,day].join("|");
    if(replayBusy||replayKey===key)return;replayBusy=true;replayKey=key;
    const note=$("qxSignalReplayNote"),status=$("qxSignalLedgerStatus");
    if(status){status.textContent="REPLAYING AVAILABLE HISTORY…";status.dataset.state="";}
    try{
      const data=await apiRequest("/api/v1/quantnex-view/replay",{method:"POST",body:JSON.stringify({symbol:selection.symbol,interval:selection.interval,min_score:selection.min})});
      if(note)note.textContent=data.note+" Replayed "+data.signals_replayed+" signals · "+data.new_trades+" new records · coverage from "+new Date(data.coverage_start).toLocaleString()+".";
      await refreshLifecycle(selection.symbol);
    }catch(error){
      replayKey="";
      if(note)note.textContent="Historical replay unavailable: "+error.message+" Existing tracked trades will still reconcile from the background feed when available.";
    }finally{replayBusy=false;}
  }
  $("qxSignalLedgerRefresh")?.addEventListener("click",()=>refreshLifecycle());
  window.addEventListener("quantnex:workspace-event",event=>{
    if(event.detail?.type==="signals.lifecycle.changed"&&isTradingViewActive())refreshLifecycle();
  });
  window.setInterval(()=>{if(isTradingViewActive())refreshLifecycle();},20000);

  async function analyze(){
    if(!isTradingViewActive())return;
    if(selected().marketType==="BINANCE_USDM_FUTURES"){
      setStatus("FUTURES CHART ONLY · FUTURES SIGNAL ENGINE NOT ENABLED");
      renderSignal({symbol:selected().symbol,status:"FUTURES CHART ONLY",message:"Futures chart is read-only. Futures signal generation is not enabled; Spot signals are never applied to this chart.",signal:null});
      window.quantnexViewSetTradePlan?.(null);
      const summary=$("qxChartIntelSummary");if(summary)summary.textContent="FUTURES CHART · SIGNAL ANALYSIS NOT ENABLED";
      return;
    }
    if(busy){analyzeQueued=true;return;}busy=true;setStatus("ANALYSING");
    try{
      const s=selected();
      const data=await apiRequest("/api/v1/quantnex-view/analyze?symbol="+encodeURIComponent(s.symbol)+"&interval="+encodeURIComponent(s.interval)+"&min_score="+s.min);
      const current=selected();
      if(!isTradingViewActive()||current.symbol!==s.symbol||current.interval!==s.interval||current.marketType!==s.marketType||current.min!==s.min)return;
      renderFeatures(data.features);renderSignal(data);window.quantnexViewSetAnalysis?.(data);
      refreshLifecycle(s.symbol);
      replayHistory(s);
      setStatus(data.status+" · "+data.eligible_setups+" ELIGIBLE / 100");

    }catch(error){setStatus("FEED ERROR");renderSignal({symbol:selected().symbol,status:"ERROR",message:"Signal analysis unavailable: "+error.message,signal:null});}
    finally{busy=false;if(analyzeQueued&&isTradingViewActive()){analyzeQueued=false;analyze();}else if(!isTradingViewActive())analyzeQueued=false;}
  }
  ["qxMarketType","qxSymbol","qxInterval"].forEach(id=>$(id)?.addEventListener("change",analyze));
  window.addEventListener("quantnex:view-changed",event=>{if(event.detail?.view==="tradingview")analyze();});
  document.addEventListener("visibilitychange",()=>{if(isTradingViewActive())analyze();});
  // Historical backtests are user-triggered; do not run 1,000-candle simulations on view entry or on a timer.
  setInterval(()=>{if(isTradingViewActive())analyze();},60000);
  // Recover the selected market's Colombo-day signals as soon as QUANTNEX starts,
  // even if the user initially lands on Overview rather than opening the chart tab.
  refreshLifecycle(selected().symbol);
  replayHistory(selected());
})();
