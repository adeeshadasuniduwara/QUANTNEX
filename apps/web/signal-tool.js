(() => {
  const $ = (id) => document.getElementById(id);
  const ids = ["side","entry","stopLoss","tp1","tp2","tp3","equity","riskPct","usdPerDollarMove"];
  const money = (v) => "$" + Math.abs(v).toFixed(2);
  const num = (id) => Number($(id).value);
  let currentPlan = null;
  function readPlan() {
    const p = {side:$("side").value,entry:num("entry"),sl:num("stopLoss"),t1:num("tp1"),t2:num("tp2"),t3:num("tp3"),equity:num("equity"),risk:num("riskPct"),value:num("usdPerDollarMove")};
    if (![p.entry,p.sl,p.t1,p.t2,p.t3,p.equity,p.risk,p.value].every(Number.isFinite) || [p.entry,p.sl,p.t1,p.t2,p.t3,p.equity,p.risk,p.value].some(v=>v<=0) || p.risk>5) return null;
    if (p.side==="BUY" ? !(p.sl<p.entry && p.entry<p.t1 && p.t1<p.t2 && p.t2<p.t3) : !(p.t3<p.t2 && p.t2<p.t1 && p.t1<p.entry && p.entry<p.sl)) return null;
    return p;
  }
  function render() {
    const p=readPlan(), status=$("signalCalcStatus"), result=$("positionSummary");
    if(!p){status.textContent="Check prices: BUY needs SL < Entry < TP1 < TP2 < TP3; SELL needs TP3 < TP2 < TP1 < Entry < SL.";result.textContent="Enter a valid setup."; $("riskRewardVisual").hidden=true;currentPlan=null;return;}
    currentPlan=p;
    const riskDistance=Math.abs(p.entry-p.sl), riskCash=p.equity*p.risk/100;
    const lots=riskCash/(riskDistance*p.value), rrs=[p.t1,p.t2,p.t3].map(t=>Math.abs(t-p.entry)/riskDistance);
    const stopPct=Math.max(12,Math.min(42,100*riskDistance/(riskDistance+Math.abs(p.t3-p.entry))));
    $("riskRewardVisual").hidden=false;$("lossZone").style.flex="0 0 "+stopPct+"%";$("profitZone").style.flex="1";
    $("lossZone").textContent="LOSS / SL "+p.sl.toFixed(2);
    $("profitZone").textContent="PROFIT / TP1 "+p.t1.toFixed(2)+" · TP2 "+p.t2.toFixed(2)+" · TP3 "+p.t3.toFixed(2);
    $("entryMarker").textContent="ENTRY "+p.entry.toFixed(2);
    result.replaceChildren();
    [["Risk amount",money(riskCash)],["Estimated size",lots.toFixed(3)+" lots"],["TP1 R:R","1:"+rrs[0].toFixed(2)],["TP2 R:R","1:"+rrs[1].toFixed(2)],["TP3 R:R","1:"+rrs[2].toFixed(2)]].forEach(([a,b])=>{const d=document.createElement("div");d.className="position-stat";const s=document.createElement("span"),v=document.createElement("strong");s.textContent=a;v.textContent=b;d.append(s,v);result.append(d);});
    status.textContent="Risk calculation ready. Confirm broker contract size and tick value before placing any trade.";
  }
  ids.forEach(id=>$(id).addEventListener("input",render));$("side").addEventListener("change",render);
  async function sendTelegram(message){
    const token=$("tgBotToken").value.trim(),chat=$("tgChatId").value.trim(),api=($("apiBase")?.value||"http://127.0.0.1:8000").trim().replace(/\/+$/,"");
    if(!token||!chat)throw new Error("Enter your Telegram bot token and chat ID.");
    const headers={"Content-Type":"application/json"},session=sessionStorage.getItem("quantnex.sessionToken.v1");if(session)headers.Authorization="Bearer "+session;
    const response=await fetch(api+"/api/v1/telegram/send",{method:"POST",headers,body:JSON.stringify({bot_token:token,chat_id:chat,message})});
    const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||"Telegram API request failed.");return data;
  }
  function planMessage(p){const lots=(p.equity*p.risk/100)/(Math.abs(p.entry-p.sl)*p.value);return ["QUANTNEX · XAUUSD TRADE PLAN","Side: "+p.side,"Entry: "+p.entry,"Stop Loss: "+p.sl,"TP1: "+p.t1,"TP2: "+p.t2,"TP3: "+p.t3,"Risk: "+p.risk+"% ($"+(p.equity*p.risk/100).toFixed(2)+")","Estimated size: "+lots.toFixed(3)+" lots","TP1 reached: review moving SL to breakeven at "+p.entry+".","Manual plan only; no order was placed."].join("\n");}
  $("sendPlanTelegram").addEventListener("click",async()=>{if(!currentPlan)render();if(!currentPlan)return;const b=$("sendPlanTelegram");b.disabled=true;try{await sendTelegram(planMessage(currentPlan));$("telegramStatus").textContent="Trade plan sent to Telegram.";}catch(e){$("telegramStatus").textContent=e.message;}finally{b.disabled=false;}});
  $("testTelegram").addEventListener("click",async()=>{const b=$("testTelegram");b.disabled=true;try{await sendTelegram("QUANTNEX Telegram connection test successful.");$("telegramStatus").textContent="Telegram test message sent.";}catch(e){$("telegramStatus").textContent=e.message;}finally{b.disabled=false;}});
  $("tp1Breakeven").addEventListener("click",async()=>{if(!currentPlan)render();if(!currentPlan)return;const p=currentPlan;try{await sendTelegram("⚠️ QUANTNEX · TP1 MANUALLY CONFIRMED\nXAUUSD "+p.side+" · TP1 "+p.t1+"\nSuggested action: move SL to breakeven (Entry "+p.entry+"). Verify your broker position and move SL manually. QUANTNEX did not change any order.");$("telegramStatus").textContent="TP1 warning sent. Move SL manually in your broker app.";}catch(e){$("telegramStatus").textContent=e.message;}});
  $("clearTelegram").addEventListener("click",()=>{$("tgBotToken").value="";$("tgChatId").value="";$("telegramStatus").textContent="Bot token and chat ID cleared from this form; not saved by this page.";});
  $("openBotGuide").addEventListener("click",()=>{$("telegramGuide").hidden=!$("telegramGuide").hidden;});
  render();

  const tfKey="quantnex.signal.timeframes.v1";
  const tfNames={"1":"M1","5":"M5","15":"M15","30":"M30","60":"H1","50":"M50"};
  function readTfSettings(){
    let saved={};try{saved=JSON.parse(localStorage.getItem(tfKey)||"{}")||{};}catch{}
    const primary=$("primarySignalTf"),trend=$("trendSignalTf"),chart=$("chartSignalTf");
    if(saved.primary)primary.value=saved.primary;if(saved.trend)trend.value=saved.trend;if(saved.chart)chart.value=saved.chart;
    document.querySelectorAll('input[name="analysisTf"]').forEach(el=>{el.checked=Array.isArray(saved.enabled)?saved.enabled.includes(el.value):true;});
  }
  function saveTfSettings(){
    const enabled=[...document.querySelectorAll('input[name="analysisTf"]:checked')].map(el=>el.value);
    const settings={primary:$("primarySignalTf").value,trend:$("trendSignalTf").value,chart:$("chartSignalTf").value,enabled};
    if(!enabled.length){$("timeframeStatus").textContent="Select at least one analysis timeframe.";return null;}
    localStorage.setItem(tfKey,JSON.stringify(settings));
    $("timeframeStatus").textContent="Saved locally · Primary "+tfNames[settings.primary]+" · Trend "+tfNames[settings.trend]+" · Analysis "+enabled.map(v=>tfNames[v]).join(", ")+". This config does not activate signal generation until a market-data engine is connected.";
    return settings;
  }
  function applyChartTimeframe(){
    const settings=saveTfSettings();if(!settings)return;
    if(settings.chart==="50"){$("timeframeStatus").textContent="M50 is a custom interval and is not reliably supported by the TradingView embed. Keep M50 for future aggregated analysis; choose M1, M5, M15, M30 or H1 for the chart.";return;}
    const host=$("xauTradingView");if(!host)return;
    host.replaceChildren();
    const widget=document.createElement("div");widget.className="tradingview-widget-container__widget";host.append(widget);
    const script=document.createElement("script");script.type="text/javascript";script.async=true;script.src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.text=JSON.stringify({autosize:true,symbol:"OANDA:XAUUSD",interval:settings.chart,timezone:"Etc/UTC",theme:"dark",style:"1",locale:"en",allow_symbol_change:true,calendar:false,support_host:"https://www.tradingview.com"});
    host.append(script);
    $("timeframeStatus").textContent="XAUUSD TradingView chart set to "+tfNames[settings.chart]+". Analysis timeframe preferences saved locally.";
  }
  $("saveTimeframes").addEventListener("click",saveTfSettings);
  $("applyChartTf").addEventListener("click",applyChartTimeframe);
  readTfSettings();

})();