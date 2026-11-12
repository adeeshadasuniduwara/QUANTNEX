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
      await apiRequest("/api/v1/signals/settings",{method:"PUT",body:JSON.stringify(s)});
      $("timeframeStatus").textContent="Saved to this local QUANTNEX workspace · Primary "+tfNames[s.primary]+" · Trend "+tfNames[s.trend]+" · Analysis "+s.enabled.map(x=>tfNames[x]).join(", ")+".";

    } catch(e){$("timeframeStatus").textContent="Local settings saved; API sync failed: "+e.message;}
    return s;
  }
  function applyChartTimeframe() {
    const settings=readSettings(),market=$("signalMarketSymbol")?.value||"BTCUSDT";
    const symbol=$("qxSymbol"),timeframe=$("qxInterval");
    if(symbol){symbol.value=market;symbol.dispatchEvent(new Event("change"));}
    if(timeframe){
      timeframe.value=settings.chart==="50"?"15m":({"1":"1m","5":"5m","15":"15m","30":"30m","60":"1h"}[settings.chart]||"15m");
      timeframe.dispatchEvent(new Event("change"));
    }
    $("timeframeStatus").textContent="QUANTNEX VIEW updated · "+market+" · "+(tfNames[settings.chart]||settings.chart)+(settings.chart==="50"?" (chart uses M15; M50 remains available for analysis)":"")+".";
  }
  $("saveTimeframes").addEventListener("click",saveSettings);
  $("syncTimeframes").addEventListener("click",async()=>{
    try{
      const remote=await apiRequest("/api/v1/signals/settings");applySettings(remote);
      localStorage.setItem(tfKey,JSON.stringify({...remote,chart:$("chartSignalTf").value}));
      $("timeframeStatus").textContent="Loaded the latest settings from your QUANTNEX account / Telegram bot.";
    }catch(e){$("timeframeStatus").textContent=e.message;}
  });
  $("applyChartTf").addEventListener("click",async()=>{await saveSettings();applyChartTimeframe();});
  function loadLocalSettings(){try{const s=JSON.parse(localStorage.getItem(tfKey)||"null");if(s)applySettings(s);}catch{}}
  loadLocalSettings();
  apiRequest("/api/v1/signals/settings").then(applySettings).catch(()=>{});
  apiRequest("/api/v1/signals/status").then(status=>{
    const ready=!!status.crypto_configured;
    $("signalEngineState").textContent=ready?(status.gold_configured?"CRYPTO + GOLD READY":"CRYPTO READY · GOLD OPTIONAL"):"SIGNAL FEED NOT CONFIGURED";
    $("signalEngineState").title=status.note||"Signal-provider status";
  }).catch(error=>{
    $("signalEngineState").textContent="SIGNAL STATUS UNAVAILABLE";
    $("signalEngineState").title="The local signal-status API could not be reached: "+error.message;
  });

  function addStat(parent,label,value) {
    const d=document.createElement("div"),s=document.createElement("span"),v=document.createElement("strong");
    d.className="position-stat";s.textContent=label;v.textContent=value;d.append(s,v);parent.append(d);
  }
  function renderScan(data) {
    const result=$("signalResult"),state=$("signalEngineState"),readout=$("indicatorReadout");
    result.replaceChildren();readout.replaceChildren();
    state.textContent=data.status==="SIGNAL"?"SIGNAL READY":"WAIT / NO SETUP";
    if(data.quality_filters){
      const filters=document.createElement("p");filters.className="signal-feed-note";
      filters.textContent="Directional quality gates: "+Object.entries(data.quality_filters).map(([k,v])=>k.replaceAll("_"," ")+": "+(v?"PASS":"FAIL")).join(" · ");
      result.append(filters);
    }
    const score=document.createElement("div");score.className="signal-score";
    score.textContent="Confluence "+data.confluence_score+"/"+data.score_out_of+" · "+(data.score_note||"Rule-based score, not win probability");result.append(score);
    if(data.signal){
      const s=data.signal;const head=document.createElement("h3");head.textContent=s.side+" "+(data.symbol||"MARKET")+" · "+(tfNames[s.timeframe]||s.timeframe);result.append(head);
      const grid=document.createElement("div");grid.className="position-summary signal-levels";
      [["Entry",s.entry],["Stop Loss",s.stop_loss],["TP1",s.tp1],["TP2",s.tp2],["TP3",s.tp3]].forEach(([a,b])=>addStat(grid,a,String(b)));
      result.append(grid);
      $("side").value=s.side;$("entry").value=s.entry;$("stopLoss").value=s.stop_loss;$("tp1").value=s.tp1;$("tp2").value=s.tp2;$("tp3").value=s.tp3;
      $("riskPct").value=String($("signalRiskPct").value||1);renderPosition();
      const title=document.createElement("h4");title.textContent="Confirmations ("+s.confirmations.length+")";result.append(title);
      const list=document.createElement("ul");list.className="confirmation-list";
      s.confirmations.forEach(x=>{const li=document.createElement("li");li.textContent="✓ "+x;list.append(li);});result.append(list);
      $("telegramStatus").textContent=data.telegram_sent?"Signal sent to your connected Telegram bot.":(data.telegram_note||"Signal calculated, but Telegram delivery did not complete. Check your bot connection.");
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
      const symbol=$("signalMarketSymbol")?.value||"BTCUSDT";
      const data=await apiRequest("/api/v1/signals/scan?symbol="+encodeURIComponent(symbol),{method:"POST"});
      renderScan(data);
      $("timeframeStatus").textContent="Analysis updated at "+new Date(data.generated_at).toLocaleString()+". Source: "+data.provider+".";
    }catch(e){$("signalEngineState").textContent="FEED / API ERROR";$("signalResult").textContent=e.message;}
    finally{button.disabled=false;button.textContent="Run market signal scan";}
  });

  async function storedTelegramMessage(message){
    return apiRequest("/api/v1/telegram/notify",{method:"POST",body:JSON.stringify({message})});
  }
  $("connectTelegram").addEventListener("click",async()=>{
    const token=$("tgBotToken").value.trim(),chat=$("tgChatId").value.trim(),button=$("connectTelegram");
    if(!token||!chat){$("telegramStatus").textContent="Enter your BotFather token and private chat ID or channel username.";return;}
    button.disabled=true;button.textContent="Connecting…";
    try{
      const data=await apiRequest("/api/v1/telegram/connect",{method:"POST",body:JSON.stringify({bot_token:token,chat_id:chat,display_name:$("tgBotDisplayName").value.trim()})});
      $("telegramStatus").textContent="Connected to "+($("tgBotDisplayName").value.trim()||"@"+(data.bot_username||"your bot"))+" (@"+(data.bot_username||"bot")+"). Commands enabled: /help, /timeframes, /settf, /settrend, /setanalysis, /scan BTCUSDT, /scan ETHUSDT, /scan SOLUSDT, /scan XAUUSD, /status.";
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
    try{await apiRequest("/api/v1/telegram/connect",{method:"DELETE"});}
    catch(e){$("telegramStatus").textContent=e.message;return;}
    $("tgBotToken").value="";$("tgChatId").value="";$("autoSignalsEnabled").checked=false;$("autoSignalStatus").textContent="Auto Signals OFF. Reconnect a bot before enabling it again.";$("telegramMonitorTitle").textContent="Telegram bot not connected";$("telegramMonitorDescription").textContent="Connect a bot in Signal Lab to enable delivery.";$("telegramMonitorPill").textContent="OFFLINE";$("telegramStatus").textContent="Telegram bot disconnected and stored token removed.";
  });
  $("openBotGuide").addEventListener("click",()=>{$("telegramGuide").hidden=!$("telegramGuide").hidden;});
  $("clearTelegram").title="Disconnect the saved Telegram bot";
  renderPosition();

  // QUANTNEX VIEW is the first-party chart workspace.
  async function loadAutoSignalSettings(){
    try{
      const [settings,bot]=await Promise.all([apiRequest("/api/v1/telegram/auto-signals"),apiRequest("/api/v1/telegram/status")]);
      if(bot.connected){$("tgBotDisplayName").value=bot.display_name||"";$("telegramStatus").textContent="Connected: "+(bot.display_name||("@"+bot.bot_username))+" · "+bot.chat_id;$("telegramMonitorTitle").textContent="Connected: "+(bot.display_name||("@"+bot.bot_username));$("telegramMonitorDescription").textContent="Your personal Telegram bot is connected. Turn on Auto Signals in Signal Lab to receive fresh BTC, ETH, SOL and optional Gold setups.";$("telegramMonitorPill").textContent=settings.enabled?"AUTO ON":"CONNECTED";}
      else {$("telegramStatus").textContent="No Telegram bot connected yet. Create one with @BotFather and connect it here.";$("telegramMonitorTitle").textContent="Telegram bot not connected";$("telegramMonitorDescription").textContent="Open Signal Lab to connect your BotFather bot. Manual crypto signals and enabled Auto Signals are delivered while the local QUANTNEX API is active.";$("telegramMonitorPill").textContent="OFFLINE";}
      $("autoSignalsEnabled").checked=!!settings.enabled;
      $("autoSignalInterval").value=String(settings.interval_seconds||180);
      document.querySelectorAll("input[name=autoSignalSymbol]").forEach(el=>{el.checked=(settings.symbols||["BTCUSDT","ETHUSDT","SOLUSDT"]).includes(el.value);});
      $("autoSignalStatus").textContent=settings.enabled?"Auto Signals ON · selected markets scan while the QUANTNEX API is running.":"Auto Signals OFF.";
    }catch(error){$("autoSignalStatus").textContent=error.message;}
  }
  $("saveAutoSignals")?.addEventListener("click",async()=>{
    const enabled=$("autoSignalsEnabled").checked;
    const interval_seconds=Number($("autoSignalInterval").value||180);
    const symbols=[...document.querySelectorAll('input[name="autoSignalSymbol"]:checked')].map(el=>el.value);
    if(!symbols.length){$("autoSignalStatus").textContent="Select at least one market.";return;}
    const button=$("saveAutoSignals");button.disabled=true;button.textContent="Saving…";
    try{
      const result=await apiRequest("/api/v1/telegram/auto-signals",{method:"PUT",body:JSON.stringify({enabled,interval_seconds,symbols})});
      $("autoSignalStatus").textContent=result.enabled?"Auto Signals ON · "+symbols.join(", ")+" · strict 8/10 minimum · every "+(interval_seconds/60)+" minute(s). Keep this computer and QUANTNEX API running.":"Auto Signals OFF. No automatic Telegram signals will be sent.";$("telegramMonitorPill").textContent=result.enabled?"AUTO ON":"CONNECTED";
    }catch(error){
      $("autoSignalsEnabled").checked=false;
      $("autoSignalStatus").textContent=error.message;
    }finally{button.disabled=false;button.textContent="Save Auto Signal settings";}
  });
  loadAutoSignalSettings();
})();
 
