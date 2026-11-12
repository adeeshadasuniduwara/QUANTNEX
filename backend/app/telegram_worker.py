"""Background Telegram command and TP1 notification worker."""
from __future__ import annotations
import asyncio, json
from typing import Any
import httpx
from sqlalchemy import select
from .database import SessionLocal
from .models import Preference
from .security import decrypt_secret
from .config import TWELVE_DATA_API_KEY
from .signal_engine import build_signal, MarketDataError

def _get(db, user_id: int, key: str, default: str="") -> str:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    return row.value if row else default

def _set(db, user_id: int, key: str, value: str) -> None:
    row=db.scalar(select(Preference).where(Preference.user_id==user_id,Preference.key==key))
    if row is None: db.add(Preference(user_id=user_id,key=key,value=value))
    else: row.value=value

async def _send(client: httpx.AsyncClient, token: str, chat_id: str, text: str) -> None:
    response=await client.post(f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id":chat_id,"text":text[:4000],"disable_web_page_preview":True})
    response.raise_for_status()
    if not response.json().get("ok"):
        raise httpx.HTTPStatusError("Telegram did not accept the message.",request=response.request,response=response)

async def _price(client: httpx.AsyncClient) -> float | None:
    if not TWELVE_DATA_API_KEY:return None
    response=await client.get("https://api.twelvedata.com/price",
        params={"symbol":"XAU/USD","apikey":TWELVE_DATA_API_KEY})
    data=response.json()
    try:return float(data["price"])
    except (KeyError,TypeError,ValueError):return None

async def _handle_command(client, db, user_id: int, token: str, chat_id: str, text: str) -> str | None:
    parts=text.strip().split()
    command=parts[0].split("@")[0].lower() if parts else ""
    raw=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}')
    try: settings=json.loads(raw)
    except ValueError: settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":7}
    names={"1":"M1","5":"M5","15":"M15","30":"M30","50":"M50","60":"H1","240":"H4"}
    if command in {"/start","/help"}:
        return ("QUANTNEX XAUUSD Signal Bot\n"
            "/timeframes — show settings\n/settf 1|5|15|30|50|60 — primary signal timeframe\n"
            "/settrend 15|30|60|240 — trend filter\n/setanalysis 1,5,15,30,60 — analysis timeframes\n"
            "/scan — run a fresh confluence scan\n/status — connection status")
    if command=="/timeframes":
        enabled=", ".join(names.get(str(x),str(x)) for x in settings.get("enabled",[]))
        return f"Primary: {names.get(str(settings.get('primary')))}\nTrend: {names.get(str(settings.get('trend')))}\nAnalysis: {enabled}"
    if command=="/settf" and len(parts)>1 and parts[1] in {"1","5","15","30","50","60"}:
        settings["primary"]=parts[1];_set(db,user_id,"signal_settings",json.dumps(settings));db.commit()
        return "Primary signal timeframe set to "+names[parts[1]]+"."
    if command=="/settrend" and len(parts)>1 and parts[1] in {"15","30","60","240"}:
        settings["trend"]=parts[1];_set(db,user_id,"signal_settings",json.dumps(settings));db.commit()
        return "Trend filter set to "+names[parts[1]]+"."
    if command=="/setanalysis" and len(parts)>1:
        selected=list(dict.fromkeys(x for x in parts[1].split(",") if x in {"1","5","15","30","50","60"}))
        if not selected:return "Use /setanalysis 1,5,15,30,60"
        settings["enabled"]=selected;_set(db,user_id,"signal_settings",json.dumps(settings));db.commit()
        return "Analysis timeframes saved: "+", ".join(names[x] for x in selected)
    if command=="/status":
        return "QUANTNEX bot connected. Market feed: "+("configured" if TWELVE_DATA_API_KEY else "not configured")+". Broker execution: disabled."
    if command=="/scan":
        try:
            result=await build_signal(settings)
            sig=result.get("signal")
            if not sig:
                _set(db,user_id,"active_signal","");db.commit()
                return "QUANTNEX · XAUUSD\nWAIT — no setup reached the minimum confluence threshold.\nScore: "+str(result["confluence_score"])+"/10\n"+result["score_note"]
            _set(db,user_id,"active_signal",json.dumps({**sig,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
            db.commit()
            return ("QUANTNEX · XAUUSD "+sig["side"]+"\nEntry: "+str(sig["entry"])+"\nSL: "+str(sig["stop_loss"])+
                "\nTP1: "+str(sig["tp1"])+"\nTP2: "+str(sig["tp2"])+"\nTP3: "+str(sig["tp3"])+
                "\nConfluence: "+str(sig["score"])+"/10 (not win probability)\nConfirmations: "+", ".join(sig["confirmations"])+
                "\nTP1 hit alert monitoring is active while the local API is running. No broker order is placed.")
        except MarketDataError as exc:return "Signal scan unavailable: "+str(exc)
        except Exception:return "Signal scan failed. Check the local API logs and market-data provider configuration."
    return "Unknown command. Send /help."

async def telegram_worker() -> None:
    """Poll connected user bots, respond to commands and monitor active TP1 levels."""
    last_monitor={}
    async with httpx.AsyncClient(timeout=12) as client:
        while True:
            try:
                with SessionLocal() as db:
                    rows=list(db.scalars(select(Preference).where(Preference.key=="telegram_bot_token_enc")))
                    for token_row in rows:
                        user_id=token_row.user_id
                        chat_id=_get(db,user_id,"telegram_chat_id")
                        if not chat_id:continue
                        try:token=decrypt_secret(token_row.value)
                        except ValueError:continue
                        offset=int(_get(db,user_id,"telegram_update_offset","0") or "0")
                        try:
                            resp=await client.get(f"https://api.telegram.org/bot{token}/getUpdates",
                                params={"offset":offset,"timeout":0,"allowed_updates":'["message","channel_post"]'})
                            data=resp.json()
                            if data.get("ok"):
                                for update in data.get("result",[]):
                                    offset=max(offset,int(update.get("update_id",0))+1)
                                    message=update.get("message") or update.get("channel_post") or {}
                                    chat=message.get("chat") or {}
                                    if str(chat.get("id"))!=str(chat_id) and not (str(chat_id).startswith("@") and ("@"+str(chat.get("username","")).lower())==str(chat_id).lower()):continue
                                    command=message.get("text","")
                                    answer=await _handle_command(client,db,user_id,token,chat_id,command)
                                    if answer:await _send(client,token,chat_id,answer)
                                _set(db,user_id,"telegram_update_offset",str(offset));db.commit()
                        except (httpx.HTTPError,ValueError):pass
                        now=asyncio.get_running_loop().time()
                        if now-last_monitor.get(user_id,0)>=60:
                            active_raw=_get(db,user_id,"active_signal")
                            if active_raw and TWELVE_DATA_API_KEY:
                                try:
                                    active=json.loads(active_raw);price=await _price(client)
                                    if price is not None:
                                        side=active.get("side")
                                        hit_sl=price<=active["stop_loss"] if side=="BUY" else price>=active["stop_loss"]
                                        hit_tp1=price>=active["tp1"] if side=="BUY" else price<=active["tp1"]
                                        hit_tp2=price>=active["tp2"] if side=="BUY" else price<=active["tp2"]
                                        hit_tp3=price>=active["tp3"] if side=="BUY" else price<=active["tp3"]
                                        if hit_sl and not active.get("sl_notified") and not active.get("tp1_notified"):
                                            await _send(client,token,chat_id,f"⚠️ QUANTNEX · XAUUSD SL level touched\nObserved price: {price}\nCheck your broker execution. No order was modified.")
                                            active["sl_notified"]=True;active_raw=""
                                        elif hit_tp1 and not active.get("tp1_notified"):
                                            await _send(client,token,chat_id,f"⚠️ QUANTNEX · XAUUSD TP1 level touched\nObserved price: {price}\nReview moving Stop Loss to breakeven (Entry {active['entry']}). Verify the actual position and move SL manually in your broker. QUANTNEX does not modify broker orders.")
                                            active["tp1_notified"]=True
                                        if hit_tp2 and not active.get("tp2_notified"):
                                            await _send(client,token,chat_id,f"QUANTNEX · XAUUSD TP2 level touched at {price}. Check broker execution.")
                                            active["tp2_notified"]=True
                                        if hit_tp3 and not active.get("tp3_notified"):
                                            await _send(client,token,chat_id,f"QUANTNEX · XAUUSD TP3 level touched at {price}. Review and manage your position manually.")
                                            active["tp3_notified"]=True;active_raw=""
                                        if active_raw:_set(db,user_id,"active_signal",json.dumps(active))
                                        else:_set(db,user_id,"active_signal","")
                                        db.commit()
                                except (ValueError,KeyError,httpx.HTTPError):pass
                        # Automatic signals scan each selected market independently.
                        auto_raw=_get(db,user_id,"auto_signal_settings",'{"enabled":false,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}')
                        try: auto_settings=json.loads(auto_raw)
                        except ValueError: auto_settings={"enabled":False,"interval_seconds":180,"symbols":["BTCUSDT","ETHUSDT","SOLUSDT"]}
                        interval=max(60,min(3600,int(auto_settings.get("interval_seconds",180) or 180)))
                        auto_key=(user_id,"auto")
                        selected=list(dict.fromkeys(str(value).upper() for value in auto_settings.get("symbols",["BTCUSDT","ETHUSDT","SOLUSDT"])
                            if str(value).upper() in {"BTCUSDT","ETHUSDT","SOLUSDT","XAUUSD"}))
                        if auto_settings.get("enabled") and selected and now-last_monitor.get(auto_key,0)>=interval:
                            signal_raw=_get(db,user_id,"signal_settings",'{"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}')
                            try: signal_settings=json.loads(signal_raw)
                            except ValueError: signal_settings={"primary":"5","trend":"60","enabled":["60","30","15","5","1"],"risk_percent":1,"min_score":8}
                            signal_settings["min_score"]=max(8,int(signal_settings.get("min_score",8)))
                            for market_symbol in selected:
                                if market_symbol=="XAUUSD" and not TWELVE_DATA_API_KEY:
                                    continue
                                fingerprint_key="auto_signal_last_fingerprint_"+market_symbol.lower()
                                try:
                                    scan=await build_signal(signal_settings,market_symbol)
                                    candidate=scan.get("signal")
                                    if candidate:
                                        fingerprint="|".join([market_symbol,str(candidate.get("side")),str(candidate.get("timeframe")),str(candidate.get("signal_candle_time"))])
                                        previous=_get(db,user_id,fingerprint_key)
                                        if fingerprint and fingerprint!=previous:
                                            msg=("QUANTNEX · AUTO SIGNAL · "+market_symbol+" "+candidate["side"]+"\n"
                                                +"Signal TF: "+str(candidate["timeframe"])+"m · Trend TF: "+str(candidate["trend_timeframe"])+"m\n"
                                                +"Entry: "+str(candidate["entry"])+"\nSL: "+str(candidate["stop_loss"])+"\n"
                                                +"TP1: "+str(candidate["tp1"])+"\nTP2: "+str(candidate["tp2"])+"\nTP3: "+str(candidate["tp3"])+"\n"
                                                +"Confluence: "+str(candidate["score"])+"/10 (rule count, not win probability)\n"
                                                +"Confirmations: "+", ".join(candidate["confirmations"])+"\n"
                                                +"Signal only; verify spread, fees and execution. No order is placed.")
                                            await _send(client,token,chat_id,msg)
                                            _set(db,user_id,fingerprint_key,fingerprint)
                                            if market_symbol=="XAUUSD":
                                                _set(db,user_id,"active_signal",json.dumps({**candidate,"tp1_notified":False,"tp2_notified":False,"tp3_notified":False,"sl_notified":False}))
                                            db.commit()
                                    else:
                                        _set(db,user_id,fingerprint_key,"")
                                        db.commit()
                                except (MarketDataError,httpx.HTTPError,ValueError,KeyError) as exc:
                                    print(f"[QUANTNEX auto-signal] user {user_id} {market_symbol}: {exc}",flush=True)
                            last_monitor[auto_key]=now
                        last_monitor[user_id]=now
            except Exception:
                pass
            await asyncio.sleep(8)
