(()=>{
"use strict";
const $=id=>document.getElementById(id);
const base="http://127.0.0.1:8000/api/v1/exchanges/binance";
const request=async(path,options={})=>{
 const response=await fetch(base+path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})},cache:"no-store"});
 const body=await response.json().catch(()=>null);
 if(!response.ok)throw new Error(body?.detail||"Request failed ("+response.status+").");
 return body;
};
const status=(message,bad=false)=>{
 const node=$("bnStatus");if(node){node.textContent=message;node.className=bad?"p7-note p7-status-error":"p7-note";}
};
const autoStatus=(message,bad=false)=>{
 const node=$("bnSpotAutoStatus");if(node){node.textContent=message;node.className=bad?"p7-note p7-status-error":"p7-note";}
};
const busy=(button,on,label)=>{if(!button)return;button.disabled=on;if(on)button.dataset.oldLabel=button.textContent;button.textContent=on?"Working…":(label||button.dataset.oldLabel||"");};
const setConfigForm=cfg=>{
 $("bnSpotSymbols").value=(cfg.symbols||["BTCUSDT","ETHUSDT","SOLUSDT"]).join(", ");
 $("bnSpotInterval").value=cfg.interval_seconds??30;
 $("bnSpotMinScore").value=cfg.min_score??8;
 $("bnSpotRisk").value=cfg.risk_per_trade_percent??0.5;
 $("bnSpotMaxOpen").value=cfg.max_open_trades??1;
 $("bnSpotMaxDaily").value=cfg.max_trades_per_day??3;
 $("bnSpotDailyLoss").value=cfg.max_daily_loss_percent??2;
 $("bnSpotSpread").value=cfg.max_spread_bps??12;
 $("bnSpotVolume").value=cfg.min_24h_quote_volume??10000000;
 $("bnSpotRR").value=cfg.min_reward_risk??1.5;
};
async function refresh(){
 try{
  const [data,spotConfig]=await Promise.all([request("/status"),request("/spot-auto-config")]);
  $("bnSpotState").textContent=data.spot_connected?"CONNECTED":"NOT CONNECTED";
  $("bnFuturesState").textContent=data.futures_connected?"CONNECTED":"NOT CONNECTED";
  $("bnSpotCredentialState").textContent=data.spot_connected?"Saved · encrypted":"Not connected";
  $("bnFuturesCredentialState").textContent=data.futures_connected?"Saved · encrypted":"Not connected";
  $("bnAutoState").textContent=data.auto_trading_enabled?"ON · SPOT DEMO":"OFF";
  $("bnExecutionState").textContent="SPOT DEMO · OCO";
  const worker=data.spot_worker||{};
  $("bnReadiness").textContent="Spot worker: "+(worker.running?"RUNNING":"STOPPED")+" · Open demo positions: "+(data.spot_open_trades??0)+" · Last cycle: "+(worker.last_cycle||"waiting")+(worker.last_error?" · Last error: "+worker.last_error:"");
  setConfigForm(spotConfig.config||{});
  $("bnSpotAutoToggle").textContent=data.auto_trading_enabled?"Stop Spot Demo Auto Trading":"Start Spot Demo Auto Trading";
  $("bnSpotAutoToggle").dataset.enabled=data.auto_trading_enabled?"true":"false";
  const r=data.risk||{};
  $("bnDailyTrades").value=r.max_trades_per_day??1;
  $("bnOpenTrades").value=r.max_open_trades??1;
  $("bnRiskPercent").value=r.risk_per_trade_percent??0.5;
  $("bnDailyLoss").value=r.max_daily_loss_percent??2;
  status("Binance Demo · Spot "+(data.spot_connected?"connected":"not connected")+" · Futures "+(data.futures_connected?"connected":"not connected")+" · Spot Auto Trading "+(data.auto_trading_enabled?"ON":"OFF")+".");
  autoStatus(data.auto_trading_enabled?"Auto Trading is ON. New entries are Spot BUY-only; exchange OCO protection remains active for existing positions.":"Auto Trading is OFF. Saving settings does not place orders.");
 }catch(error){status("Local API unavailable: "+error.message,true);autoStatus("Could not load Spot Auto Trading status: "+error.message,true);}
}
const connectExchange=async(exchange,formId,buttonId,keyId,secretId)=>{
 const form=$(formId),button=$(buttonId);busy(button,true);
 try{
  const data=await request("/connect/"+exchange,{method:"POST",body:JSON.stringify({
   api_key:$(keyId).value.trim(),api_secret:$(secretId).value.trim()
  })});
  form.reset();status(data.message+(exchange==="spot"?(data.can_trade?" · Spot trading permission enabled.":" · Spot trade permission is OFF; enable it in Binance Demo API management before starting."):""));await refresh();
 }catch(error){status("Could not connect "+exchange+": "+error.message,true);}
 finally{busy(button,false,exchange==="spot"?"Verify & save Spot":"Verify & save Futures");}
};
$("bnSpotConnectForm").addEventListener("submit",event=>{event.preventDefault();connectExchange("spot","bnSpotConnectForm","bnSpotConnect","bnSpotKey","bnSpotSecret");});
$("bnFuturesConnectForm").addEventListener("submit",event=>{event.preventDefault();connectExchange("futures","bnFuturesConnectForm","bnFuturesConnect","bnFuturesKey","bnFuturesSecret");});
const testExchange=async exchange=>{
 try{const data=await request("/test/"+exchange,{method:"POST"});status(exchange.toUpperCase()+": "+(data.connected?(data.can_trade?"credentials verified · trading permission enabled":"credentials verified · trading permission is OFF"):"not verified"+(data.reason?" · "+data.reason:"")),!data.connected||!data.can_trade);await refresh();}
 catch(error){status("Connection test failed: "+error.message,true);}
};
$("bnSpotTest").addEventListener("click",()=>testExchange("spot"));
$("bnFuturesTest").addEventListener("click",()=>testExchange("futures"));
const disconnectExchange=async exchange=>{
 if(!window.confirm("Remove only the saved Binance "+exchange.toUpperCase()+" Demo Trading credentials?"))return;
 try{await request("/connect/"+exchange,{method:"DELETE"});status(exchange.toUpperCase()+" credentials removed. The other exchange credentials are unchanged.");await refresh();}
 catch(error){status("Disconnect failed: "+error.message,true);}
};
$("bnSpotDisconnect").addEventListener("click",()=>disconnectExchange("spot"));
$("bnFuturesDisconnect").addEventListener("click",()=>disconnectExchange("futures"));
const stopAuto=async()=>{
 try{const d=await request("/spot-auto-trading",{method:"PUT",body:JSON.stringify({enabled:false})});autoStatus(d.message);await refresh();}
 catch(error){autoStatus("Could not confirm emergency stop: "+error.message,true);}
};
$("bnAutoOff").addEventListener("click",stopAuto);
$("bnSpotAutoConfigForm").addEventListener("submit",async event=>{
 event.preventDefault();const button=$("bnSpotAutoSave");busy(button,true);
 try{
  const symbols=$("bnSpotSymbols").value.split(",").map(x=>x.trim().toUpperCase()).filter(Boolean);
  const payload={symbols,interval_seconds:Number($("bnSpotInterval").value),min_score:Number($("bnSpotMinScore").value),
   risk_per_trade_percent:Number($("bnSpotRisk").value),max_open_trades:Number($("bnSpotMaxOpen").value),
   max_trades_per_day:Number($("bnSpotMaxDaily").value),max_daily_loss_percent:Number($("bnSpotDailyLoss").value),
   max_spread_bps:Number($("bnSpotSpread").value),min_24h_quote_volume:Number($("bnSpotVolume").value),
   min_reward_risk:Number($("bnSpotRR").value)};
  const d=await request("/spot-auto-config",{method:"PUT",body:JSON.stringify(payload)});
  autoStatus(d.message);await refresh();
 }catch(error){autoStatus("Could not save Spot Auto settings: "+error.message,true);}
 finally{busy(button,false,"Save Spot Auto settings");}
});
$("bnSpotAutoToggle").addEventListener("click",async()=>{
 const enabled=$("bnSpotAutoToggle").dataset.enabled!=="true";
 if(enabled&&!window.confirm("Start Binance Spot DEMO Auto Trading? This can place BUY orders in your demo wallet and attach OCO exits."))return;
 const button=$("bnSpotAutoToggle");busy(button,true);
 try{const d=await request("/spot-auto-trading",{method:"PUT",body:JSON.stringify({enabled})});autoStatus(d.message);await refresh();}
 catch(error){autoStatus("Auto Trading change rejected: "+error.message,true);await refresh();}
 finally{busy(button,false);}
});
$("bnRiskForm").addEventListener("submit",async event=>{
 event.preventDefault();
 try{
  const risk={max_trades_per_day:Number($("bnDailyTrades").value),max_open_trades:Number($("bnOpenTrades").value),
   risk_per_trade_percent:Number($("bnRiskPercent").value),max_daily_loss_percent:Number($("bnDailyLoss").value)};
  await request("/risk",{method:"PUT",body:JSON.stringify(risk)});status("Risk limits saved.");
 }catch(error){status("Could not save risk limits: "+error.message,true);}
});
$("bnRefresh").addEventListener("click",refresh);
document.addEventListener("DOMContentLoaded",refresh);
refresh();
})();