// QUANTNEX VIEW chart controller — first-party candles, live updates and local chart preferences.
(()=> {
 "use strict";
 const $=id=>document.getElementById(id),host=$("qxChartHost");if(!host)return;
 const API="http://127.0.0.1:8000",KEY="quantnex.view.settings.v1";
 const defaults={symbol:"BTCUSDT",interval:"15m",type:"candles",theme:"dark",volume:true,ema20:false,ema50:false,sma200:false,log:false,grid:true,up:"#20c997",down:"#f05d68"};
 let cfg={...defaults};try{cfg={...cfg,...JSON.parse(localStorage.getItem(KEY)||"{}")};}catch{}
 let chart=null,priceSeries=null,volumeSeries=null,indicators=[],bars=[],drawings=[],mode="cursor",firstPoint=null,observer=null;
 const secs={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400};
 const status=(m,bad=false)=>{const e=$("qxChartStatus");if(e){e.textContent=m;e.dataset.state=bad?"error":"ok";}};
 const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(cfg));}catch{}};
 const timeOf=v=>{if(typeof v==="number")return Math.floor(v);let t=String(v||"");if(/^\d{4}-\d{2}-\d{2} \d/.test(t))t=t.replace(" ","T")+"Z";const n=Date.parse(t);return Number.isFinite(n)?Math.floor(n/1000):NaN;};
 const clean=r=>({time:timeOf(r.time),open:+r.open,high:+r.high,low:+r.low,close:+r.close,volume:+(r.volume||0)});
 const ha=data=>{let prev=null;return data.map(c=>{const close=(c.open+c.high+c.low+c.close)/4,open=prev?(prev.open+prev.close)/2:(c.open+c.close)/2,x={time:c.time,open,high:Math.max(c.high,open,close),low:Math.min(c.low,open,close),close};prev=x;return x;});};
 const avg=(data,n,kind)=>{let sum=0,value=data[0]?.close||0,out=[],k=2/(n+1);data.forEach((c,i)=>{if(kind==="sma"){sum+=c.close;if(i>=n)sum-=data[i-n].close;if(i>=n-1)out.push({time:c.time,value:sum/n});}else{value=i===0?c.close:c.close*k+value*(1-k);if(i>=n-1)out.push({time:c.time,value});}});return out;};
 function removeDrawings(){drawings.forEach(d=>{try{if(d.kind==="price")priceSeries?.removePriceLine(d.line);else chart?.removeSeries(d.series);}catch{}});drawings=[];firstPoint=null;}
 function clearSeries(){if(!chart)return;removeDrawings();if(priceSeries){chart.removeSeries(priceSeries);priceSeries=null;}if(volumeSeries){chart.removeSeries(volumeSeries);volumeSeries=null;}indicators.forEach(x=>chart.removeSeries(x.series));indicators=[];}
 function updateHeader(price){if(!Number.isFinite(price))return;$("qxChartLastPrice").textContent="$"+price.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});const prev=bars.length>1?bars[bars.length-2].close:price,delta=prev?(price-prev)/prev*100:0;$("qxChartChange").textContent=(delta>=0?"+":"")+delta.toFixed(2)+"% vs previous candle";$("qxChartChange").className=delta>=0?"positive":"negative";}
 function render(){
  if(!chart||!bars.length)return;clearSeries();const L=window.LightweightCharts,data=cfg.type==="heikin"?ha(bars):bars,up=cfg.up,down=cfg.down;
  if(cfg.type==="line"){priceSeries=chart.addSeries(L.LineSeries,{color:"#5da9ff",lineWidth:2});priceSeries.setData(data.map(c=>({time:c.time,value:c.close})));}
  else if(cfg.type==="area"){priceSeries=chart.addSeries(L.AreaSeries,{lineColor:"#5da9ff",topColor:"rgba(93,169,255,.28)",bottomColor:"rgba(93,169,255,.015)",lineWidth:2});priceSeries.setData(data.map(c=>({time:c.time,value:c.close})));}
  else if(cfg.type==="bar"){priceSeries=chart.addSeries(L.BarSeries,{upColor:up,downColor:down,openVisible:true});priceSeries.setData(data);}
  else{priceSeries=chart.addSeries(L.CandlestickSeries,{upColor:up,downColor:down,borderVisible:false,wickUpColor:up,wickDownColor:down});priceSeries.setData(data);}
  if(cfg.volume){volumeSeries=chart.addSeries(L.HistogramSeries,{priceScaleId:"",priceFormat:{type:"volume"},lastValueVisible:false,priceLineVisible:false,base:0});volumeSeries.setData(bars.map(c=>({time:c.time,value:c.volume,color:c.close>=c.open?"rgba(32,201,151,.38)":"rgba(240,93,104,.38)"})));chart.priceScale("").applyOptions({scaleMargins:{top:.8,bottom:0}});}
  [["ema20",20,"#e8b44f","ema"],["ema50",50,"#a78bfa","ema"],["sma200",200,"#f08b5d","sma"]].forEach(([key,n,color,kind])=>{if(!cfg[key])return;const series=chart.addSeries(L.LineSeries,{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false});series.setData(avg(data,n,kind));indicators.push({series,n,kind});});
  chart.applyOptions({rightPriceScale:{mode:cfg.log?L.PriceScaleMode.Logarithmic:L.PriceScaleMode.Normal,scaleMargins:{top:.08,bottom:cfg.volume?.22:.08}}});updateHeader(bars[bars.length-1].close);
 }
 function draw(param){
  if(mode==="cursor"||!priceSeries||!param.point||!param.time)return;
  const price=priceSeries.coordinateToPrice(param.point.y);if(!Number.isFinite(price))return;
  if(mode==="horizontal"){const line=priceSeries.createPriceLine({price,color:"#e8bd55",lineWidth:1,lineStyle:2,axisLabelVisible:true,title:"Level"});drawings.push({kind:"price",line});status("Horizontal level added.");return;}
  if(mode==="trend"){if(!firstPoint){firstPoint={time:param.time,price};status("Trend line: click its second point.");return;}if(firstPoint.time===param.time){status("Choose a different candle for the second point.",true);return;}const pts=[firstPoint,{time:param.time,price}].sort((a,b)=>a.time-b.time),series=chart.addSeries(window.LightweightCharts.LineSeries,{color:"#e8bd55",lineWidth:2,priceLineVisible:false,lastValueVisible:false});series.setData(pts.map(p=>({time:p.time,value:p.price})));drawings.push({kind:"trend",series});firstPoint=null;status("Trend line added.");}
 }
 async function fetchChartCandles(){
  const localUrl=API+"/api/v1/charts/candles?symbol="+encodeURIComponent(cfg.symbol)+"&interval="+encodeURIComponent(cfg.interval)+"&limit=500";
  let localError=null;
  try{
   const response=await fetch(localUrl,{cache:"no-store",headers:{Accept:"application/json"}});
   const payload=await response.json().catch(()=>null);
   if(response.ok&&Array.isArray(payload?.candles)&&payload.candles.length)return payload;
   localError=new Error(payload?.detail||"Local chart API returned HTTP "+response.status+".");
   if(response.status>=400&&response.status<500&&response.status!==404)throw localError;
  }catch(error){localError=error;}
  if(["BTCUSDT","ETHUSDT","SOLUSDT"].includes(cfg.symbol)){
   try{
    const query=new URLSearchParams({symbol:cfg.symbol,interval:cfg.interval,limit:"500"});
    const response=await fetch("https://api.binance.com/api/v3/klines?"+query.toString(),{cache:"no-store",headers:{Accept:"application/json"}});
    if(!response.ok)throw new Error("Binance returned HTTP "+response.status+".");
    const rows=await response.json();
    if(!Array.isArray(rows)||!rows.length)throw new Error("Binance returned no candles.");
    const candles=rows.map(row=>({time:Math.floor(Number(row[0])/1000),open:Number(row[1]),high:Number(row[2]),low:Number(row[3]),close:Number(row[4]),volume:Number(row[5])}));
    return {symbol:cfg.symbol,interval:cfg.interval,provider:"Binance Spot · direct fallback",candles,count:candles.length};
   }catch(fallbackError){
    throw new Error("Could not load "+cfg.symbol+" candles. Local API: "+(localError?.message||"unavailable")+" Binance fallback: "+fallbackError.message);
   }
  }
  if(cfg.symbol==="XAUUSD"&&(localError?.message||"").toLowerCase().includes("not found")){
   throw new Error("Gold chart endpoint is missing from the local QUANTNEX API. Update/restart QUANTNEX and configure the Twelve Data key.");
  }
  throw localError||new Error("No market candle data is available.");
 }
 async function load(){
  status("Loading "+cfg.symbol+" "+cfg.interval+" candles…");
  if(!window.LightweightCharts){throw new Error("Chart engine could not load. Check your internet connection, then reload QUANTNEX VIEW.");}
  if(!chart)host.innerHTML='<div class="qx-chart-loading">Connecting to live market data…</div>';
  try{
   const body=await fetchChartCandles();
   bars=(body.candles||[]).map(clean).filter(c=>Number.isFinite(c.time)&&[c.open,c.high,c.low,c.close].every(Number.isFinite));if(!bars.length)throw new Error("The market provider returned no valid candles.");
   if(!chart){host.replaceChildren();const dark=cfg.theme==="dark";chart=window.LightweightCharts.createChart(host,{width:Math.max(320,host.clientWidth),height:Math.max(320,host.clientHeight||460),layout:{background:{type:"solid",color:dark?"#080d13":"#f7f9fc"},textColor:dark?"#cbd5e1":"#334155",fontFamily:"Inter,Arial,sans-serif",fontSize:11},grid:{vertLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"},horzLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"}},crosshair:{mode:window.LightweightCharts.CrosshairMode.Normal,vertLine:{color:"#8295ad",width:1,style:2},horzLine:{color:"#8295ad",width:1,style:2}},rightPriceScale:{borderColor:dark?"#263241":"#d8dee8"},timeScale:{borderColor:dark?"#263241":"#d8dee8",timeVisible:true,secondsVisible:false,rightOffset:8,barSpacing:7},handleScroll:{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:false},handleScale:{axisPressedMouseMove:true,mouseWheel:true,pinch:true}});chart.subscribeClick(draw);observer=new ResizeObserver(entries=>{const b=entries[0]?.contentRect;if(b&&chart)chart.applyOptions({width:Math.max(320,Math.floor(b.width)),height:Math.max(320,Math.floor(b.height))});});observer.observe(host);}
   const dark=cfg.theme==="dark";chart.applyOptions({layout:{background:{type:"solid",color:dark?"#080d13":"#f7f9fc"},textColor:dark?"#cbd5e1":"#334155"},grid:{vertLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"},horzLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"}}});
   render();chart.timeScale().fitContent();$("qxChartProvider").textContent=body.provider+" · "+bars.length+" candles · "+cfg.symbol;status("LIVE READY · "+cfg.symbol+" · "+cfg.interval);
  }catch(e){if(!chart){host.innerHTML='<div class="qx-chart-loading qx-chart-error"></div>';$("qxChartHost").firstElementChild.textContent=e.message;}status("Chart data unavailable",true);$("qxChartProvider").textContent=e.message;}
 }
 function tick(event){
  const d=event.detail||{};if(!chart||!priceSeries||String(d.symbol||"").toUpperCase()!==cfg.symbol||!bars.length)return;const price=Number(d.price),ms=Number(d.eventTime)||Date.now();if(!Number.isFinite(price)||price<=0)return;
  const seconds=secs[cfg.interval]||900,time=Math.floor(ms/1000/seconds)*seconds;let last=bars[bars.length-1];if(time<last.time)return;
  if(time>last.time){last={time,open:price,high:price,low:price,close:price,volume:0};bars.push(last);if(bars.length>1000)bars.shift();}else{last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;}
  if(d.kind==="trade"&&Number.isFinite(Number(d.volume)))last.volume+=Number(d.volume);
  const display=cfg.type==="heikin"?ha(bars):bars,point=display[display.length-1];if(cfg.type==="line"||cfg.type==="area")priceSeries.update({time:point.time,value:point.close});else priceSeries.update(point);
  if(volumeSeries)volumeSeries.update({time:last.time,value:last.volume||0,color:last.close>=last.open?"rgba(32,201,151,.38)":"rgba(240,93,104,.38)"});
  indicators.forEach(x=>{const vals=avg(display,x.n,x.kind),lastValue=vals[vals.length-1];if(lastValue)x.series.update(lastValue);});
  updateHeader(price);$("qxChartProvider").textContent=(d.source||"Market provider")+" · live tick · "+new Date(ms).toLocaleTimeString();
 }
 function setMode(value){mode=value;firstPoint=null;document.querySelectorAll("[data-qx-draw]").forEach(b=>b.classList.toggle("active",b.dataset.qxDraw===value));status(value==="cursor"?"Cursor mode":value==="horizontal"?"Click chart to add a horizontal level":"Click two candles to draw a trend line");}
 const controls={qxSymbol:"symbol",qxInterval:"interval",qxChartType:"type",qxChartTheme:"theme",qxVolume:"volume",qxEma20:"ema20",qxEma50:"ema50",qxSma200:"sma200",qxLogScale:"log",qxGrid:"grid",qxUpColor:"up",qxDownColor:"down"};
 Object.entries(controls).forEach(([id,key])=>{const el=$(id);if(!el)return;if(el.type==="checkbox")el.checked=!!cfg[key];else el.value=cfg[key];el.addEventListener("change",()=>{cfg[key]=el.type==="checkbox"?el.checked:el.value;save();if(key==="symbol"||key==="interval")load();else if(key==="theme"){chart?.remove();chart=null;priceSeries=null;volumeSeries=null;indicators=[];drawings=[];observer?.disconnect();observer=null;load();}else if(key==="type"||key==="volume"||key==="ema20"||key==="ema50"||key==="sma200"||key==="up"||key==="down")render();else if(chart){const dark=cfg.theme==="dark";chart.applyOptions({rightPriceScale:{mode:cfg.log?window.LightweightCharts.PriceScaleMode.Logarithmic:window.LightweightCharts.PriceScaleMode.Normal},grid:{vertLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"},horzLines:{color:cfg.grid?(dark?"rgba(148,163,184,.09)":"rgba(100,116,139,.13)"):"transparent"}}});}});});
 $("qxFitChart").addEventListener("click",()=>chart?.timeScale().fitContent());
 $("qxScreenshot").addEventListener("click",()=>{if(!chart)return;const canvas=chart.takeScreenshot(),a=document.createElement("a");a.href=canvas.toDataURL("image/png");a.download="quantnex-view-"+cfg.symbol+".png";a.click();});
 $("qxClearDrawings").addEventListener("click",()=>{removeDrawings();status("Chart drawings cleared.");});
 document.querySelectorAll("[data-qx-draw]").forEach(b=>b.addEventListener("click",()=>setMode(b.dataset.qxDraw)));
 window.addEventListener("quantnex:market-tick",tick);document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!bars.length)load();});
 load();
})();
