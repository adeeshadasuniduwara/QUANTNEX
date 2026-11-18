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
const status=(message,bad=false)=>{const node=$("bnStatus");node.textContent=message;node.className=bad?"p7-note p7-status-error":"p7-note";};
const busy=(button,on,label)=>{button.disabled=on;if(on)button.dataset.oldLabel=button.textContent;button.textContent=on?"Connecting…":(label||button.dataset.oldLabel||"");};
async function refresh(){
 try{
  const data=await request("/status");
  $("bnSpotState").textContent=data.spot_connected?"CONNECTED":"NOT CONNECTED";
  $("bnFuturesState").textContent=data.futures_connected?"CONNECTED":"NOT CONNECTED";
  $("bnSpotCredentialState").textContent=data.spot_connected?"Saved · encrypted":"Not connected";
  $("bnFuturesCredentialState").textContent=data.futures_connected?"Saved · encrypted":"Not connected";
  $("bnAutoState").textContent=data.auto_trading_enabled?"ON":"OFF";
  const r=data.risk||{};
  $("bnDailyTrades").value=r.max_trades_per_day??1;
  $("bnOpenTrades").value=r.max_open_trades??1;
  $("bnRiskPercent").value=r.risk_per_trade_percent??0.5;
  $("bnDailyLoss").value=r.max_daily_loss_percent??2;
  const cfg=data.auto_config||{};
  const setMulti=(id,values)=>{const el=$(id);if(el)Array.from(el.options).forEach(o=>o.selected=(values||[]).includes(o.value));};
  setMulti("bnMarketModes",cfg.market_modes||["SPOT","USD_M_FUTURES"]);
  setMulti("bnStrategies",cfg.strategies||["SCALPING","SWING"]);
  $("bnAutoDaily").value=cfg.max_trades_per_day??5;
  $("bnAutoOpen").value=cfg.max_open_positions??2;
  $("bnAutoLeverage").value=cfg.futures_leverage_cap??3;
  $("bnAutoDrawdown").value=cfg.max_total_drawdown_percent??5;
  $("bnAutoVolume").value=cfg.min_24h_quote_volume??10000000;
  $("bnAutoSpread").value=cfg.max_spread_bps??12;
  $("bnAutoDca").checked=cfg.dca_enabled===true;
  const checks=data.readiness?.checks||{};
  $("bnReadiness").textContent="Readiness · "+Object.entries(checks).map(([k,v])=>k.replaceAll("_"," ")+": "+(v?"PASS":"WAIT")).join(" · ");
  status("Binance DEMO testnet · "+(data.spot_connected&&data.futures_connected?"Both connections verified.":"Connect both demo environments to continue.")+" Auto Trading is "+(data.auto_trading_enabled?"ON":"OFF")+".");
 }catch(error){status("Local API unavailable: "+error.message,true);}
}
const connectExchange=async(exchange,formId,buttonId,keyId,secretId)=>{
 const form=$(formId),button=$(buttonId);busy(button,true);
 try{
  const data=await request("/connect/"+exchange,{method:"POST",body:JSON.stringify({
   api_key:$(keyId).value.trim(),api_secret:$(secretId).value.trim()
  })});
  form.reset();status(data.message);await refresh();
 }catch(error){status("Could not connect "+exchange+": "+error.message,true);}
 finally{busy(button,false,exchange==="spot"?"Verify & save Spot":"Verify & save Futures");}
};
$("bnSpotConnectForm").addEventListener("submit",event=>{event.preventDefault();connectExchange("spot","bnSpotConnectForm","bnSpotConnect","bnSpotKey","bnSpotSecret");});
$("bnFuturesConnectForm").addEventListener("submit",event=>{event.preventDefault();connectExchange("futures","bnFuturesConnectForm","bnFuturesConnect","bnFuturesKey","bnFuturesSecret");});
const testExchange=async exchange=>{
 try{const data=await request("/test/"+exchange,{method:"POST"});status(exchange.toUpperCase()+": "+(data.connected?"saved credentials verified":"not verified"+(data.reason? " · "+data.reason:"")),!data.connected);await refresh();}
 catch(error){status("Connection test failed: "+error.message,true);}
};
$("bnSpotTest").addEventListener("click",()=>testExchange("spot"));
$("bnFuturesTest").addEventListener("click",()=>testExchange("futures"));
const disconnectExchange=async exchange=>{
 if(!window.confirm("Remove only the saved Binance "+exchange.toUpperCase()+" Testnet credentials?"))return;
 try{await request("/connect/"+exchange,{method:"DELETE"});status(exchange.toUpperCase()+" credentials removed. The other exchange credentials are unchanged.");await refresh();}
 catch(error){status("Disconnect failed: "+error.message,true);}
};
$("bnSpotDisconnect").addEventListener("click",()=>disconnectExchange("spot"));
$("bnFuturesDisconnect").addEventListener("click",()=>disconnectExchange("futures"));
$("bnTest").addEventListener("click",async()=>{
 const spot=await request("/test/spot",{method:"POST"});
 const futures=await request("/test/futures",{method:"POST"});
 status("Spot: "+(spot.connected?"verified":"not configured/verified")+" · Futures: "+(futures.connected?"verified":"not configured/verified"));
 await refresh();
});
$("bnDisconnect").addEventListener("click",async()=>{
 if(!window.confirm("Remove BOTH saved Binance Testnet credential pairs?"))return;
 try{await request("/connect",{method:"DELETE"});status("Both Binance testnet connections disconnected.");await refresh();}
 catch(error){status("Disconnect failed: "+error.message,true);}
});
$("bnRiskForm").addEventListener("submit",async event=>{
 event.preventDefault();
 try{
  const data=await request("/risk",{method:"PUT",body:JSON.stringify({
   max_trades_per_day:Number($("bnDailyTrades").value),max_open_trades:Number($("bnOpenTrades").value),
   risk_per_trade_percent:Number($("bnRiskPercent").value),max_daily_loss_percent:Number($("bnDailyLoss").value)
  })});
  status("Risk limits saved. Daily trade cap: "+data.risk.max_trades_per_day+".");
 }catch(error){status("Could not save risk limits: "+error.message,true);}
});
$("bnTest").addEventListener("click",async()=>{
 try{const data=await request("/test",{method:"POST"});status("Spot: "+(data.results.spot.connected?"verified":"not verified")+" · Futures: "+(data.results.futures.connected?"verified":"not verified"));await refresh();}
 catch(error){status("Connection test failed: "+error.message,true);}
});
$("bnDisconnect").addEventListener("click",async()=>{
 try{await request("/connect",{method:"DELETE"});status("Both Binance testnet connections disconnected.");await refresh();}
 catch(error){status("Disconnect failed: "+error.message,true);}
});
$("bnAutoOff").addEventListener("click",async()=>{
 try{await request("/auto-trading",{method:"PUT",body:JSON.stringify({enabled:false})});status("Emergency stop confirmed · Auto Trading OFF.");await refresh();}
 catch(error){status("Could not confirm Auto OFF: "+error.message,true);}
});

