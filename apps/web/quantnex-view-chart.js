(() => {
"use strict";
const $=id=>document.getElementById(id),host=$("qxChartHost");
if(!host||typeof apiRequest!=="function")return;
const palette={bull:"#22c997",bear:"#f05d68",fvg:"#4a9cff",ob:"#c18cff",breaker:"#f4b860",sr:"#e6c85c"};
const INTERVALS={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400};
const fmt=v=>Number(v).toLocaleString(undefined,{maximumFractionDigits:8});
const stamp=v=>{let s=String(v||"");if(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?$/.test(s))s+="Z";const n=Date.parse(s);return Number.isFinite(n)?Math.floor(n/1000):null;};
const selected=()=>({symbol:$("qxSymbol")?.value||"BTCUSDT",interval:$("qxInterval")?.value||"15m"});
function restoreChartSelection(){try{const saved=JSON.parse(localStorage.getItem("quantnex.chart.selection.v1")||"{}");if(saved.symbol&&[...($("qxSymbol")?.options||[])].some(x=>x.value===saved.symbol))$("qxSymbol").value=saved.symbol;if(saved.interval&&[...($("qxInterval")?.options||[])].some(x=>x.value===saved.interval))$("qxInterval").value=saved.interval;}catch{}}
function saveChartSelection(){try{localStorage.setItem("quantnex.chart.selection.v1",JSON.stringify(selected()));}catch{}}
restoreChartSelection();
const isChartViewActive=()=>!document.hidden&&document.querySelector(".workspace-view:not([hidden])")?.dataset.workspaceView==="tradingview";
let candles=[],analysis=null,ws=null,retry=null,historyRequests=new Map(),resize=null,reconnectAttempts=0,lastFeedMessageAt=0,staleWatchdog=null;
let candleRevision=0,indicatorCache=null,indicatorCacheRevision=-1,drawFrame=null;
let canvas,ctx,view={start:0,count:120,priceZoom:1,priceShift:0,drag:null,crosshair:null},drawMode="cursor",drawings=[],pendingDrawing=null,tradePlan=null,lastPrice=null,feedName="",feedState="connecting";
const chartBg=()=> $("qxChartTheme")?.value==="light"?"#f7f9fc":"#080d13";
const textColor=()=> $("qxChartTheme")?.value==="light"?"#263244":"#b8c4d4";
function setStatus(message,state=""){const e=$("qxChartStatus");if(e){e.textContent=message;e.dataset.state=state;}const t=$("qxChartIntelState");if(t)t.textContent=state==="error"?(message.startsWith("ANALYSIS ERROR")?"ANALYSIS ERROR":"FEED ERROR"):message.includes("CONFIRMED")?"CONFIRMED":message.includes("WAITING")?"SCANNING":feedState.toUpperCase();}
function ema(values,p){if(!values.length)return[];const a=2/(p+1),out=[values[0]];for(let i=1;i<values.length;i++)out.push(a*values[i]+(1-a)*out[i-1]);return out;}
function rsiSeries(values,p=14){const out=Array(values.length).fill(null);if(values.length<=p)return out;let g=0,l=0;for(let i=1;i<=p;i++){const d=values[i]-values[i-1];g+=Math.max(d,0);l+=Math.max(-d,0);}let ag=g/p,al=l/p;out[p]=al===0?100:100-100/(1+ag/al);for(let i=p+1;i<values.length;i++){const d=values[i]-values[i-1];ag=(ag*(p-1)+Math.max(d,0))/p;al=(al*(p-1)+Math.max(-d,0))/p;out[i]=al===0?100:100-100/(1+ag/al);}return out;}
function adxSeries(rows,p=14){const out=Array(rows.length).fill(null),plus=Array(rows.length).fill(null),minus=Array(rows.length).fill(null);if(rows.length<p*2+1)return{adx:out,pdi:plus,mdi:minus};const tr=[],up=[],down=[];for(let i=1;i<rows.length;i++){const a=rows[i],b=rows[i-1],u=a.high-b.high,d=b.low-a.low;tr.push(Math.max(a.high-a.low,Math.abs(a.high-b.close),Math.abs(a.low-b.close)));up.push(u>d&&u>0?u:0);down.push(d>u&&d>0?d:0);}const dx=[];for(let i=p-1;i<tr.length;i++){const t=tr.slice(i-p+1,i+1).reduce((a,b)=>a+b,0),u=up.slice(i-p+1,i+1).reduce((a,b)=>a+b,0),d=down.slice(i-p+1,i+1).reduce((a,b)=>a+b,0),pi=t?100*u/t:0,mi=t?100*d/t:0;plus[i+1]=pi;minus[i+1]=mi;dx.push({i:i+1,v:100*Math.abs(pi-mi)/Math.max(pi+mi,1e-9)});}for(let i=p-1;i<dx.length;i++){const q=dx.slice(i-p+1,i+1);if(q.length===p)out[q.at(-1).i]=q.reduce((s,x)=>s+x.v,0)/p;}return{adx:out,pdi:plus,mdi:minus};}
function sma(values,p){return values.map((_,i)=>i+1<p?null:values.slice(i-p+1,i+1).reduce((a,b)=>a+b,0)/p);}
function atrSeries(rows,p=14){const tr=rows.map((r,i)=>i===0?null:Math.max(r.high-r.low,Math.abs(r.high-rows[i-1].close),Math.abs(r.low-rows[i-1].close)));return tr.map((_,i)=>i<p?null:tr.slice(i-p+1,i+1).reduce((a,b)=>a+b,0)/p);}
function stochSeries(rows,p=14){const k=rows.map((r,i)=>{if(i+1<p)return null;const w=rows.slice(i-p+1,i+1),hi=Math.max(...w.map(x=>x.high)),lo=Math.min(...w.map(x=>x.low));return hi===lo?50:100*(r.close-lo)/(hi-lo);});return{k,d:sma(k.map(x=>x??0),3).map((v,i)=>i<p+1?null:v)};}
function cciSeries(rows,p=20){const tp=rows.map(r=>(r.high+r.low+r.close)/3);return tp.map((v,i)=>{if(i+1<p)return null;const w=tp.slice(i-p+1,i+1),mean=w.reduce((a,b)=>a+b,0)/p,dev=w.reduce((a,b)=>a+Math.abs(b-mean),0)/p;return dev? (v-mean)/(.015*dev):0;});}
function calcIndicators(){
 if(indicatorCache&&indicatorCacheRevision===candleRevision)return indicatorCache;
 const c=candles.map(x=>x.close),fast=ema(c,12),slow=ema(c,26),macd=fast.map((v,i)=>v-slow[i]),signal=ema(macd,9),adx=adxSeries(candles),mid=sma(c,20),std=c.map((_,i)=>{if(i<19)return null;const w=c.slice(i-19,i+1),m=mid[i];return Math.sqrt(w.reduce((a,b)=>a+(b-m)**2,0)/20);}),vwap=[];
 let day="",pv=0,vol=0;
 candles.forEach(r=>{const d=new Date(r.time*1000).toISOString().slice(0,10);if(d!==day){day=d;pv=0;vol=0;}const q=Number(r.volume||0);if(q>0){pv+=((r.high+r.low+r.close)/3)*q;vol+=q;}vwap.push(vol?pv/vol:null);});
 indicatorCache={ema20:ema(c,20),ema50:ema(c,50),ema200:ema(c,200),sma20:mid,bbUpper:mid.map((v,i)=>v==null?null:v+2*std[i]),bbLower:mid.map((v,i)=>v==null?null:v-2*std[i]),vwap,rsi:rsiSeries(c),macd,signal,hist:macd.map((v,i)=>v-signal[i]),adx,atr:atrSeries(candles),stoch:stochSeries(candles),cci:cciSeries(candles)};
 indicatorCacheRevision=candleRevision;
 return indicatorCache;
}
function visible(){const end=candles.length,start=Math.max(0,Math.min(end-1,view.start)),count=Math.max(20,Math.min(view.count,end-start));return{start:Math.max(0,end-count-view.start),end:Math.max(0,end-view.start),count};}
function setupCanvas(){host.replaceChildren();canvas=document.createElement("canvas");canvas.className="qx-native-chart-canvas";canvas.setAttribute("role","img");canvas.setAttribute("aria-label","QUANTNEX first-party live candlestick chart");host.append(canvas);ctx=canvas.getContext("2d");resize?.disconnect();resize=new ResizeObserver(draw);resize.observe(host);canvas.addEventListener("pointerdown",pointerDown);canvas.addEventListener("pointermove",pointerMove);canvas.addEventListener("pointerup",pointerUp);canvas.addEventListener("pointercancel",pointerUp);canvas.addEventListener("pointerleave",()=>{if(!view.drag){view.crosshair=null;draw();}});canvas.addEventListener("wheel",wheel,{passive:false});canvas.addEventListener("dblclick",()=>fit());}
function dimensions(){const r=host.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2),width=Math.max(1,Math.floor(r.width*d)),height=Math.max(1,Math.floor(r.height*d));if(canvas.width!==width)canvas.width=width;if(canvas.height!==height)canvas.height=height;const cssWidth=r.width+"px",cssHeight=r.height+"px";if(canvas.style.width!==cssWidth)canvas.style.width=cssWidth;if(canvas.style.height!==cssHeight)canvas.style.height=cssHeight;ctx.setTransform(d,0,0,d,0,0);return{w:r.width,h:r.height};}
function scheduleDraw(){if(drawFrame!==null)return;drawFrame=requestAnimationFrame(()=>{drawFrame=null;draw();});}
function heikin(rows){let po=null,pc=null;return rows.map(c=>{const close=(c.open+c.high+c.low+c.close)/4,open=po===null?(c.open+c.close)/2:(po+pc)/2;po=open;pc=close;return{...c,open,close,high:Math.max(c.high,open,close),low:Math.min(c.low,open,close)};});}
function priceAxisWidth(width){return Math.min(132,Math.max(84,width*.13));}
function draw(){
 if(!canvas||!ctx)return;
 const{w,h}=dimensions();ctx.clearRect(0,0,w,h);ctx.fillStyle=chartBg();ctx.fillRect(0,0,w,h);
 if(!candles.length){ctx.fillStyle=textColor();ctx.font="13px system-ui";ctx.fillText("Waiting for market candles…",24,36);return;}
 const end=candles.length,start=Math.max(0,end-view.count-view.start),rows=candles.slice(start,end-view.start||undefined);if(!rows.length)return;const plotSlots=Math.max(24,view.count+12);
 const left=12,axisWidth=priceAxisWidth(w),right=w-axisWidth,top=18,bottom=h-70,plotW=right-left,plotH=bottom-top;
 const type=$("qxChartType")?.value||"candles",src=type==="heikin"?heikin(rows):rows;
 const rawMin=Math.min(...src.map(x=>x.low)),rawMax=Math.max(...src.map(x=>x.high));
 const baseRange=Math.max(rawMax-rawMin,Math.abs(rawMax)*.001,1e-8),pad=baseRange*.08;
 const logScale=$("qxLogScale")?.checked===true,scale=v=>logScale?Math.log(Math.max(v,1e-12)):v,unscale=v=>logScale?Math.exp(v):v;
 const rawLo=scale(Math.max(1e-12,rawMin-pad)),rawHi=scale(rawMax+pad),rawRange=Math.max(1e-8,rawHi-rawLo);
 const center=(rawLo+rawHi)/2+(Number(view.priceShift)||0)*rawRange;
 const range=Math.max(1e-8,rawRange/Math.max(.25,Math.min(8,view.priceZoom||1)));
 const lo=center-range/2,hi=center+range/2;
 const y=v=>top+(hi-scale(v))/(hi-lo)*plotH,x=i=>left+(i+.5)*plotW/plotSlots;
 const up=$("qxUpColor")?.value||palette.bull,down=$("qxDownColor")?.value||palette.bear;
 const light=$("qxChartTheme")?.value==="light";
 ctx.fillStyle=light?"#eef2f7":"#0c131d";ctx.fillRect(right,top,w-right,bottom-top);ctx.fillRect(left,bottom,plotW,h-bottom);
 ctx.fillStyle=textColor();ctx.font="9px system-ui";ctx.textAlign="left";ctx.textBaseline="middle";
 ctx.fillText("PRICE",right+8,top-7);ctx.fillText("TIME",left,bottom+8);
 for(let i=0;i<=5;i++){
  const yy=top+i*plotH/5,val=unscale(hi-i*(hi-lo)/5);
  ctx.strokeStyle=$("qxGrid")?.checked?"rgba(130,150,175,.16)":"transparent";
  ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();
  ctx.strokeStyle=light?"rgba(50,65,85,.28)":"rgba(160,180,205,.24)";ctx.beginPath();ctx.moveTo(right,yy);ctx.lineTo(right+5,yy);ctx.stroke();
  ctx.fillStyle=textColor();ctx.fillText(fmt(val),right+8,yy);
 }
 if($("qxGrid")?.checked){for(let i=0;i<=8;i++){const xx=left+i*plotW/8;ctx.strokeStyle="rgba(130,150,175,.08)";ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,bottom);ctx.stroke();}}
 const timeLabel=seconds=>{
  const date=new Date(seconds*1000),now=new Date(),clock=date.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});
  return w<600?clock:(date.toDateString()===now.toDateString()?clock:date.toLocaleDateString([],{month:"short",day:"2-digit"})+" "+clock);
 };
 ctx.font="9px system-ui";ctx.textAlign="center";ctx.textBaseline="middle";
 const timeTicks=w<520?4:6;
 for(let i=0;i<=timeTicks;i++){
  const index=Math.max(0,Math.min(rows.length-1,Math.round(i*(rows.length-1)/timeTicks))),xx=x(index);
  const label=timeLabel(rows[index].time),labelX=Math.max(left+26,Math.min(right-26,xx));
  ctx.strokeStyle=light?"rgba(50,65,85,.28)":"rgba(160,180,205,.24)";
  ctx.beginPath();ctx.moveTo(xx,bottom);ctx.lineTo(xx,bottom+5);ctx.stroke();
  ctx.fillStyle=textColor();ctx.fillText(label,labelX,bottom+27);
 }
 const ind=calcIndicators(),sliceLine=a=>a.slice(start,end-view.start||undefined);
 const drawLine=(vals,color,width=1.4)=>{ctx.beginPath();let begun=false;vals.forEach((v,i)=>{if(!Number.isFinite(v))return;const xx=x(i),yy=y(v);if(!begun){ctx.moveTo(xx,yy);begun=true;}else ctx.lineTo(xx,yy);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();};
 const candleW=Math.max(1,Math.min(18,plotW/plotSlots*.68));
 if(type==="line"||type==="area"){
  const vals=src.map(c=>c.close);ctx.beginPath();vals.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v)));
  if(type==="area"){ctx.lineTo(x(vals.length-1),bottom);ctx.lineTo(x(0),bottom);ctx.closePath();ctx.fillStyle="rgba(99,169,255,.13)";ctx.fill();}
  ctx.beginPath();vals.forEach((v,i)=>i?ctx.lineTo(x(i),y(v)):ctx.moveTo(x(i),y(v)));ctx.strokeStyle="#63a9ff";ctx.lineWidth=2;ctx.stroke();
 }else src.forEach((c,i)=>{const xx=x(i),color=c.close>=c.open?up:down;ctx.strokeStyle=color;ctx.fillStyle=color;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(xx,y(c.high));ctx.lineTo(xx,y(c.low));ctx.stroke();if(type==="bar"){ctx.beginPath();ctx.moveTo(xx-candleW/2,y(c.open));ctx.lineTo(xx,y(c.open));ctx.moveTo(xx,y(c.close));ctx.lineTo(xx+candleW/2,y(c.close));ctx.stroke();}else{const yy=Math.min(y(c.open),y(c.close)),hh=Math.max(1,Math.abs(y(c.open)-y(c.close)));ctx.fillRect(xx-candleW/2,yy,candleW,hh);}});
 if($("qxEma20")?.checked)drawLine(sliceLine(ind.ema20),"#f3c969");
 if($("qxEma50")?.checked)drawLine(sliceLine(ind.ema50),"#67a7ff");
 if($("qxEma200")?.checked)drawLine(sliceLine(ind.ema200),"#c18cff");
 if($("qxSma20")?.checked)drawLine(sliceLine(ind.sma20),"#f08c4a");
 if($("qxBollinger")?.checked){drawLine(sliceLine(ind.bbUpper),"rgba(111,170,255,.85)",1);drawLine(sliceLine(ind.bbLower),"rgba(111,170,255,.85)",1);}
 if($("qxVwap")?.checked)drawLine(sliceLine(ind.vwap),"#f0d36a",1.7);
 if($("qxVolume")?.checked){const vmax=Math.max(1,...rows.map(c=>Number(c.volume||0))),vh=plotH*.16;rows.forEach((c,i)=>{const xx=x(i),v=Number(c.volume||0),color=c.close>=c.open?up:down;ctx.globalAlpha=.28;ctx.fillStyle=color;ctx.fillRect(xx-candleW/2,bottom-v/vmax*vh,candleW,Math.max(1,v/vmax*vh));});ctx.globalAlpha=1;}
 const priceLabelPlacements=[];
 const drawPriceLabel=(label,value,color,anchorY)=>{
  const text=label+" "+fmt(value),step=15,half=7;
  let labelY=Math.max(top+half,Math.min(bottom-half,anchorY-8));
  const candidates=[0,1,-1,2,-2,3,-3,4,-4,5,-5].map(n=>labelY+n*step).filter(v=>v>=top+half&&v<=bottom-half);
  const chosen=candidates.find(v=>priceLabelPlacements.every(existing=>Math.abs(existing-v)>=step))??labelY;
  priceLabelPlacements.push(chosen);
  ctx.save();ctx.font="600 9px system-ui";ctx.textAlign="left";ctx.textBaseline="middle";
  const width=Math.min(plotW*.62,ctx.measureText(text).width+10);
  ctx.fillStyle=light?"rgba(247,249,252,.94)":"rgba(8,13,19,.94)";ctx.fillRect(left+3,chosen-half,width,14);
  ctx.fillStyle=color;ctx.fillText(text,left+7,chosen);ctx.restore();
 };
 const priceLine=(label,value,color,dash=true)=>{if(!Number.isFinite(Number(value)))return;const yy=y(Number(value));if(yy<top||yy>bottom)return;ctx.strokeStyle=color;ctx.lineWidth=1;ctx.setLineDash(dash?[5,4]:[]);ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();ctx.setLineDash([]);drawPriceLabel(label,value,color,yy);};
 const st=analysis?.features?.structure||{};
 if($("qxOverlaySR")?.checked){priceLine("SWING HIGH",st.swing_high,palette.sr);priceLine("SWING LOW",st.swing_low,palette.sr);priceLine("EQUILIBRIUM",st.equilibrium,"#aab4c4");}
 if($("qxOverlayZones")?.checked){for(const[name,z,color]of[["BULL FVG",st.bullish_fvg,palette.fvg],["BEAR FVG",st.bearish_fvg,palette.fvg],["BULL OB",st.bullish_order_block,palette.ob],["BEAR OB",st.bearish_order_block,palette.ob],["BULL BREAKER",st.bullish_breaker_block,palette.breaker],["BEAR BREAKER",st.bearish_breaker_block,palette.breaker],["BULL IFVG",st.bullish_ifvg,palette.bear],["BEAR IFVG",st.bearish_ifvg,palette.bear]])if(z&&Number.isFinite(+z.low)&&Number.isFinite(+z.high)){const yy=y(z.high),hh=y(z.low)-yy;ctx.fillStyle=color+"20";ctx.strokeStyle=color;ctx.fillRect(left,yy,plotW,hh);ctx.strokeRect(left,yy,plotW,hh);ctx.fillStyle=color;ctx.fillText(name,left+5,yy+10);}}
 if($("qxOverlayStructure")?.checked&&st.structure_event&&st.structure_event!=="NONE"){ctx.fillStyle="#e9edf5";ctx.font="600 10px system-ui";ctx.fillText(st.structure_event.replace("_"," ")+" · "+(st.liquidity_sweep!=="NONE"?"LIQUIDITY SWEEP "+st.liquidity_sweep:""),left+6,top+10);}
 if(tradePlan){for(const[name,value,color]of[["ENTRY",tradePlan.entry,palette.sr],["SL",tradePlan.stop_loss,down],["TP1",tradePlan.tp1,up],["TP2",tradePlan.tp2,up],["TP3",tradePlan.tp3,up]])priceLine(name,value,color);}
 const allDrawings=[...drawings,...(pendingDrawing?[pendingDrawing]:[])];
 allDrawings.forEach(d=>{
  const x1=left+d.x1*plotW,y1=top+d.y1*plotH,x2=left+d.x2*plotW,y2=top+d.y2*plotH;
  ctx.strokeStyle="#e6c85c";ctx.fillStyle="rgba(230,200,92,.08)";ctx.lineWidth=1.3;ctx.setLineDash(d.type==="horizontal"?[6,4]:[]);
  if(d.type==="horizontal"){ctx.beginPath();ctx.moveTo(left,y1);ctx.lineTo(right,y1);ctx.stroke();}
  else if(d.type==="vertical"){ctx.beginPath();ctx.moveTo(x1,top);ctx.lineTo(x1,bottom);ctx.stroke();}
  else if(d.type==="rectangle"){ctx.fillRect(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1));ctx.strokeRect(Math.min(x1,x2),Math.min(y1,y2),Math.abs(x2-x1),Math.abs(y2-y1));}
  else if(d.type==="fib"){const levels=[0,.236,.382,.5,.618,.786,1];levels.forEach(level=>{const yy=y1+(y2-y1)*level;ctx.setLineDash([]);ctx.beginPath();ctx.moveTo(Math.min(x1,x2),yy);ctx.lineTo(right,yy);ctx.stroke();ctx.fillStyle="#e6c85c";ctx.font="9px system-ui";ctx.textAlign="left";ctx.fillText((level*100).toFixed(1)+"%",Math.min(x1,x2)+4,yy-6);});}
  else{ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();}
  ctx.setLineDash([]);
 });
 const last=candles.at(-1);
 const liveY=y(last.close);
 if(liveY>=top&&liveY<=bottom){
  const liveColor=last.close>=last.open?up:down;
  ctx.strokeStyle=liveColor;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(left,liveY);ctx.lineTo(right,liveY);ctx.stroke();ctx.setLineDash([]);
  ctx.save();ctx.beginPath();ctx.rect(right+1,top,axisWidth-2,plotH);ctx.clip();
  ctx.fillStyle=liveColor;ctx.fillRect(right+1,liveY-10,axisWidth-2,20);
  let liveFont=10;ctx.font="700 "+liveFont+"px system-ui";const liveText=fmt(last.close);
  while(liveFont>7&&ctx.measureText(liveText).width>axisWidth-12){liveFont--;ctx.font="700 "+liveFont+"px system-ui";}
  ctx.fillStyle="#071018";ctx.textAlign="left";ctx.textBaseline="middle";ctx.fillText(liveText,right+6,liveY);ctx.restore();
 }
 if(view.crosshair){
  const{cx,cy}=view.crosshair;
  if(cx>=left&&cx<=right&&cy>=top&&cy<=bottom){
   ctx.strokeStyle="rgba(190,205,225,.65)";ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(cx,top);ctx.lineTo(cx,bottom);ctx.moveTo(left,cy);ctx.lineTo(right,cy);ctx.stroke();ctx.setLineDash([]);
   const index=Math.max(0,Math.min(rows.length-1,Math.floor((cx-left)/plotW*rows.length))),bar=rows[index],crossPrice=unscale(hi-(cy-top)/plotH*(hi-lo));
   ctx.save();ctx.beginPath();ctx.rect(right+1,top,axisWidth-2,plotH);ctx.clip();ctx.fillStyle="#d8e4f2";ctx.fillRect(right+1,cy-9,axisWidth-2,18);ctx.fillStyle="#071018";ctx.font="9px system-ui";ctx.textAlign="left";ctx.textBaseline="middle";ctx.fillText(fmt(crossPrice),right+5,cy);ctx.restore();
   ctx.fillStyle="#d8e4f2";ctx.fillRect(Math.max(left,Math.min(right-92,cx-46)),bottom+3,92,18);ctx.fillStyle="#071018";ctx.textAlign="center";ctx.fillText(timeLabel(bar.time),Math.max(left+46,Math.min(right-46,cx)),bottom+12);
  }
 }
 if($("qxChartLastPrice"))$("qxChartLastPrice").textContent=fmt(last.close);
 const first=candles[Math.max(0,candles.length-Math.max(1,view.count))],change=first?.close?100*(last.close-first.close)/first.close:0;
 if($("qxChartChange")){$("qxChartChange").textContent=(change>=0?"+":"")+change.toFixed(2)+"% visible range · "+candles.length+" candles";$("qxChartChange").dataset.direction=change>=0?"up":"down";}
 renderIndicatorPanels(ind);
}
function renderIndicatorPanels(ind=calcIndicators()){
 const closes=candles.map(c=>c.close),n=candles.length,tail=a=>a.slice(Math.max(0,n-120)),drawPanel=(id,lines,min,max,refs=[])=>{const el=$(id);if(!el)return;let c=el.querySelector("canvas");if(!c){el.replaceChildren();c=document.createElement("canvas");c.className="qx-indicator-native-canvas";el.append(c);}const w=el.clientWidth||500,h=el.clientHeight||142,d=Math.min(devicePixelRatio||1,2);c.width=w*d;c.height=h*d;c.style.width=w+"px";c.style.height=h+"px";const g=c.getContext("2d");g.scale(d,d);g.fillStyle=chartBg();g.fillRect(0,0,w,h);const pad=8,ww=w-16,hh=h-16;g.strokeStyle="rgba(130,150,175,.18)";g.font="9px system-ui";refs.forEach(v=>{const yy=pad+(max-v)/(max-min)*hh;g.beginPath();g.moveTo(pad,yy);g.lineTo(w-pad,yy);g.stroke();g.fillStyle=textColor();g.fillText(String(v),pad+2,yy-2);});lines.forEach(line=>{const vals=tail(line.values);g.strokeStyle=line.color;g.lineWidth=1.6;g.beginPath();let started=false;vals.forEach((v,i)=>{if(!Number.isFinite(v))return;const xx=pad+i*ww/Math.max(vals.length-1,1),yy=pad+(max-v)/(max-min)*hh;if(!started){g.moveTo(xx,yy);started=true;}else g.lineTo(xx,yy);});g.stroke();});};
 const r=ind.rsi.filter(Number.isFinite),m=ind.macd.filter(Number.isFinite),a=ind.adx.adx.filter(Number.isFinite);
 drawPanel("qxRsiChart",[{values:ind.rsi,color:"#b58cff"}],0,100,[30,50,70]);
 drawPanel("qxMacdChart",[{values:ind.macd,color:"#62aaff"},{values:ind.signal,color:"#f2c86b"}],Math.min(-1,...m),Math.max(1,...m),[0]);
 drawPanel("qxAdxChart",[{values:ind.adx.adx,color:"#e8c56b"},{values:ind.adx.pdi,color:palette.bull},{values:ind.adx.mdi,color:palette.bear}],0,100,[20,40]);
 drawPanel("qxAtrChart",[{values:ind.atr,color:"#f0a45d"}],0,Math.max(1,...ind.atr.filter(Number.isFinite)),[]);
 drawPanel("qxStochChart",[{values:ind.stoch.k,color:"#62aaff"},{values:ind.stoch.d,color:"#f2c86b"}],0,100,[20,80]);
 drawPanel("qxCciChart",[{values:ind.cci,color:"#b58cff"}],-200,200,[-100,0,100]);
 const last=a=>{for(let i=a.length-1;i>=0;i--)if(Number.isFinite(a[i]))return a[i];return null;};
 [["qxRsiValue",last(ind.rsi)],["qxMacdValue",last(ind.hist)],["qxAdxValue",last(ind.adx.adx)],["qxAtrValue",last(ind.atr)],["qxStochValue",last(ind.stoch.k)],["qxCciValue",last(ind.cci)]].forEach(([id,v])=>{if($(id))$(id).textContent=v==null?"—":Number(v).toFixed(2);});
}
function drawingsStorageKey(){const pick=selected();return "quantnex.chart.drawings.v1."+pick.symbol+"."+pick.interval;}
function loadDrawings(){try{const saved=JSON.parse(localStorage.getItem(drawingsStorageKey())||"[]");drawings=Array.isArray(saved)?saved.filter(d=>d&&["horizontal","vertical","trend","rectangle","fib"].includes(d.type)&&[d.x1,d.y1,d.x2,d.y2].every(v=>Number.isFinite(Number(v)))):[];}catch{drawings=[];}}
function saveDrawings(){try{localStorage.setItem(drawingsStorageKey(),JSON.stringify(drawings.slice(-100)));}catch{}}
function fit(){view.count=Math.min(500,Math.max(120,candles.length));view.start=0;view.priceZoom=1;view.priceShift=0;draw();}
function pointerDown(e){
 const r=canvas.getBoundingClientRect(),cx=e.clientX-r.left,cy=e.clientY-r.top,left=12,right=r.width-priceAxisWidth(r.width),top=18,bottom=r.height-70;
 canvas.setPointerCapture(e.pointerId);
 if(cx>=right){view.drag={mode:"price-scale",y:e.clientY,priceZoom:view.priceZoom||1};return;}
 if(cy>=bottom){view.drag={mode:"time-scale",x:e.clientX,count:view.count};return;}
 if(cx<left||cy<top||cx>right||cy>bottom)return;
 const px=(cx-left)/(right-left),py=(cy-top)/(bottom-top);
 view.drag={x:e.clientX,y:e.clientY,start:view.start,priceShift:view.priceShift||0,mode:drawMode,px,py};
 if(drawMode!=="cursor")pendingDrawing={type:drawMode,x1:px,y1:py,x2:px,y2:py};
}
function pointerMove(e){
 const r=canvas.getBoundingClientRect(),cx=e.clientX-r.left,cy=e.clientY-r.top,left=12,right=r.width-priceAxisWidth(r.width),top=18,bottom=r.height-70;
 if(view.drag){
  const dx=e.clientX-view.drag.x;
  if(view.drag.mode==="price-scale"){view.priceZoom=Math.max(.25,Math.min(8,view.drag.priceZoom*Math.exp((view.drag.y-e.clientY)*.008)));}
  else if(view.drag.mode==="time-scale"){view.count=Math.max(24,Math.min(500,Math.round(view.drag.count*Math.exp((view.drag.x-e.clientX)*.008))));}
  else if(view.drag.mode==="cursor"&&(Math.abs(dx)>2||Math.abs(e.clientY-view.drag.y)>2)){view.start=Math.max(-Math.min(48,view.count-1),Math.min(Math.max(0,candles.length-view.count),view.drag.start+Math.round(dx/((right-left)/view.count))));view.priceShift=view.drag.priceShift+(e.clientY-view.drag.y)/Math.max(1,bottom-top);}
  else if(pendingDrawing){pendingDrawing.x2=Math.max(0,Math.min(1,(cx-left)/(right-left)));pendingDrawing.y2=Math.max(0,Math.min(1,(cy-top)/(bottom-top)));if(pendingDrawing.type==="horizontal")pendingDrawing.y2=pendingDrawing.y1;if(pendingDrawing.type==="vertical")pendingDrawing.x2=pendingDrawing.x1;}
  draw();
 }else{view.crosshair={cx,cy};draw();}
}
function pointerUp(){if(pendingDrawing){drawings.push({...pendingDrawing});pendingDrawing=null;saveDrawings();}view.drag=null;draw();}
function wheel(e){
 e.preventDefault();const r=canvas.getBoundingClientRect(),cx=e.clientX-r.left,cy=e.clientY-r.top;
 if(cx>=r.width-priceAxisWidth(r.width)){view.priceZoom=Math.max(.25,Math.min(8,(view.priceZoom||1)*(e.deltaY<0?.88:1.14)));}
 else{const factor=e.deltaY<0?.85:1.18;view.count=Math.max(24,Math.min(500,Math.round(view.count*factor)));view.start=Math.max(-Math.min(48,view.count-1),Math.min(Math.max(0,candles.length-view.count),view.start));}
 draw();
}
function mergeCandle(row){if(!row||!Number.isFinite(Number(row.close)))return;const t=typeof row.time==="number"?Math.floor(row.time):stamp(row.time);if(!Number.isFinite(t))return;const next={...row,time:t,open:+row.open,high:+row.high,low:+row.low,close:+row.close,volume:+(row.volume||0)};const last=candles.at(-1);if(last&&last.time===t)candles[candles.length-1]=next;else if(!last||t>last.time){candles.push(next);}else{const i=candles.findIndex(c=>c.time===t);if(i>=0)candles[i]=next;else return;}if(candles.length>1200)candles=candles.slice(-1200);candleRevision++;scheduleDraw();}
function onTradingRoomTick(event){if(!isChartViewActive())return;const d=event.detail||{},symbol=String(d.symbol||"").toUpperCase();if(symbol!==selected().symbol)return;if(symbol==="XAUUSD"&&!String(d.source||"").startsWith("QUANTNEX VIEW · "))return;const price=Number(d.price),ms=Number(d.eventTime)||Date.now();if(!Number.isFinite(price)||price<=0||!candles.length)return;const seconds=INTERVALS[selected().interval]||900,time=Math.floor(ms/1000/seconds)*seconds;let last=candles.at(-1);if(time<last.time)return;if(time>last.time){last={time,open:price,high:price,low:price,close:price,volume:0};candles.push(last);}else{last.high=Math.max(last.high,price);last.low=Math.min(last.low,price);last.close=price;}if(d.kind==="trade"&&Number.isFinite(Number(d.volume)))last.volume+=Number(d.volume);if(candles.length>1200)candles=candles.slice(-1200);candleRevision++;feedName="Trading Room · "+(d.source||"shared live market feed");const p=$("qxChartProvider");if(p)p.textContent="Feed: "+feedName+" · "+candles.length+" candles";scheduleDraw();}
async function loadGoldQuote(){
 if(document.hidden||!isChartViewActive()||selected().symbol!=="XAUUSD")return;
 const pick=selected();
 try{
  const quote=await apiRequest("/api/v1/charts/quote?symbol=XAUUSD&interval="+encodeURIComponent(pick.interval));
  if(!isChartViewActive()||selected().symbol!==pick.symbol||selected().interval!==pick.interval)return;
  if(quote.stale){setStatus("GOLD FEED STALE · CHECK MT5 / TWELVE DATA","error");return;}
  const price=Number(quote.price);
  if(!Number.isFinite(price)||price<=0)throw Error("Gold provider returned an invalid quote.");
  if($("qxChartLastPrice"))$("qxChartLastPrice").textContent=fmt(price);
  const provider=$("qxChartProvider");
  if(provider)provider.textContent="Feed: "+quote.provider+(quote.quote_only?" · live indicative quote only":" · live quote")+(candles.length?" · "+candles.length+" historical candles":"");
  if(candles.length){
   onTradingRoomTick({detail:{symbol:"XAUUSD",price,eventTime:Date.now(),kind:"provider_quote",source:"QUANTNEX VIEW · "+quote.provider}});
  }else{
   setStatus(quote.quote_only?"GOLD LIVE QUOTE · HISTORICAL CANDLES REQUIRE MT5 OR TWELVE DATA":"GOLD QUOTE LIVE · WAITING FOR HISTORICAL CANDLES");
  }
 }catch(error){setStatus("GOLD QUOTE ERROR · "+(error.message||"provider unavailable"),"error");}
}
function stopFeed(){if(ws){ws.onclose=null;ws.close();ws=null;}if(retry){clearTimeout(retry);retry=null;}if(staleWatchdog){clearInterval(staleWatchdog);staleWatchdog=null;}if(drawFrame!==null){cancelAnimationFrame(drawFrame);drawFrame=null;}}
function connectLive(){
 stopFeed();
 const{symbol,interval}=selected(),recovering=reconnectAttempts>0,useCoinbase=symbol==="BTCUSDT"&&reconnectAttempts>=2;
 if(symbol==="XAUUSD"){feedState="polling";return;}
 const stream=symbol.toLowerCase()+"@kline_"+interval;
 try{ws=new WebSocket(useCoinbase?"wss://ws-feed.exchange.coinbase.com":"wss://stream.binance.com:9443/ws/"+stream);}
 catch{feedState="reconnecting";return scheduleReconnect();}
 ws.onopen=()=>{
  if(useCoinbase)ws.send(JSON.stringify({type:"subscribe",product_ids:["BTC-USD"],channels:["ticker"]}));
  reconnectAttempts=0;lastFeedMessageAt=Date.now();feedState="live";
  setStatus(useCoinbase?"LIVE STREAM · COINBASE EXCHANGE BTC-USD":"LIVE STREAM · "+symbol+" · "+interval.toUpperCase());
  const p=$("qxChartProvider");if(p)p.textContent="Feed: "+(useCoinbase?"Coinbase Exchange WebSocket fallback":"Binance WebSocket live")+" · "+candles.length+" historical candles";
  if(recovering)loadHistory();
 };
 ws.onmessage=e=>{
  lastFeedMessageAt=Date.now();
  try{
   const message=JSON.parse(e.data);
   if(useCoinbase){
    if(message.type!=="ticker"||message.product_id!=="BTC-USD")return;
    const price=Number(message.price),ms=Date.parse(message.time)||Date.now(),seconds=INTERVALS[interval]||900;
    if(!Number.isFinite(price)||price<=0)return;
    const time=Math.floor(ms/1000/seconds)*seconds,last=candles.at(-1);
    if(last&&time<last.time)return;
    const bar=last&&last.time===time?{...last,high:Math.max(last.high,price),low:Math.min(last.low,price),close:price,volume:last.volume+Math.max(0,Number(message.last_size)||0)}:
     {time,open:last?last.close:price,high:price,low:price,close:price,volume:Math.max(0,Number(message.last_size)||0)};
    mergeCandle(bar);
    return;
   }
   const k=message.k;if(!k)return;
   mergeCandle({time:Math.floor(k.t/1000),open:k.o,high:k.h,low:k.l,close:k.c,volume:k.v});
  }catch{}
 };
 ws.onerror=()=>{feedState="reconnecting";try{ws?.close();}catch{}};
 ws.onclose=()=>{
  if(staleWatchdog){clearInterval(staleWatchdog);staleWatchdog=null;}
  if(selected().symbol===symbol&&selected().interval===interval){feedState="reconnecting";scheduleReconnect();}
 };
 staleWatchdog=setInterval(()=>{if(!document.hidden&&ws&&ws.readyState===WebSocket.OPEN&&lastFeedMessageAt&&Date.now()-lastFeedMessageAt>30000){feedState="reconnecting";setStatus("LIVE FEED STALE · RECONNECTING","error");try{ws.close();}catch{}}},10000);
}
function scheduleReconnect(){if(retry)return;const delay=Math.min(30000,1000*Math.pow(2,Math.min(reconnectAttempts,5)));reconnectAttempts=Math.min(reconnectAttempts+1,6);const p=$("qxChartProvider");if(p)p.textContent="Feed: reconnecting in "+Math.ceil(delay/1000)+"s · attempt "+reconnectAttempts;retry=setTimeout(()=>{retry=null;if(!document.hidden)connectLive();},delay);}
async function loadHistory(){
 if(!isChartViewActive())return;
 const pick=selected(),key=pick.symbol+"|"+pick.interval;
 if(historyRequests.has(key))return historyRequests.get(key);
 const request=(async()=>{
  try{
   const bars=await apiRequest("/api/v1/charts/candles?symbol="+encodeURIComponent(pick.symbol)+"&interval="+encodeURIComponent(pick.interval)+"&limit=1000");
   if(!isChartViewActive()||selected().symbol!==pick.symbol||selected().interval!==pick.interval)return;
   const rows=(bars.candles||[]).map(c=>({...c,time:stamp(c.time),open:Number(c.open),high:Number(c.high),low:Number(c.low),close:Number(c.close),volume:Number(c.volume||0)}))
    .filter(c=>c.time!==null&&[c.open,c.high,c.low,c.close,c.volume].every(Number.isFinite)&&c.open>0&&c.high>0&&c.low>0&&c.close>0&&c.high>=Math.max(c.open,c.close,c.low)&&c.low<=Math.min(c.open,c.close,c.high)&&c.volume>=0)
    .sort((a,b)=>a.time-b.time);
   const unique=[];for(const row of rows){if(unique.length&&unique[unique.length-1].time===row.time)unique[unique.length-1]=row;else unique.push(row);}
   if(!unique.length)throw Error("The market-data provider returned no valid OHLC candles.");
   // A reconnect backfill can finish after new WebSocket ticks arrive. Keep
   // the live tail instead of replacing it with the slightly older REST snapshot.
   const liveTail=candles.filter(c=>c.time>=unique.at(-1).time);
   const merged=new Map(unique.map(c=>[c.time,c]));
   liveTail.forEach(c=>merged.set(c.time,c));
   candles=[...merged.values()].sort((a,b)=>a.time-b.time).slice(-1200);candleRevision++;
   feedName=bars.provider||"Market feed";
   const p=$("qxChartProvider");
   if(p)p.textContent="Feed: "+feedName+" · "+candles.length+" candles · "+(feedState==="live"?"WebSocket live":"polling")+(bars.stale?" · STALE DATA":" · FRESH")+(candles.length<210?" · INDICATORS WARMING UP":"");
   if(!view.start)fit();else draw();
   if(candles.length<210)setStatus("CHART READY · "+candles.length+" CANDLES · INDICATORS WARMING UP");
  }catch(e){
   setStatus("HISTORY FEED ERROR · "+(e.message||"market data unavailable"),"error");
   const p=$("qxChartProvider");if(p)p.textContent=e.message||"Market data unavailable";
  }
 })();
 historyRequests.set(key,request);
 try{return await request;}finally{if(historyRequests.get(key)===request)historyRequests.delete(key);}
}
function renderAnalysis(data){analysis=data;const f=data.features||{},st=f.structure||{},summary=$("qxChartIntelSummary"),signal=data.signal;if(summary)summary.textContent=signal?signal.side+" · Entry "+fmt(signal.entry)+" · SL "+fmt(signal.stop_loss)+" · TP1 "+fmt(signal.tp1)+" / TP2 "+fmt(signal.tp2)+" / TP3 "+fmt(signal.tp3):"WAITING FOR CONFIRMATION · "+data.confluence_score+"/"+data.score_out_of+" rule matches. No trade plan is active.";const score=Math.max(0,Number(data.confluence_score)||0),outOf=Math.max(1,Number(data.score_out_of)||20),pct=Math.min(100,Math.round(score/outOf*100));if($("qxConfidenceFill"))$("qxConfidenceFill").style.width=pct+"%";if($("qxConfidenceLabel"))$("qxConfidenceLabel").textContent=score+" / "+outOf+" rule matches ("+pct+"% of checklist) · not a win probability";const metrics=$("qxChartIntelMetrics");if(metrics){metrics.replaceChildren();[["RSI",Number(f.rsi).toFixed(1)],["ADX",Number(f.adx).toFixed(1)],["EMA 20",fmt(f.ema20)],["EMA 50",fmt(f.ema50)],["EMA 200",fmt(f.ema200)],["Structure",st.structure_event||"—"],["Trend",st.structure_trend||"—"],["Liquidity",st.liquidity_sweep||"—"],["Premium / Discount",st.premium_discount||"—"],["Confidence",data.confluence_score+"/"+data.score_out_of]].forEach(([a,b])=>{const d=document.createElement("div"),n=document.createElement("span"),v=document.createElement("strong");d.className="qx-chart-intel-metric";n.textContent=a;v.textContent=b;d.append(n,v);metrics.append(d);});}window.quantnexViewSetTradePlan(signal||null);setStatus(signal?"CONFIRMED SETUP · "+signal.side:"WAITING FOR CONFIRMATION · SCANNING");}
window.quantnexViewSetAnalysis=renderAnalysis;
window.quantnexViewSetTradePlan=function(plan){tradePlan=plan||null;draw();};

