(() => {
  const $ = id => document.getElementById(id);
  const money = n => "$" + Number(n || 0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
  const price = n => Number(n).toLocaleString(undefined,{maximumFractionDigits:8});
  let lastAnalysis = null;
  let busy = false, analyzeQueued = false, backtestBusy = false, backtestQueued = false;
  const isTradingViewActive=()=>!document.hidden&&document.querySelector(".workspace-view:not([hidden])")?.dataset.workspaceView==="tradingview";

  function setText(id,value){const el=$(id);if(el)el.textContent=value;}
  function selected(){return {symbol:$("qxSymbol")?.value||"BTCUSDT",interval:$("qxInterval")?.value||"15m",min:Number($("qxIntelMinScore")?.value||6)};}
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
    const details=document.createElement("p");details.textContent="Selected setup: "+s.confirmations.join(" + ")+" · "+s.timeframe;
    host.append(details);
    const reason=document.createElement("p");reason.className="qx-signal-reasons";reason.textContent=s.reasons.join(" · ");host.append(reason);
    const colorStop=$("qxStopColor")?.value||"#e6535d",colorTarget=$("qxTargetColor")?.value||"#20c997",colorEntry=$("qxEntryColor")?.value||"#e5c15b";
    levels.replaceChildren();
    [["STOP LOSS",s.stop_loss,colorStop],["ENTRY",s.entry,colorEntry],["TP1",s.tp1,colorTarget],["TP2",s.tp2,colorTarget],["TP3",s.tp3,colorTarget]].forEach(([label,value,color])=>{
      const item=document.createElement("div");item.className="qx-position-level";
      item.style.borderColor=color;const name=document.createElement("span"),val=document.createElement("strong");
      name.textContent=label;val.textContent=price(value);val.style.color=color;item.append(name,val);levels.append(item);
    });
    preview.hidden=false;window.quantnexViewSetTradePlan?.(s,{stop:colorStop,target:colorTarget,entry:colorEntry});
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
  async function analyze(){
    if(!isTradingViewActive())return;
    if(busy){analyzeQueued=true;return;}busy=true;setStatus("ANALYSING");
    try{
      const s=selected();
      const data=await apiRequest("/api/v1/quantnex-view/analyze?symbol="+encodeURIComponent(s.symbol)+"&interval="+encodeURIComponent(s.interval)+"&min_score="+s.min);
      const current=selected();
      if(!isTradingViewActive()||current.symbol!==s.symbol||current.interval!==s.interval||current.min!==s.min)return;
      lastAnalysis=data;renderFeatures(data.features);renderSignal(data);window.quantnexViewSetAnalysis?.(data);
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
    }catch(error){setStatus("FEED ERROR");const host=$("qxMainSignal");if(host)host.textContent="Signal analysis unavailable: "+error.message;}
    finally{busy=false;if(analyzeQueued&&isTradingViewActive()){analyzeQueued=false;analyze();}else if(!isTradingViewActive())analyzeQueued=false;}
  }
  async function backtest(){
    if(!isTradingViewActive())return;
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
  ["qxSymbol","qxInterval","qxIntelMinScore"].forEach(id=>$(id)?.addEventListener("change",()=>{analyze();resetBacktestForSelection();}));
  ["qxStopColor","qxTargetColor","qxEntryColor"].forEach(id=>$(id)?.addEventListener("input",()=>{if(lastAnalysis)renderSignal(lastAnalysis);}));
  window.addEventListener("quantnex:view-changed",event=>{if(event.detail?.view==="tradingview")analyze();});
  document.addEventListener("visibilitychange",()=>{if(isTradingViewActive())analyze();});
  // Historical backtests are user-triggered; do not run 1,000-candle simulations on view entry or on a timer.
  setInterval(()=>{if(isTradingViewActive())analyze();},60000);
})();
