"""Read-only Binance USDⓈ-M Futures derivatives context adapters."""
from __future__ import annotations
import asyncio, math, re
from typing import Any
import httpx

FAPI_BASE = "https://fapi.binance.com"
DATA_BASE = "https://fapi.binance.com"
ALLOWED_OI_PERIODS = {"5m","15m","30m","1h","2h","4h","6h","12h","1d"}

class UsdmDerivativesError(ValueError):
    pass

def _symbol(value: str) -> str:
    normalized=str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,25}",normalized):
        raise UsdmDerivativesError("Invalid USDⓈ-M Futures symbol.")
    return normalized

def _number(value: Any, name: str, *, allow_zero=False) -> float:
    if isinstance(value,bool):
        raise UsdmDerivativesError(f"{name} must be numeric.")
    try: result=float(value)
    except (TypeError,ValueError,OverflowError):
        raise UsdmDerivativesError(f"{name} must be numeric.") from None
    if not math.isfinite(result) or (result < 0 if allow_zero else result <= 0):
        raise UsdmDerivativesError(f"{name} is outside valid numeric bounds.")
    return result

def _epoch_ms(value: Any, name: str) -> int:
    if isinstance(value,bool):
        raise UsdmDerivativesError(f"{name} must be integer milliseconds.")
    try: result=int(value)
    except (TypeError,ValueError,OverflowError):
        raise UsdmDerivativesError(f"{name} must be integer milliseconds.") from None
    if result<=0 or str(value).strip()!=str(result):
        raise UsdmDerivativesError(f"{name} must be positive integer milliseconds.")
    return result

async def _get_json(client, url, params):
    response=await client.get(url,params=params)
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,(dict,list)):
        raise UsdmDerivativesError("Binance Futures derivatives endpoint returned an invalid payload.")
    return data

async def fetch_usdm_derivatives_snapshot(client, symbol: str, *, oi_period: str="5m", oi_limit: int=30) -> dict[str,Any]:
    """Fetch premium/funding, current OI and bounded OI history from public USD-M endpoints."""
    normalized=_symbol(symbol)
    if oi_period not in ALLOWED_OI_PERIODS:
        raise UsdmDerivativesError("Choose a supported Futures open-interest period.")
    if isinstance(oi_limit,bool) or not isinstance(oi_limit,int) or not 1<=oi_limit<=30:
        raise UsdmDerivativesError("Open-interest history limit must be between 1 and 30.")
    premium, open_interest, history = await asyncio.gather(
        _get_json(client,F"{FAPI_BASE}/fapi/v1/premiumIndex",{"symbol":normalized}),
        _get_json(client,F"{FAPI_BASE}/fapi/v1/openInterest",{"symbol":normalized}),
        _get_json(client,F"{DATA_BASE}/futures/data/openInterestHist",{"symbol":normalized,"period":oi_period,"limit":oi_limit}),
    )
    if not isinstance(premium,dict) or not isinstance(open_interest,dict) or not isinstance(history,list):
        raise UsdmDerivativesError("Binance Futures derivatives payload shape is invalid.")
    if str(premium.get("symbol") or "").upper()!=normalized or str(open_interest.get("symbol") or "").upper()!=normalized:
        raise UsdmDerivativesError("Binance Futures derivatives symbol mismatch.")
    mark=_number(premium.get("markPrice"),"mark price")
    index=_number(premium.get("indexPrice"),"index price")
    funding=float(premium.get("lastFundingRate"))
    if not math.isfinite(funding):
        raise UsdmDerivativesError("Funding rate is not finite.")
    next_funding=_epoch_ms(premium.get("nextFundingTime"),"next funding time")
    premium_time=_epoch_ms(premium.get("time"),"premium timestamp")
    oi_amount=_number(open_interest.get("openInterest"),"open interest")
    oi_time=_epoch_ms(open_interest.get("time"),"open-interest timestamp")
    points=[]
    for row in history:
        if not isinstance(row,dict):
            continue
        stamp=_epoch_ms(row.get("timestamp"),"open-interest history timestamp")
        amount=_number(row.get("sumOpenInterest"),"historical open interest")
        value=_number(row.get("sumOpenInterestValue"),"historical open-interest value",allow_zero=True)
        points.append({"timestamp_ms":stamp,"open_interest":amount,"open_interest_value":value})
    points.sort(key=lambda item:item["timestamp_ms"])
    change_pct=None
    if len(points)>=2 and points[0]["open_interest"]>0:
        change_pct=(points[-1]["open_interest"]-points[0]["open_interest"])/points[0]["open_interest"]*100
    return {
        "market_type":"BINANCE_USDM_FUTURES","symbol":normalized,
        "mark_price":mark,"index_price":index,"mark_index_basis":mark-index,
        "mark_index_basis_pct":(mark-index)/index*100,
        "funding_rate":funding,"funding_rate_pct":funding*100,
        "next_funding_time_ms":next_funding,"premium_source_time_ms":premium_time,
        "open_interest":oi_amount,"open_interest_source_time_ms":oi_time,
        "open_interest_notional_estimate":oi_amount*mark,
        "open_interest_history":{"period":oi_period,"points":points,"change_pct":change_pct},
        "provenance":{
            "premium":"Binance USDⓈ-M /fapi/v1/premiumIndex",
            "open_interest":"Binance USDⓈ-M /fapi/v1/openInterest",
            "open_interest_history":"Binance USDⓈ-M /futures/data/openInterestHist",
            "history_limit":oi_limit,
        },
        "coverage":"PUBLIC_ENDPOINT_SNAPSHOT_AND_BOUNDED_HISTORY",
        "execution_enabled":False,
        "interpretation_note":"Funding, basis and open-interest changes are market context, not standalone directional signals or guaranteed liquidation indicators.",
    }
