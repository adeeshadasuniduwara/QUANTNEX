(() => {
"use strict";
const $=id=>document.getElementById(id),host=$("qxChartHost");
if(!host||typeof apiRequest!=="function")return;
let chart=null,series=null,volume=null,emaLines={},overlay=null,ctx=null,candles=[],analysis=null,busy=false,observer=null,tradeLines=[],markerApi=null;
const palette={bull:"#22c997",bear:"#f05d68",fvg:"#4a9cff",ob:"#c18cff",breaker:"#f4b860",sr:"#e6c85c"};
const stamp=v=>{let s=String(v||"");if(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?$/.test(s))s+="Z";let n=Date.parse(s);return Number.isFinite(n)?Math.floor(n/1000):null;};
const fmt=v=>Number(v).toLocaleString(undefined,{maximumFractionDigits:8});
const selected=()=>({symbol:$("qxSymbol")?.value||"BTCUSDT",interval:$("qxInterval")?.value||"15m"});
function setStatus(message,state=""){const el=$("qxChartStatus");if(el){el.textContent=message;el.dataset.state=state;}const tag=$("qxChartIntelState");if(tag)tag.textContent=state==="error"?"FEED ERROR":message.includes("CONFIRMED")?"CONFIRMED":message.includes("WAITING")?"SCANNING":"LOADING";}
function ema(values,p){if(!values.length)return[];const a=2/(p+1),out=[values[0]];for(let i=1;i<values.length;i++)out.push(a*values[i]+(1-a)*out[i-1]);return out;}
function makeChart(){
 const L=window.LightweightCharts;if(!L?.createChart)throw Error("Chart library unavailable. Check internet connection.");
 host.replaceChildren();markerApi=null;chart=L.createChart(host,{width:host.clientWidth||800,height:host.clientHeight||470,
  layout:{background:{type:"solid",color:$("qxChartTheme")?.value==="light"?"#f7f9fc":"#080d13"},textColor:$("qxChartTheme")?.value==="light"?"#263244":"#b8c4d4",fontFamily:"Inter,system-ui,sans-serif",fontSize:11},
  grid:{vertLines:{color:$("qxGrid")?.checked?"rgba(130,150,175,.10)":"transparent"},horzLines:{color:$("qxGrid")?.checked?"rgba(130,150,175,.10)":"transparent"}},
  rightPriceScale:{borderColor:"rgba(130,150,175,.22)",mode:$("qxLogScale")?.checked?L.PriceScaleMode?.Logarithmic:L.PriceScaleMode?.Normal},
  timeScale:{borderColor:"rgba(130,150,175,.22)",timeVisible:true,rightOffset:8},crosshair:{mode:L.CrosshairMode?.Normal}});
 const type=$("qxChartType")?.value||"candles",common={priceLineVisible:true,lastValueVisible:true};
 if(type==="line")series=chart.addSeries(L.LineSeries,{...common,color:"#63a9ff",lineWidth:2});
 else if(type==="area")series=chart.addSeries(L.AreaSeries,{...common,lineColor:"#63a9ff",topColor:"rgba(99,169,255,.30)",bottomColor:"rgba(99,169,255,.02)"});
 else if(type==="bar")series=chart.addSeries(L.BarSeries,{...common,upColor:$("qxUpColor")?.value||palette.bull,downColor:$("qxDownColor")?.value||palette.bear});
 else series=chart.addSeries(L.CandlestickSeries,{...common,upColor:$("qxUpColor")?.value||palette.bull,downColor:$("qxDownColor")?.value||palette.bear,borderUpColor:$("qxUpColor")?.value||palette.bull,borderDownColor:$("qxDownColor")?.value||palette.bear,wickUpColor:$("qxUpColor")?.value||palette.bull,wickDownColor:$("qxDownColor")?.value||palette.bear});
 volume=null;emaLines={};
 if($("qxVolume")?.checked&&L.HistogramSeries){volume=chart.addSeries(L.HistogramSeries,{priceScaleId:"volume",priceFormat:{type:"volume"},priceLineVisible:false,lastValueVisible:false,base:0});chart.priceScale("volume").applyOptions({scaleMargins:{top:.82,bottom:0},visible:false});}
 [["20","qxEma20","#f3c969"],["50","qxEma50","#67a7ff"],["200","qxEma200","#c18cff"]].forEach(([p,id,color])=>{if($(id)?.checked)emaLines[p]=chart.addSeries(L.LineSeries,{color,lineWidth:1,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});});
 overlay=document.createElement("canvas");overlay.className="qx-intelligence-overlay";overlay.setAttribute("aria-hidden","true");host.append(overlay);ctx=overlay.getContext("2d");
 chart.timeScale().subscribeVisibleLogicalRangeChange(drawOverlay);chart.timeScale().subscribeVisibleTimeRangeChange(drawOverlay);
 observer?.disconnect();observer=new ResizeObserver(entries=>{let r=entries[0]?.contentRect;if(r&&chart){chart.applyOptions({width:Math.max(280,Math.floor(r.width)),height:Math.max(320,Math.floor(r.height))});drawOverlay();}});observer.observe(host);
}
function applyCandles(rows){
 candles=(rows||[]).map(r=>({...r,time:stamp(r.time)})).filter(r=>r.time!==null).sort((a,b)=>a.time-b.time).filter((r,i,a)=>i===0||r.time>a[i-1].time);
 if(!candles.length)throw Error("No valid candles returned.");
 const type=$("qxChartType")?.value||"candles";
 let chartRows=candles;
 if(type==="heikin"){let prevOpen=null,prevClose=null;chartRows=candles.map(c=>{const close=(c.open+c.high+c.low+c.close)/4,open=prevOpen===null?(c.open+c.close)/2:(prevOpen+prevClose)/2;const row={time:c.time,open,high:Math.max(c.high,open,close),low:Math.min(c.low,open,close),close};prevOpen=open;prevClose=close;return row;});}
 series.setData(candles.map((c,i)=>type==="line"||type==="area"?{time:c.time,value:c.close}:chartRows[i]));
 if(volume)volume.setData(candles.map(c=>({time:c.time,value:Number(c.volume||0),color:c.close>=c.open?"rgba(34,201,151,.42)":"rgba(240,93,104,.42)"})));
 Object.entries(emaLines).forEach(([p,line])=>{let values=ema(candles.map(c=>c.close),Number(p));line.setData(candles.map((c,i)=>({time:c.time,value:values[i]})));});
 chart.timeScale().fitContent();const last=candles.at(-1),first=candles[0],change=first.close?100*(last.close-first.close)/first.close:0;
 if($("qxChartLastPrice"))$("qxChartLastPrice").textContent=fmt(last.close);
 if($("qxChartChange")){$("qxChartChange").textContent=(change>=0?"+":"")+change.toFixed(2)+"% across loaded candles";$("qxChartChange").dataset.direction=change>=0?"up":"down";}
 drawOverlay();
}
function drawOverlay(){
 if(!overlay||!chart||!candles.length||!ctx)return;
 const r=host.getBoundingClientRect(),d=window.devicePixelRatio||1;overlay.width=Math.max(1,Math.floor(r.width*d));overlay.height=Math.max(1,Math.floor(r.height*d));overlay.style.width=r.width+"px";overlay.style.height=r.height+"px";
 ctx.setTransform(d,0,0,d,0,0);ctx.clearRect(0,0,r.width,r.height);
 const st=analysis?.features?.structure;if(!st)return;const ts=chart.timeScale(),first=ts.timeToCoordinate(candles[Math.max(0,candles.length-55)].time),left=Math.max(0,first??0),right=Math.max(0,r.width-58);
 const zone=(label,z,color,fill)=>{if(!z||!Number.isFinite(Number(z.low))||!Number.isFinite(Number(z.high)))return;const y1=series.priceToCoordinate(Number(z.high)),y2=series.priceToCoordinate(Number(z.low));if(y1===null||y2===null)return;const y=Math.min(y1,y2),h=Math.max(2,Math.abs(y2-y));ctx.fillStyle=fill;ctx.strokeStyle=color;ctx.lineWidth=1;ctx.fillRect(left,y,right-left,h);ctx.strokeRect(left,y,right-left,h);ctx.fillStyle=color;ctx.font="10px Inter,system-ui,sans-serif";ctx.fillText(label,left+5,Math.max(11,y-4));};
 const line=(label,v,color)=>{if(!Number.isFinite(Number(v)))return;const y=series.priceToCoordinate(Number(v));if(y===null)return;ctx.strokeStyle=color;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle=color;ctx.font="10px Inter,system-ui,sans-serif";ctx.fillText(label+" "+fmt(v),left+5,Math.max(11,y-4));};
 if($("qxOverlayZones")?.checked!==false){zone("BULL FVG",st.bullish_fvg,palette.fvg,"rgba(74,156,255,.13)");zone("BEAR FVG",st.bearish_fvg,palette.fvg,"rgba(74,156,255,.10)");zone("BULL OB",st.bullish_order_block,palette.ob,"rgba(193,140,255,.15)");zone("BEAR OB",st.bearish_order_block,palette.ob,"rgba(193,140,255,.12)");zone("BULL BREAKER",st.bullish_breaker_block,palette.breaker,"rgba(244,184,96,.14)");zone("BEAR BREAKER",st.bearish_breaker_block,palette.breaker,"rgba(244,184,96,.11)");zone("BULL IFVG",st.bullish_ifvg,palette.bear,"rgba(240,93,104,.12)");zone("BEAR IFVG",st.bearish_ifvg,palette.bear,"rgba(240,93,104,.10)");}
 if($("qxOverlaySR")?.checked!==false){zone("RESISTANCE ZONE",st.resistance_zone,palette.sr,"rgba(230,200,92,.12)");zone("SUPPORT ZONE",st.support_zone,palette.sr,"rgba(230,200,92,.12)");line("SWING HIGH",st.swing_high,"rgba(230,200,92,.72)");line("SWING LOW",st.swing_low,"rgba(230,200,92,.72)");line("EQUILIBRIUM",st.equilibrium,"rgba(190,198,210,.7)");}
 if($("qxOverlayStructure")?.checked!==false){const last=candles.at(-1),x=ts.timeToCoordinate(last.time),y=series.priceToCoordinate(last.close),labels=[st.structure_event&&st.structure_event!=="NONE"?st.structure_event.replace("_"," "):"",st.liquidity_sweep!=="NONE"?"LIQUIDITY SWEEP "+st.liquidity_sweep:""].filter(Boolean).join(" · ");if(labels&&x!==null&&y!==null){ctx.fillStyle="#e9edf5";ctx.font="600 10px Inter,system-ui,sans-serif";ctx.fillText(labels,Math.max(6,x-155),Math.max(14,y-17));}}
}
window.quantnexViewSetTradePlan=function(plan){
 if(!series)return;
 tradeLines.forEach(line=>{try{series.removePriceLine(line);}catch{}});
 tradeLines=[];
 if(!plan)return;
 const levels=[
  ["ENTRY",plan.entry,"#e6c85c"],
  ["STOP LOSS",plan.stop_loss,"#f05d68"],
  ["TP1",plan.tp1,"#22c997"],["TP2",plan.tp2,"#22c997"],["TP3",plan.tp3,"#22c997"]
 ];
 levels.forEach(([title,value,color])=>{
  if(!Number.isFinite(Number(value)))return;
  tradeLines.push(series.createPriceLine({price:Number(value),color,lineWidth:title==="ENTRY"?2:1,
   lineStyle:title==="ENTRY"?0:2,axisLabelVisible:true,title}));
 });
 drawOverlay();
};
function renderAnalysis(data){
 analysis=data;const f=data.features||{},st=f.structure||{},summary=$("qxChartIntelSummary");
 if(summary){const s=data.signal;summary.textContent=s?s.side+" · Entry "+fmt(s.entry)+" · SL "+fmt(s.stop_loss)+" · TP1 "+fmt(s.tp1)+" / TP2 "+fmt(s.tp2)+" / TP3 "+fmt(s.tp3):"WAITING FOR CONFIRMATION · "+data.confluence_score+"/"+data.score_out_of+" confluence. No trade plan is active.";}
 const metrics=$("qxChartIntelMetrics");if(metrics){metrics.replaceChildren();[["RSI",Number(f.rsi).toFixed(1)],["ADX",Number(f.adx).toFixed(1)],["EMA 20",fmt(f.ema20)],["EMA 50",fmt(f.ema50)],["EMA 200",fmt(f.ema200)],["Structure",st.structure_event||st.bos_mss||"—"],["Trend",st.structure_trend||"—"],["Liquidity",st.liquidity_sweep||"—"],["Premium / Discount",st.premium_discount||"—"]].forEach(([a,b])=>{let d=document.createElement("div"),n=document.createElement("span"),v=document.createElement("strong");d.className="qx-chart-intel-metric";n.textContent=a;v.textContent=b;d.append(n,v);metrics.append(d);});}
 if(series&&window.LightweightCharts?.createSeriesMarkers){const marks=data.signal?[{time:candles.at(-1).time,position:data.signal.side==="BUY"?"belowBar":"aboveBar",color:data.signal.side==="BUY"?palette.bull:palette.bear,shape:data.signal.side==="BUY"?"arrowUp":"arrowDown",text:data.signal.side+" · "+data.signal.timeframe}]:[];if(markerApi)markerApi.setMarkers(marks);else markerApi=window.LightweightCharts.createSeriesMarkers(series,marks);}
 if(window.quantnexViewSetTradePlan)window.quantnexViewSetTradePlan(data.signal||null);drawOverlay();
}
async function refresh(){
 if(busy)return;busy=true;const pick=selected();
 try{
  setStatus("LOADING "+pick.symbol+" · "+pick.interval.toUpperCase());
  const [bars,scan]=await Promise.all([apiRequest("/api/v1/charts/candles?symbol="+encodeURIComponent(pick.symbol)+"&interval="+encodeURIComponent(pick.interval)+"&limit=500"),apiRequest("/api/v1/quantnex-view/analyze?symbol="+encodeURIComponent(pick.symbol)+"&interval="+encodeURIComponent(pick.interval)+"&min_score=7")]);
  const now=selected();if(now.symbol!==pick.symbol||now.interval!==pick.interval)return;
  if(!chart)makeChart();applyCandles(bars.candles);const p=$("qxChartProvider");if(p)p.textContent="Feed: "+bars.provider+" · "+bars.count+" candles · "+new Date(bars.timestamp).toLocaleTimeString();
  renderAnalysis(scan);setStatus(scan.signal?"CONFIRMED SETUP · "+scan.signal.side:"WAITING FOR CONFIRMATION · SCANNING");
 }catch(e){setStatus("FEED / ANALYSIS ERROR","error");const p=$("qxChartProvider");if(p)p.textContent=e.message;const s=$("qxChartIntelSummary");if(s)s.textContent="Analysis unavailable. "+e.message;}
 finally{busy=false;}
}
function rebuild(){if(!candles.length){refresh();return;}const old=candles;makeChart();applyCandles(old);if(analysis)renderAnalysis(analysis);}
["qxSymbol","qxInterval"].forEach(id=>$(id)?.addEventListener("change",refresh));
["qxChartType","qxChartTheme","qxVolume","qxEma20","qxEma50","qxEma200","qxLogScale","qxGrid","qxUpColor","qxDownColor"].forEach(id=>$(id)?.addEventListener("change",rebuild));
["qxOverlayStructure","qxOverlayZones","qxOverlaySR"].forEach(id=>$(id)?.addEventListener("change",drawOverlay));
$("qxFitChart")?.addEventListener("click",()=>chart?.timeScale().fitContent());
$("qxScreenshot")?.addEventListener("click",()=>{try{const c=chart?.takeScreenshot?.();if(!c)throw Error("Snapshot unavailable in this chart build.");const a=document.createElement("a");a.download="QUANTNEX-VIEW-"+selected().symbol+".png";a.href=c.toDataURL("image/png");a.click();}catch(e){setStatus(e.message,"error");}});
refresh();const timer=window.setInterval(refresh,45000);window.addEventListener("beforeunload",()=>{window.clearInterval(timer);observer?.disconnect();chart?.remove();});
})();