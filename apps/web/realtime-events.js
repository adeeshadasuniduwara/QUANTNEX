/* Shared local QUANTNEX event stream. No cloud relay, credentials or synthetic market data. */
(()=>{
"use strict";
const localHosts=new Set(["127.0.0.1","localhost"]);
if(!localHosts.has(location.hostname))return;
let socket=null,retryTimer=null,retryMs=1000,closedByPage=false,lastEventId=0,connectedOnce=false;
const emit=(name,detail)=>window.dispatchEvent(new CustomEvent(name,{detail}));
const status=(state,extra={})=>emit("quantnex:stream-status",{feed:"workspace",status:state,...extra});
function scheduleReconnect(){
 if(closedByPage||retryTimer!==null)return;
 status("reconnecting",{retryInMs:retryMs});
 retryTimer=window.setTimeout(()=>{retryTimer=null;connect();},retryMs);
 retryMs=Math.min(15000,retryMs*2);
}
function connect(){
 if(closedByPage||socket&&[WebSocket.CONNECTING,WebSocket.OPEN].includes(socket.readyState))return;
 const host=location.hostname==="localhost"?"localhost":"127.0.0.1";
 try{socket=new WebSocket("ws://"+host+":8000/api/v1/events/stream");}
 catch(error){scheduleReconnect();return;}
 socket.addEventListener("open",()=>status("connecting"));
 socket.addEventListener("message",message=>{
  let event;try{event=JSON.parse(message.data);}catch{return;}
  if(event.type==="stream.ping"){if(socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify({type:"stream.pong"}));return;}
  if(event.type==="stream.ready"){
   const current=Number(event.event_id)||0;
   if(connectedOnce&&current!==lastEventId)emit("quantnex:workspace-resync",{reason:current<lastEventId?"event_stream_restarted":"events_missed_during_disconnect",from:lastEventId,to:current});
   lastEventId=Math.max(lastEventId,current);connectedOnce=true;retryMs=1000;
   status("connected",{eventId:lastEventId,replay:false});
   return;
  }
  if(event.type==="stream.resync_required"){
   lastEventId=Math.max(lastEventId,Number(event.event_id)||0);
   emit("quantnex:workspace-resync",{reason:event.payload?.reason||"server_requested_resync",event});
   return;
  }
  const id=Number(event.event_id)||0;
  if(id&&lastEventId&&id>lastEventId+1)emit("quantnex:workspace-resync",{reason:"event_sequence_gap",from:lastEventId,to:id});
  if(id)lastEventId=Math.max(lastEventId,id);
  emit("quantnex:workspace-event",event);
 });
 socket.addEventListener("error",()=>status("error"));
 socket.addEventListener("close",event=>{
  socket=null;status("disconnected",{code:event.code,reason:event.reason||"Local event stream disconnected."});
  scheduleReconnect();
 });
}
window.addEventListener("pagehide",()=>{
 closedByPage=true;if(retryTimer!==null)window.clearTimeout(retryTimer);
 if(socket){socket.close(1000,"Workspace page closing.");socket=null;}
});
connect();
})();
