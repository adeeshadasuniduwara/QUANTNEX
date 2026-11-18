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
  $("bnAutoState").textContent=data.auto_trading_enabled?"ON":"OFF";
  const r=data.risk||{};
  $("bnDailyTrades").value=r.max_trades_per_day??1;
  $("bnOpenTrades").value=r.max_open_trades??1;
  $("bnRiskPercent").value=r.risk_per_trade_percent??0.5;
  $("bnDailyLoss").value=r.max_daily_loss_percent??2;
  status("Binance DEMO testnet · "+(data.spot_connected&&data.futures_connected?"Both connections verified.":"Connect both demo environments to continue.")+" Auto Trading is "+(data.auto_trading_enabled?"ON":"OFF")+".");
 }catch(error){status("Local API unavailable: "+error.message,true);}
}
$("bnConnectForm").addEventListener("submit",async event=>{
 event.preventDefault();const button=$("bnConnect");busy(button,true);
 try{
  const data=await request("/connect",{method:"POST",body:JSON.stringify({
   spot_api_key:$("bnSpotKey").value.trim(),spot_api_secret:$("bnSpotSecret").value.trim(),
   futures_api_key:$("bnFuturesKey").value.trim(),futures_api_secret:$("bnFuturesSecret").value.trim()
  })});
  $("bnConnectForm").reset();status(data.message);await refresh();
 }catch(error){status("Connection failed: "+error.message,true);}
 finally{busy(button,false,"Verify & connect both testnets");}
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
$("bnRefresh").addEventListener("click",refresh);
document.addEventListener("DOMContentLoaded",refresh);
refresh();
})();