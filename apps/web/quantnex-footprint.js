/* Phase 3 archived Binance Spot footprint viewer. */
(function initQuantnexFootprint(){
  const $=id=>document.getElementById(id);
  const button=$("qaFootprintLoad");
  if(!button)return;
  const safe=(value,digits=4)=>{const n=Number(value);return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:digits}):"—";};
  const cell=(row,value,className="")=>{const td=document.createElement("td");td.textContent=value==null?"—":String(value);if(className)td.className=className;row.append(td);};
  const setText=(id,value)=>{const el=$(id);if(el)el.textContent=value;};
  const renderList=(id,items,format)=>{const el=$(id);if(!el)return;el.replaceChildren();if(!items?.length){el.textContent="No observed candidates in this window.";return;}items.slice(0,8).forEach(item=>{const p=document.createElement("p");p.textContent=format(item);el.append(p);});};
  let latestFootprint=null;
  function drawFootprintChart(data){
    const canvas=$("qaFootprintCanvas");if(!canvas)return;
    const width=Math.max(320,canvas.clientWidth||900),height=320,dpr=Math.min(2,window.devicePixelRatio||1);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,width,height);
    const candles=(data.candles||[]).filter(x=>x.levels?.length).slice(-24);
    if(!candles.length){ctx.fillStyle="#8b949e";ctx.font="12px sans-serif";ctx.fillText("No archived footprint intervals in this range.",16,30);return;}
    const prices=[...new Set(candles.flatMap(x=>x.levels.map(y=>Number(y.price))))].filter(Number.isFinite).sort((a,b)=>b-a).slice(0,80);
    if(!prices.length)return;
    const left=72,right=10,top=12,bottom=32,plotW=width-left-right,plotH=height-top-bottom;
    const rowH=Math.max(3,Math.min(15,plotH/prices.length)),colW=plotW/candles.length;
    const maxSide=Math.max(1,...candles.flatMap(x=>x.levels.flatMap(y=>[Number(y.buy_volume)||0,Number(y.sell_volume)||0])));
    ctx.font="10px sans-serif";ctx.textBaseline="middle";
    prices.forEach((price,index)=>{
      const y=top+index*rowH+rowH/2;
      ctx.fillStyle="#8b949e";ctx.textAlign="right";ctx.fillText(price.toLocaleString(undefined,{maximumFractionDigits:8}),left-8,y);
      ctx.strokeStyle="rgba(130,140,150,.12)";ctx.beginPath();ctx.moveTo(left,y+rowH/2);ctx.lineTo(width-right,y+rowH/2);ctx.stroke();
      candles.forEach((candle,col)=>{
        const level=candle.levels.find(x=>Number(x.price)===price);if(!level)return;
        const center=left+col*colW+colW/2,half=Math.max(1,(colW-3)/2);
        const buy=(Number(level.buy_volume)||0)/maxSide*half;
        const sell=(Number(level.sell_volume)||0)/maxSide*half;
        ctx.fillStyle="#20c997";ctx.fillRect(center-buy,y-rowH*.38,buy,Math.max(2,rowH*.76));
        ctx.fillStyle="#ef6868";ctx.fillRect(center,y-rowH*.38,sell,Math.max(2,rowH*.76));
      });
    });
    ctx.fillStyle="#8b949e";ctx.textAlign="center";ctx.textBaseline="alphabetic";
    candles.forEach((candle,col)=>{const x=left+col*colW+colW/2;if(col%Math.max(1,Math.ceil(candles.length/8))===0)ctx.fillText(new Date(candle.open_time_ms).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit"}),x,height-9);});
  }
  async function load(){
    const symbol=String($("qaSymbol")?.value||"BTCUSDT").toUpperCase();
    const market=String($("qaMarketType")?.value||"BINANCE_SPOT");
    const tick=Number($("qaFootprintTick").value);
    const interval=Number($("qaFootprintInterval").value);
    const minutes=Number($("qaFootprintHistory").value);
    if(market!=="BINANCE_SPOT"){setText("qaFootprintStatus","Footprint archive is Binance Spot only. Futures needs its own validated trade archive.");return;}
    if(!Number.isFinite(tick)||tick<=0){setText("qaFootprintStatus","Enter a valid positive exchange price tick.");return;}
    button.disabled=true;button.textContent="Loading…";setText("qaFootprintStatus","Reading archived events for "+symbol+"…");
    try{
      const end=Date.now(),start=end-minutes*60_000;
      const url="/api/v1/order-flow/footprint/"+encodeURIComponent(symbol)+"?start_ms="+start+"&end_ms="+end+"&price_step="+encodeURIComponent(String(tick))+"&interval_ms="+interval+"&max_levels=250&imbalance_ratio=3";
      const response=await fetch(url,{headers:{"Accept":"application/json"},cache:"no-store"});
      const data=await response.json();
      if(!response.ok)throw new Error(data.detail||("HTTP "+response.status));
      const rows=$("qaFootprintRows");rows.replaceChildren();
      const flattened=[];
      (data.candles||[]).forEach(candle=>(candle.levels||[]).forEach(level=>flattened.push({time:candle.open_time_ms,...level})));
      flattened.sort((a,b)=>b.time-a.time||Number(b.price)-Number(a.price));
      if(!flattened.length){const tr=document.createElement("tr");const td=document.createElement("td");td.colSpan=7;td.className="empty-row";td.textContent="No archived trade events found for this symbol and time range. Start the QUANTNEX Spot capture worker and try again.";tr.append(td);rows.append(tr);}
      flattened.slice(0,300).forEach(item=>{const tr=document.createElement("tr");cell(tr,new Date(item.time).toISOString().replace("T"," ").slice(0,19));cell(tr,item.price);cell(tr,safe(item.buy_volume));cell(tr,safe(item.sell_volume));cell(tr,safe(item.delta),Number(item.delta)>=0?"qa-footprint-buy":"qa-footprint-sell");cell(tr,item.buy_imbalance?"YES":"—",item.buy_imbalance?"qa-footprint-buy":"");cell(tr,item.sell_imbalance?"YES":"—",item.sell_imbalance?"qa-footprint-sell":"");rows.append(tr);});
      latestFootprint=data;drawFootprintChart(data);
      const totalTrades=Number(data.accepted_trade_events)||0;
      const stacked=data.stacked_imbalances||[],absorption=data.absorption_candidates||[],icebergs=data.iceberg_candidates||[],pulls=data.liquidity_pull_context||[];
      const kpis=$("qaFootprintKpis");kpis.replaceChildren();
      [["Observed trades",safe(totalTrades,0)],["Stacked imbalance",String(stacked.length)],["Delta divergence",data.delta_divergence?.signal||"—"],["Absorption candidates",String(absorption.length)]].forEach(([label,value])=>{const article=document.createElement("article"),span=document.createElement("span"),strong=document.createElement("strong");span.textContent=label;strong.textContent=value;article.append(span,strong);kpis.append(article);});
      renderList("qaFootprintStacked",stacked,x=>x.side+" · "+x.count+" adjacent levels · "+x.levels.join(", "));
      renderList("qaFootprintAbsorption",absorption,x=>x.price+" · vol "+x.volume+" · delta "+x.delta+" · "+x.confidence+" confidence");
      renderList("qaFootprintIceberg",icebergs,x=>x.price+" · "+x.trade_count+" executions · "+x.confidence+" confidence (not confirmed iceberg)");
      renderList("qaFootprintPulls",pulls,x=>x.price+" · "+x.pulls+" zero-quantity updates / "+x.updates+" changes (not proof of spoofing)");
      setText("qaFootprintStatus",totalTrades+" archived trades · "+flattened.length+" price levels · "+data.coverage);
      setText("qaFootprintDisclaimer",(data.delta_divergence?.note||"")+" "+(data.spoofing_detection?.note||"")+" Data source: archived Binance Spot events only.");
    }catch(error){setText("qaFootprintStatus","Footprint unavailable: "+error.message);}
    finally{button.disabled=false;button.textContent="Load footprint";}
  }
  button.addEventListener("click",load);\n  window.addEventListener("resize",()=>{if(latestFootprint)drawFootprintChart(latestFootprint);});
  $("qaSymbol")?.addEventListener("change",()=>setText("qaFootprintStatus","Symbol changed. Load footprint to refresh."));
  $("qaMarketType")?.addEventListener("change",()=>setText("qaFootprintStatus","Market changed. Footprint archive is Spot-only."));
})();