$("bnAutoConfigForm").addEventListener("submit",async event=>{
 event.preventDefault();
 const selected=id=>Array.from($(id).selectedOptions).map(option=>option.value);
 try{
  const dca=$("bnAutoDca").checked;
  const payload={
   enabled:false,environment:"BINANCE_TESTNET",
   market_modes:selected("bnMarketModes"),strategies:selected("bnStrategies"),
   max_trades_per_day:Number($("bnAutoDaily").value),
   max_open_positions:Number($("bnAutoOpen").value),
   risk_per_trade_percent:0.5,max_daily_loss_percent:2,
   max_total_drawdown_percent:Number($("bnAutoDrawdown").value),
   futures_leverage_cap:Number($("bnAutoLeverage").value),futures_margin_type:"ISOLATED",
   dca_enabled:dca,dca_max_addons:dca?1:0,
   min_24h_quote_volume:Number($("bnAutoVolume").value),
   max_spread_bps:Number($("bnAutoSpread").value),
   min_reward_risk:1.5,max_signal_age_seconds:90
  };
  const saved=await request("/auto-config",{method:"PUT",body:JSON.stringify(payload)});
  status(saved.message);
  await refresh();
 }catch(error){status("Could not save autonomous policy: "+error.message,true);}
});

$("bnRefresh").addEventListener("click",refresh);
document.addEventListener("DOMContentLoaded",refresh);
refresh();
})();