import asyncio
import pytest
from app.binance_usdm_derivatives import UsdmDerivativesError, fetch_usdm_derivatives_snapshot

class FakeResponse:
    def __init__(self,payload): self.payload=payload
    def raise_for_status(self): pass
    def json(self): return self.payload

class FakeClient:
    async def get(self,url,params):
        if url.endswith("/premiumIndex"):
            return FakeResponse({"symbol":"BTCUSDT","markPrice":"90010","indexPrice":"90000","lastFundingRate":"0.0001","nextFundingTime":"1700003600000","time":"1700000000000"})
        if url.endswith("/openInterest"):
            return FakeResponse({"symbol":"BTCUSDT","openInterest":"1234.5","time":"1700000000001"})
        return FakeResponse([
            {"symbol":"BTCUSDT","sumOpenInterest":"1200","sumOpenInterestValue":"108000000","timestamp":"1699999700000"},
            {"symbol":"BTCUSDT","sumOpenInterest":"1230","sumOpenInterestValue":"110700000","timestamp":"1700000000000"},
        ])

def test_usdm_derivatives_snapshot_normalizes_funding_basis_and_oi_change():
    result=asyncio.run(fetch_usdm_derivatives_snapshot(FakeClient(),"BTCUSDT"))
    assert result["market_type"]=="BINANCE_USDM_FUTURES"
    assert result["mark_price"]==90010
    assert result["mark_index_basis"]==10
    assert result["funding_rate_pct"]==pytest.approx(0.01)
    assert result["open_interest"]==1234.5
    assert result["open_interest_history"]["change_pct"]==pytest.approx(2.5)
    assert result["execution_enabled"] is False

def test_usdm_derivatives_rejects_invalid_symbol_period_and_limits():
    async def run():
        client=FakeClient()
        with pytest.raises(UsdmDerivativesError):
            await fetch_usdm_derivatives_snapshot(client,"BTC USDT")
        with pytest.raises(UsdmDerivativesError):
            await fetch_usdm_derivatives_snapshot(client,"BTCUSDT",oi_period="1m")
        with pytest.raises(UsdmDerivativesError):
            await fetch_usdm_derivatives_snapshot(client,"BTCUSDT",oi_limit=31)
    asyncio.run(run())

def test_usdm_derivatives_rejects_symbol_mismatch_and_nonfinite_values():
    class BadClient(FakeClient):
        async def get(self,url,params):
            if url.endswith("/premiumIndex"):
                return FakeResponse({"symbol":"ETHUSDT","markPrice":"NaN","indexPrice":"1","lastFundingRate":"0","nextFundingTime":"1700003600000","time":"1700000000000"})
            return await super().get(url,params)
    with pytest.raises(UsdmDerivativesError):
        asyncio.run(fetch_usdm_derivatives_snapshot(BadClient(),"BTCUSDT"))
