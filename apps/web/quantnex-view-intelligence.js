(() => {
  const $ = id => document.getElementById(id);
  const money = n => "$" + Number(n || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const price = n => Number(n).toLocaleString(undefined,{maximumFractionDigits:8});
  let lastAnalysis = null;
  let busy = false, analyzeQueued = false, backtestBusy = false, backtestQueued = false;
  let replayKey = "", replayBusy = false, ledgerBusy = false;
  const isTradingViewActive=()=>!document.hidden&&document.querySelector(".workspace-view:not([hidden])")?.dataset.workspaceView==="tradingview";

  function setText(id,value){const el=$(id);if(el)el.textContent=value;}
  function selected(){return {symbol:$("qxSymbol")?.value||"BTCUSDT",interval:$("qxInterval")?.value||"15m",marketType:$("qxMarketType")?.value||"BINANCE_SPOT",min:Number($("qxIntelMinScore")?.value||6)};}
  function setStatus(value){setText("qxIntelStatus",value);}
  function bindDisclosure(buttonId,contentId,expandLabel="Expand",collapseLabel="Collapse"){
    const button=$(buttonId),content=$(contentId);
    if(!button||!content)return;
    button.addEventListener("click",()=>{
      const expanded=button.getAttribute("aria-expanded")==="true";
      content.hidden=expanded;
      button.setAttribute("aria-expanded",String(!expanded));
      button.textContent=expanded?expandLabel:collapseLabel;
      if(!expanded&&contentId==="qxIndicatorsContent")window.quantnexViewRefreshIndicators?.();
    });
  }
  bindDisclosure("qxSignalSettingsToggle","qxSignalSettingsPanel","⚙ Settings","⚙ Close settings");
  bindDisclosure("qxChartSignalSheetToggle","qxChartSignalSheetContent");
  bindDisclosure("qxSignalLedgerToggle","qxSignalLedgerContent");
  bindDisclosure("qxIndicatorsToggle","qxIndicatorsContent");
  function renderFeatures(f){
    setText("qxIndEma",price(f.ema20)+" / "+price(f.ema50)+" / "+price(f.ema200));
    setText("qxIndMomentum","RSI "+Number(f.rsi).toFixed(1)+" · MACD "+Number(f.macd_histogram).toFixed(4));
    setText("qxIndVolatility","ADX "+Number(f.adx).toFixed(1)+" · ATR "+price(f.atr));
    setText("qxIndVolume",Number(f.relative_volume).toFixed(2)+"× average");
    setText("qxIndStructure",f.structure.bos_mss+" · "+f.structure.liquidity_sweep);
    setText("qxIndLocation",f.structure.premium_discount+" · EQ "+price(f.structure.equilibrium));
  }
  function renderSignal(data){
    const host=$("qxMainSignal"),preview=$("qxPositionPreview"),levels=$("qxPositionLevels");
    if(!host)return;
    host.replaceChildren();
    if(!data.signal){
      const note=document.createElement("div");note.className="qx-signal-empty";
      note.textContent="WAIT · No setup passed the selected confluence threshold and directional filters. No forced trade.";
      host.append(note);preview.hidden=true;window.quantnexViewSetTradePlan?.(null);return;
    }
    const s=data.signal,head=document.createElement("div");head.className="qx-signal-head";
    const title=document.createElement("strong");title.className=s.side==="BUY"?"qx-buy":"qx-sell";title.textContent=s.side+" · "+s.symbol;
    const score=document.createElement("span");score.textContent=s.confidence_label+" · "+s.score+"/20 confluence";
    head.append(title,score);host.append(head);
    const details=document.createElement("p");details.textContent="Selected setup: "+s.confirmations.join(" + ")+" · "+s.timeframe+
      " · Entry: "+(s.entry_type==="MARKET"?"MARKET ("+price(s.entry)+")":"LIMIT ("+price(s.limit_price||s.entry)+")")+
      (s.entry_reference_note?" · "+s.entry_reference_note:"");
    host.append(details);
    const reason=document.createElement("p");reason.className="qx-signal-reasons";reason.textContent=s.reasons.join(" · ");host.append(reason);
    const colorStop=$("qxStopColor")?.value||"#e6535d",colorTarget=$("qxTargetColor")?.value||"#20c997",colorEntry=$("qxEntryColor")?.value||"#e5c15b";
    levels.replaceChildren();
    [["STOP LOSS",s.stop_loss,colorStop],[s.entry_type==="MARKET"?"ENTRY · MARKET":"ENTRY · LIMIT",s.entry,colorEntry],["TP1",s.tp1,colorTarget],["TP2",s.tp2,colorTarget],["TP3",s.tp3,colorTarget]].forEach(([label,value,color])=>{
      const item=document.createElement("div");item.className="qx-position-level";
      item.style.borderColor=color;const name=document.createElement("span"),val=document.createElement("strong");
      name.textContent=label;val.textContent=label.startsWith("ENTRY")&&s.entry_type==="MARKET"?"MARKET ("+price(value)+")":price(value);val.style.color=color;item.append(name,val);levels.append(item);
    });
    preview.hidden=false;window.quantnexViewSetTradePlan?.(s,{stop:colorStop,target:colorTarget,entry:colorEntry});
  }
  function renderLiveSignals(data,selection=selected(),state){
    const rows=$("qxLiveSignalsRows"),status=$("qxLiveSignalsStatus");
    if(!rows)return;
    rows.replaceChildren();
    const signal=data?.signal;
    const addEmpty=message=>{
      const tr=document.createElement("tr"),td=document.createElement("td");
      td.colSpan=10;td.className="empty-row";td.textContent=message;tr.append(td);rows.append(tr);
    };
    if(selection.marketType==="BINANCE_USDM_FUTURES"){
      addEmpty("USDⓈ-M Futures chart is read-only. A separate validated Futures signal engine is not enabled.");
      if(status)status.textContent="FUTURES · CHART ONLY";
      return;
    }
    if(!signal){
      addEmpty(state==="ERROR"?"Live analysis is temporarily unavailable. Retrying automatically…":"WAIT · No confirmed setup passed the current filters. The engine keeps monitoring.");
      if(status)status.textContent=state==="ERROR"?"RETRYING":"WAITING · LIVE";
      return;
    }
    const market=selection.marketType==="BINANCE_USDM_FUTURES"?signal.symbol+".P":signal.symbol;
    const entry=signal.entry_type==="MARKET"?"MARKET ("+price(signal.entry)+")":"LIMIT ("+price(signal.limit_price||signal.entry)+")";
    const values=[market,signal.side,signal.timeframe||selection.interval,entry,price(signal.stop_loss),price(signal.tp1),price(signal.tp2),price(signal.tp3),String(signal.score)+"/20","SIGNAL READY"];
    const tr=document.createElement("tr");
    values.forEach((value,index)=>{const td=document.createElement("td");td.textContent=String(value);if(index===1)td.dataset.side=signal.side;if(index===9)td.className="qx-live-signal-ready";tr.append(td);});
    rows.append(tr);
    if(status)status.textContent="LIVE · "+new Date(data.generated_at||Date.now()).toLocaleTimeString();
  }
  function renderBacktest(data){
    const host=$("qxBacktestMetrics");host.replaceChildren();
    [["Simulated balance",money(data.final_balance)],["Net P&L",money(data.net_pnl)],["Trades",String(data.trades)],
     ["Win rate",Number(data.win_rate).toFixed(2)+"%"],["Profit factor",data.profit_factor==null?"—":Number(data.profit_factor).toFixed(2)],
     ["Max drawdown",Number(data.max_drawdown_percent).toFixed(2)+"%"]].forEach(([k,v])=>{
      const item=document.createElement("div");item.className="qx-backtest-metric";
      const label=document.createElement("span"),value=document.createElement("strong");
      label.textContent=k;value.textContent=v;item.append(label,value);host.append(item);
    });
    setText("qxBacktestStatus","COMPLETED · "+data.interval);
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
      lastAnalysis=null;
      setStatus("FUTURES CHART ONLY · FUTURES SIGNAL ENGINE NOT ENABLED");
      const host=$("qxMainSignal");if(host)host.textContent="Futures market data is displayed read-only. Spot signal rules are deliberately not run against this Futures chart.";
      renderLiveSignals(null,selected());
      const list=$("qxStrategyList");if(list)list.textContent="USDⓈ-M Futures strategy evaluation is not enabled yet.";
      window.quantnexViewSetTradePlan?.(null);
      const summary=$("qxChartIntelSummary");if(summary)summary.textContent="FUTURES CHART · SIGNAL ANALYSIS NOT ENABLED";
      setText("qxBacktestStatus","FUTURES BACKTEST NOT ENABLED");
      return;
    }
    if(busy){analyzeQueued=true;return;}busy=true;setStatus("ANALYSING");
    try{
      const s=selected();
      const data=await apiRequest("/api/v1/quantnex-view/analyze?symbol="+encodeURIComponent(s.symbol)+"&interval="+encodeURIComponent(s.interval)+"&min_score="+s.min);
      const current=selected();
      if(!isTradingViewActive()||current.symbol!==s.symbol||current.interval!==s.interval||current.marketType!==s.marketType||current.min!==s.min)return;
      lastAnalysis=data;renderFeatures(data.features);renderSignal(data);renderLiveSignals(data,s);window.quantnexViewSetAnalysis?.(data);
      refreshLifecycle(s.symbol);
      replayHistory(s);
      setStatus(data.status+" · "+data.eligible_setups+" ELIGIBLE / 100");
      const list=$("qxStrategyList");
      if(list){
        list.replaceChildren();
        const summary=document.createElement("p");summary.textContent=data.strategies_evaluated+" setup variants checked; "+data.eligible_setups+" passed their context gates. Scores rank confluence, not win probability.";
        list.append(summary);
        const table=document.createElement("div");table.className="qx-strategy-list";
        (data.strategy_evaluations||[]).filter(x=>x.eligible).forEach(x=>{
          const row=document.createElement("div");row.textContent=x.id+" · "+x.name+" · "+x.side;table.append(row);
        });
        if(!table.childElementCount){const empty=document.createElement("p");empty.textContent="No setup variants passed all context gates on this candle.";table.append(empty);}
        list.append(table);
      }
    }catch(error){setStatus("FEED ERROR");renderLiveSignals(null,selected(),"ERROR");const host=$("qxMainSignal");if(host)host.textContent="Signal analysis unavailable: "+error.message;}
    finally{busy=false;if(analyzeQueued&&isTradingViewActive()){analyzeQueued=false;analyze();}else if(!isTradingViewActive())analyzeQueued=false;}
  }
  async function backtest(){
    if(!isTradingViewActive()||selected().marketType!=="BINANCE_SPOT"){setText("qxBacktestStatus","FUTURES BACKTEST NOT ENABLED");return;}
    if(backtestBusy){backtestQueued=true;return;}backtestBusy=true;
    const button=$("qxRunBacktest");if(button)button.disabled=true;setText("qxBacktestStatus","RUNNING");
    try{
      const s=selected(),balance=Number($("qxBacktestBalance").value),risk=Number($("qxBacktestRisk").value);
      const url="/api/v1/quantnex-view/backtest?symbol="+encodeURIComponent(s.symbol)+"&interval="+encodeURIComponent(s.interval)+
        "&initial_balance="+encodeURIComponent(balance)+"&risk_percent="+encodeURIComponent(risk)+"&min_score="+s.min;
      const data=await apiRequest(url),current=selected();
      if(isTradingViewActive()&&current.symbol===s.symbol&&current.interval===s.interval&&current.min===s.min&&Number($("qxBacktestBalance").value)===balance&&Number($("qxBacktestRisk").value)===risk)renderBacktest(data);
    }catch(error){if(isTradingViewActive()){setText("qxBacktestStatus","ERROR");const host=$("qxBacktestMetrics");host.textContent="Backtest unavailable: "+error.message;}}
    finally{backtestBusy=false;if(button)button.disabled=false;if(backtestQueued&&isTradingViewActive()){backtestQueued=false;backtest();}else if(!isTradingViewActive())backtestQueued=false;}
  }
  function resetBacktestForSelection(){
    backtestQueued=false;
    const host=$("qxBacktestMetrics");if(host)host.replaceChildren();
    setText("qxBacktestStatus","SELECTION CHANGED · RUN BACKTEST");
  }
  $("qxRunBacktest")?.addEventListener("click",backtest);
  ["qxMarketType","qxSymbol","qxInterval","qxIntelMinScore"].forEach(id=>$(id)?.addEventListener("change",()=>{renderLiveSignals(null,selected());analyze();resetBacktestForSelection();}));
  ["qxStopColor","qxTargetColor","qxEntryColor"].forEach(id=>$(id)?.addEventListener("input",()=>{if(lastAnalysis)renderSignal(lastAnalysis);}));
  window.addEventListener("quantnex:view-changed",event=>{if(event.detail?.view==="tradingview")analyze();});
  document.addEventListener("visibilitychange",()=>{if(isTradingViewActive())analyze();});
  // Historical backtests are user-triggered; do not run 1,000-candle simulations on view entry or on a timer.
  setInterval(()=>{if(isTradingViewActive())analyze();},60000);
  // Recover the selected market's Colombo-day signals as soon as QUANTNEX starts,
  // even if the user initially lands on Overview rather than opening the chart tab.
  refreshLifecycle(selected().symbol);
  replayHistory(selected());
})();
