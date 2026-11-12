(() => {
  const $ = (id) => document.getElementById(id);
  const tfKey = "quantnex.signal.timeframes.v1";
  const tfNames = {"1":"M1","5":"M5","15":"M15","30":"M30","50":"M50","60":"H1","240":"H4"};
  const money = v => "$" + Math.abs(v).toFixed(2);
  const num = id => Number($(id).value);
  let currentPlan = null;

  function readPlan() {
    const p={side:$("side").value,entry:num("entry"),sl:num("stopLoss"),t1:num("tp1"),t2:num("tp2"),t3:num("tp3"),
      equity:num("signalEquity"),risk:num("riskPct"),value:num("usdPerDollarMove")};
    if(![p.entry,p.sl,p.t1,p.t2,p.t3,p.equity,p.risk,p.value].every(Number.isFinite) ||
      [p.entry,p.sl,p.t1,p.t2,p.t3,p.equity,p.risk,p.value].some(v=>v<=0) || p.risk>5)return null;
    if(p.side==="BUY" ? !(p.sl<p.entry&&p.entry<p.t1&&p.t1<p.t2&&p.t2<p.t3) :
      !(p.t3<p.t2&&p.t2<p.t1&&p.t1<p.entry&&p.entry<p.sl))return null;
    return p;
  }
  function renderPosition() {
    const p=readPlan(),status=$("signalCalcStatus"),result=$("positionSummary");
    if(!p){status.textContent="Check price order: BUY needs SL < Entry < TP1 < TP2 < TP3; SELL needs TP3 < TP2 < TP1 < Entry < SL.";
      result.textContent="Enter a valid setup."; $("riskRewardVisual").hidden=true;currentPlan=null;return;}
    currentPlan=p;
    const distance=Math.abs(p.entry-p.sl),riskCash=p.equity*p.risk/100,lots=riskCash/(distance*p.value);
    const rrs=[p.t1,p.t2,p.t3].map(t=>Math.abs(t-p.entry)/distance);
    const stopPct=Math.max(12,Math.min(42,100*distance/(distance+Math.abs(p.t3-p.entry))));
    $("riskRewardVisual").hidden=false;$("lossZone").style.flex="0 0 "+stopPct+"%";$("profitZone").style.flex="1";
    $("lossZone").textContent="LOSS / SL "+p.sl.toFixed(2);
    $("profitZone").textContent="PROFIT · TP1 "+p.t1.toFixed(2)+" · TP2 "+p.t2.toFixed(2)+" · TP3 "+p.t3.toFixed(2);
    $("entryMarker").textContent="ENTRY "+p.entry.toFixed(2);result.replaceChildren();
    [["Risk amount",money(riskCash)],["Estimated size",lots.toFixed(3)+" lots"],["TP1 R:R","1:"+rrs[0].toFixed(2)],["TP2 R:R","1:"+rrs[1].toFixed(2)],["TP3 R:R","1:"+rrs[2].toFixed(2)]].forEach(([a,b])=>{
      const d=document.createElement("div"),s=document.createElement("span"),v=document.createElement("strong");
      d.className="position-stat";s.textContent=a;v.textContent=b;d.append(s,v);result.append(d);
    });
    status.textContent="Risk estimate ready. Verify contract size, tick value and lot sizing with your broker.";
  }
  ["side","entry","stopLoss","tp1","tp2","tp3","signalEquity","riskPct","usdPerDollarMove"].forEach(id=>$(id).addEventListener("input",renderPosition));
  $("side").addEventListener("change",renderPosition);

  function readSettings() {
    const enabled=[...document.querySelectorAll('input[name="analysisTf"]:checked')].map(el=>el.value);
    return {primary:$("primarySignalTf").value,trend:$("trendSignalTf").value,chart:$("chartSignalTf").value,
      enabled,risk_percent:Number($("signalRiskPct").value),min_score:Number($("signalMinScore").value)};
  }
  function applySettings(settings) {
    $("primarySignalTf").value=settings.primary||"5";$("trendSignalTf").value=settings.trend||"60";
    $("chartSignalTf").value=settings.chart||$("chartSignalTf").value||"15";$("signalRiskPct").value=settings.risk_percent||1;
    $("signalMinScore").value=String(settings.min_score||7);
    document.querySelectorAll('input[name="analysisTf"]').forEach(el=>{el.checked=(settings.enabled||["60","30","15","5","1"]).includes(el.value);});
  }
  async function saveSettings() {
    const s=readSettings();
    if(!s.enabled.length){$("timeframeStatus").textContent="Select at least one analysis timeframe.";return null;}
    if(!Number.isFinite(s.risk_percent)||s.risk_percent<=0||s.risk_percent>5){$("timeframeStatus").textContent="Risk per signal must be above 0 and no more than 5%.";return null;}
    localStorage.setItem(tfKey,JSON.stringify(s));
    try {
      if(typeof sessionToken==="function"&&sessionToken()){
        await apiRequest("/api/v1/signals/settings",{method:"PUT",body:JSON.stringify(s)});
        $("timeframeStatus").textContent="Saved to your QUANTNEX account · Primary "+tfNames[s.primary]+" · Trend "+tfNames[s.trend]+" · Analysis "+s.enabled.map(x=>tfNames[x]).join(", ")+".";
      } else {
        $("timeframeStatus").textContent="Saved on this device. Sign in to QUANTNEX to sync settings and run server-side analysis.";
      }
    } catch(e){$("timeframeStatus").textContent="Local settings saved; API sync failed: "+e.message;}
    return s;
  }
  function applyChartTimeframe() {
    const s=readSettings();
    if(s.chart==="50"){$("timeframeStatus").textContent="M50 is a custom aggregation and is not supported by the TradingView embed. Use M1/M5/M15/M30/H1 for the chart; M50 can be used by the analysis engine.";return;}
    const host=$("xauTradingView");if(!host)return;
    host.replaceChildren();const widget=document.createElement("div");widget.className="tradingview-widget-container__widget";host.append(widget);
    const script=document.createElement("script");script.type="text/javascript";script.async=true;
    script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.text=JSON.stringify({autosize:true,symbol:"OANDA:XAUUSD",interval:s.chart,timezone:"Etc/UTC",theme:"dark",style:"1",locale:"en",allow_symbol_change:true,calendar:false,support_host:"https://www.tradingview.com"});
    host.append(script);$("timeframeStatus").textContent="TradingView XAUUSD chart changed to "+tfNames[s.chart]+".";
  }
  $("saveTimeframes").addEventListener("click",saveSettings);
  $("syncTimeframes").addEventListener("click",async()=>{
    try{
      if(typeof sessionToken!=="function"||!sessionToken())throw new Error("Sign in to QUANTNEX first.");
      const remote=await apiRequest("/api/v1/signals/settings");applySettings(remote);
      localStorage.setItem(tfKey,JSON.stringify({...remote,chart:$("chartSignalTf").value}));
      $("timeframeStatus").textContent="Loaded the latest settings from your QUANTNEX account / Telegram bot.";
    }catch(e){$("timeframeStatus").textContent=e.message;}
  });
  $("applyChartTf").addEventListener("click",async()=>{await saveSettings();applyChartTimeframe();});
  function loadLocalSettings(){try{const s=JSON.parse(localStorage.getItem(tfKey)||"null");if(s)applySettings(s);}catch{}}
  loadLocalSettings();
  if(typeof sessionToken==="function"&&sessionToken()){
    apiRequest("/api/v1/signals/settings").then(applySettings).catch(()=>{});
    apiRequest("/api/v1/signals/status").then(status=>{
      $("signalEngineState").textContent=status.configured?"MARKET FEED READY":"ADD MARKET DATA KEY";
    }).catch(()=>{});
  }

  function addStat(parent,label,value) {
    const d=document.createElement("div"),s=document.createElement("span"),v=document.createElement("strong");
    d.className="position-stat";s.textContent=label;v.textContent=value;d.append(s,v);parent.append(d);
  }
  function renderScan(data) {
    const result=$("signalResult"),state=$("signalEngineState"),readout=$("indicatorReadout");
    result.replaceChildren();readout.replaceChildren();
    state.textContent=data.status==="SIGNAL"?"SIGNAL READY":"WAIT / NO SETUP";
    const score=document.createElement("div");score.className="signal-score";
    score.textContent="Confluence "+data.confluence_score+"/"+data.score_out_of+" · "+(data.score_note||"Rule-based score, not win probability");result.append(score);
    if(data.signal){
      const s=data.signal;const head=document.createElement("h3");head.textContent=s.side+" XAUUSD · "+(tfNames[s.timeframe]||s.timeframe);result.append(head);
      const grid=document.createElement("div");grid.className="position-summary signal-levels";
      [["Entry",s.entry],["Stop Loss",s.stop_loss],["TP1",s.tp1],["TP2",s.tp2],["TP3",s.tp3]].forEach(([a,b])=>addStat(grid,a,String(b)));
      result.append(grid);
      $("side").value=s.side;$("entry").value=s.entry;$("stopLoss").value=s.stop_loss;$("tp1").value=s.tp1;$("tp2").value=s.tp2;$("tp3").value=s.tp3;
      $("riskPct").value=String($("signalRiskPct").value||1);renderPosition();
      const title=document.createElement("h4");title.textContent="Confirmations ("+s.confirmations.length+")";result.append(title);
      const list=document.createElement("ul");list.className="confirmation-list";
      s.confirmations.forEach(x=>{const li=document.createElement("li");li.textContent="✓ "+x;list.append(li);});result.append(list);
      $("telegramStatus").textContent=data.telegram_sent?"Signal sent to your connected Telegram bot.":"Signal calculated. Connect Telegram to receive automatic signal messages.";
    } else {
      const p=document.createElement("p");p.textContent=data.message||"No high-confluence setup. Wait for confirmation.";result.append(p);
    }
    Object.entries(data.timeframes||{}).forEach(([tf,v])=>{
      const card=document.createElement("div");card.className="indicator-card";
      const h=document.createElement("strong");h.textContent=tfNames[tf]||tf;card.append(h);
      [["Bias",v.bias],["EMA20 / 50 / 200",[v.ema20,v.ema50,v.ema200??"n/a"].join(" / ")],
       ["MACD histogram",v.macd_histogram],["RSI",v.rsi],["ADX",v.adx],["ATR",v.atr],
       ["BOS / MSS",v.structure?.bos_mss],["Liquidity sweep",v.structure?.liquidity_sweep],["Premium / discount",v.structure?.premium_discount],["FVG / iFVG",JSON.stringify(v.structure?.bullish_fvg||v.structure?.bearish_fvg||v.structure?.bullish_ifvg||v.structure?.bearish_ifvg||null)],["Order / breaker block",JSON.stringify(v.structure?.bullish_order_block||v.structure?.bearish_order_block||v.structure?.bullish_breaker_block||v.structure?.bearish_breaker_block||null)]].forEach(([a,b])=>{
        const line=document.createElement("div");line.textContent=a+": "+String(b??"—");card.append(line);
      });
      readout.append(card);
    });
  }
  $("runSignalScan").addEventListener("click",async()=>{
    const button=$("runSignalScan");button.disabled=true;button.textContent="Scanning…";
    $("signalEngineState").textContent="FETCHING MARKET DATA";
    try{
      const s=await saveSettings();if(!s)throw new Error("Check timeframe settings.");
      if(typeof sessionToken!=="function"||!sessionToken())throw new Error("Sign in to your QUANTNEX account before running a live scan.");
      const data=await apiRequest("/api/v1/signals/scan",{method:"POST"});
      renderScan(data);
      $("timeframeStatus").textContent="Analysis updated at "+new Date(data.generated_at).toLocaleString()+". Source: "+data.provider+".";
    }catch(e){$("signalEngineState").textContent="FEED / API ERROR";$("signalResult").textContent=e.message;}
    finally{button.disabled=false;button.textContent="Run XAUUSD signal scan";}
  });

  async function storedTelegramMessage(message){
    if(typeof sessionToken!=="function"||!sessionToken())throw new Error("Sign in to QUANTNEX first.");
    return apiRequest("/api/v1/telegram/notify",{method:"POST",body:JSON.stringify({message})});
  }
  $("connectTelegram").addEventListener("click",async()=>{
    const token=$("tgBotToken").value.trim(),chat=$("tgChatId").value.trim(),button=$("connectTelegram");
    if(!token||!chat){$("telegramStatus").textContent="Enter your BotFather token and private chat ID or channel username.";return;}
    button.disabled=true;button.textContent="Connecting…";
    try{
      const data=await apiRequest("/api/v1/telegram/connect",{method:"POST",body:JSON.stringify({bot_token:token,chat_id:chat})});
      $("telegramStatus").textContent="Connected to @"+(data.bot_username||"your bot")+". Commands enabled: /help, /timeframes, /settf, /settrend, /setanalysis, /scan, /status.";
      $("tgBotToken").value="";
    }catch(e){$("telegramStatus").textContent=e.message;}
    finally{button.disabled=false;button.textContent="Connect bot & enable commands";}
  });
  $("testTelegram").addEventListener("click",async()=>{
    try{await storedTelegramMessage("QUANTNEX Telegram connection test successful. Send /help to see bot commands.");$("telegramStatus").textContent="Telegram test message sent.";}
    catch(e){$("telegramStatus").textContent=e.message;}
  });
  $("sendPlanTelegram").addEventListener("click",async()=>{
    if(!currentPlan)renderPosition();if(!currentPlan)return;
    const p=currentPlan,lots=(p.equity*p.risk/100)/(Math.abs(p.entry-p.sl)*p.value);
    const message=["QUANTNEX · XAUUSD TRADE PLAN","Side: "+p.side,"Entry: "+p.entry,"Stop Loss: "+p.sl,"TP1: "+p.t1,"TP2: "+p.t2,"TP3: "+p.t3,"Risk: "+p.risk+"% ($"+(p.equity*p.risk/100).toFixed(2)+")","Estimated size: "+lots.toFixed(3)+" lots","Move SL to breakeven only after TP1 is confirmed at your broker.","No broker order was placed."].join("\n");
    try{await storedTelegramMessage(message);$("telegramStatus").textContent="Trade plan sent to your connected Telegram bot.";}
    catch(e){$("telegramStatus").textContent=e.message;}
  });
  $("tp1Breakeven").addEventListener("click",async()=>{
    if(!currentPlan)renderPosition();if(!currentPlan)return;const p=currentPlan;
    try{await storedTelegramMessage("⚠️ QUANTNEX · TP1 MANUALLY CONFIRMED\nXAUUSD "+p.side+" · TP1 "+p.t1+"\nSuggested action: move SL to breakeven (Entry "+p.entry+"). Verify the broker position and move SL manually. No order was changed.");$("telegramStatus").textContent="TP1 breakeven warning sent.";}
    catch(e){$("telegramStatus").textContent=e.message;}
  });
  $("clearTelegram").addEventListener("click",async()=>{
    try{if(typeof sessionToken==="function"&&sessionToken())await apiRequest("/api/v1/telegram/connect",{method:"DELETE"});}
    catch(e){$("telegramStatus").textContent=e.message;return;}
    $("tgBotToken").value="";$("tgChatId").value="";$("telegramStatus").textContent="Telegram bot disconnected and stored token removed.";
  });
  $("openBotGuide").addEventListener("click",()=>{$("telegramGuide").hidden=!$("telegramGuide").hidden;});
  $("clearTelegram").title="Disconnect the saved Telegram bot";
  renderPosition();
})();