async function refresh(){if(!isChartViewActive())return;const pick=selected();loadDrawings();candles=[];candleRevision++;analysis=null;tradePlan=null;view.start=0;view.count=120;view.priceZoom=1;view.priceShift=0;reconnectAttempts=0;stopFeed();feedState=pick.symbol==="XAUUSD"?"polling":"connecting";setStatus("LOADING "+pick.symbol+" · "+pick.interval.toUpperCase());await loadHistory();if(pick.symbol!=="XAUUSD")connectLive();else{setStatus(candles.length?"GOLD FEED · MATCHING HISTORY PROVIDER":"GOLD HISTORY UNAVAILABLE · CHECK FEED SETTINGS","error");await loadGoldQuote();}}
function rebuild(){draw();}
["qxSymbol","qxInterval"].forEach(id=>$(id)?.addEventListener("change",()=>{saveChartSelection();refresh();}));
["qxChartType","qxChartTheme","qxVolume","qxEma20","qxEma50","qxEma200","qxSma20","qxBollinger","qxVwap","qxGrid","qxUpColor","qxDownColor","qxOverlayStructure","qxOverlayZones","qxOverlaySR"].forEach(id=>$(id)?.addEventListener("change",rebuild));
$("qxLogScale")?.addEventListener("change",rebuild);
$("qxFitChart")?.addEventListener("click",fit);
$("qxScreenshot")?.addEventListener("click",()=>{try{const a=document.createElement("a");a.download="QUANTNEX-VIEW-"+selected().symbol+".png";a.href=canvas.toDataURL("image/png");a.click();}catch(e){setStatus("Snapshot failed: "+e.message,"error");}});
document.querySelectorAll("[data-qx-draw]").forEach(b=>b.addEventListener("click",()=>{drawMode=b.dataset.qxDraw;document.querySelectorAll("[data-qx-draw]").forEach(x=>x.classList.toggle("active",x===b));}));
$("qxClearDrawings")?.addEventListener("click",()=>{drawings=[];pendingDrawing=null;saveDrawings();draw();});
window.addEventListener("quantnex:market-tick",onTradingRoomTick);
window.addEventListener("quantnex:view-changed",event=>{if(event.detail?.view==="tradingview")refresh();else stopFeed();});
document.addEventListener("visibilitychange",()=>{if(document.hidden){stopFeed();return;}if(isChartViewActive())refresh();});
setupCanvas();
const goldQuoteTimer=setInterval(()=>{if(!document.hidden&&isChartViewActive()&&selected().symbol==="XAUUSD")loadGoldQuote();},30000);
window.addEventListener("beforeunload",()=>{clearInterval(goldQuoteTimer);stopFeed();window.removeEventListener("quantnex:market-tick",onTradingRoomTick);resize?.disconnect();});
})();