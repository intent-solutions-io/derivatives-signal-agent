"""
Coinglass API client for aggregated derivatives data.

Endpoints:
- Aggregated funding rates -> AggregatedFundingData
- Aggregated open interest -> AggregatedOIData
- Liquidations -> LiquidationData
- Cross-exchange long/short ratio -> CrossExchangeLSRatio
"""

import os
import logging
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .http_client import HTTPClient

logger = logging.getLogger(__name__)


@dataclass
class AggregatedFundingData:
    symbol: str
    exchanges: List[Dict[str, str]]
    average_rate: str
    timestamp: str


@dataclass
class AggregatedOIData:
    symbol: str
    total_open_interest: str
    open_interest_change_pct: str
    exchanges: List[Dict[str, str]]
    timestamp: str


@dataclass
class LiquidationData:
    symbol: str
    long_liquidations: str
    short_liquidations: str
    total_liquidations: str
    timestamp: str

    @property
    def liquidation_bias(self) -> str:
        """Positive = more longs liquidated (bearish), negative = more shorts (bullish)."""
        try:
            long_val = float(self.long_liquidations)
            short_val = float(self.short_liquidations)
            total = long_val + short_val
            if total == 0:
                return "0.0000"
            return f"{(long_val - short_val) / total:.4f}"
        except (ValueError, TypeError):
            return "0.0000"


@dataclass
class CrossExchangeLSRatio:
    symbol: str
    long_ratio: str
    short_ratio: str
    long_short_ratio: str
    timestamp: str


class CoinglassClient:
    """Coinglass API client for aggregated derivatives data."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://open-api-v3.coinglass.com",
        rate_limit_rpm: int = 30,
        circuit_threshold: int = 5,
        circuit_backoff: int = 30,
        timeout: float = 10.0,
    ):
        self.api_key = api_key or os.getenv("COINGLASS_API_KEY", "")
        self.http = HTTPClient(
            base_url=base_url,
            default_headers={
                "accept": "application/json",
                "CG-API-KEY": self.api_key,
            },
            rate_limit_rpm=rate_limit_rpm,
            circuit_threshold=circuit_threshold,
            circuit_backoff=circuit_backoff,
            timeout=timeout,
        )

    def _strip_usdt(self, symbol: str) -> str:
        """Strip USDT suffix for Coinglass symbol format."""
        if symbol.endswith("USDT"):
            return symbol[:-4]
        return symbol

    async def get_aggregated_funding(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated funding rates across exchanges."""
        coin = self._strip_usdt(symbol)
        result = await self.http.get(
            "/api/futures/funding/current",
            params={"symbol": coin},
            cache_ttl=60,
        )

        data = result["data"]
        items = data.get("data", [])

        exchanges = []
        rates = []
        for item in items:
            rate = item.get("rate", "0")
            exchanges.append({
                "exchange": item.get("exchangeName", "unknown"),
                "rate": rate,
            })
            try:
                rates.append(float(rate))
            except (ValueError, TypeError):
                pass

        avg_rate = f"{sum(rates) / len(rates):.8f}" if rates else "0"

        parsed = AggregatedFundingData(
            symbol=symbol,
            exchanges=exchanges,
            average_rate=avg_rate,
            timestamp=str(data.get("dateList", [""])[0]) if data.get("dateList") else "",
        )

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_aggregated_oi(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated open interest across exchanges."""
        coin = self._strip_usdt(symbol)
        result = await self.http.get(
            "/api/futures/openInterest/chart",
            params={"symbol": coin, "interval": "0", "range": "1"},
            cache_ttl=60,
        )

        data = result["data"]
        prices = data.get("data", [])

        exchanges = []
        total_oi = "0"
        change_pct = "0"
        if prices:
            latest = prices[-1] if isinstance(prices, list) else prices
            if isinstance(latest, dict):
                total_oi = str(latest.get("openInterest", "0"))
                for k, v in latest.items():
                    if k not in ("openInterest", "time", "price"):
                        exchanges.append({"exchange": k, "oi": str(v)})

        parsed = AggregatedOIData(
            symbol=symbol,
            total_open_interest=total_oi,
            open_interest_change_pct=change_pct,
            exchanges=exchanges,
            timestamp="",
        )

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_liquidations(self, symbol: str) -> Dict[str, Any]:
        """Get liquidation data."""
        coin = self._strip_usdt(symbol)
        result = await self.http.get(
            "/api/futures/liquidation/chart",
            params={"symbol": coin, "interval": "1h", "range": "1"},
            cache_ttl=60,
        )

        data = result["data"]
        items = data.get("data", [])

        long_liq = "0"
        short_liq = "0"
        if items and isinstance(items, list) and len(items) > 0:
            latest = items[-1] if isinstance(items[-1], dict) else {}
            long_liq = str(latest.get("longLiquidationUsd", "0"))
            short_liq = str(latest.get("shortLiquidationUsd", "0"))

        try:
            total = str(float(long_liq) + float(short_liq))
        except (ValueError, TypeError):
            total = "0"

        parsed = LiquidationData(
            symbol=symbol,
            long_liquidations=long_liq,
            short_liquidations=short_liq,
            total_liquidations=total,
            timestamp="",
        )

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_long_short_ratio(self, symbol: str) -> Dict[str, Any]:
        """Get cross-exchange long/short ratio."""
        coin = self._strip_usdt(symbol)
        result = await self.http.get(
            "/api/futures/globalLongShortAccountRatio/chart",
            params={"symbol": coin, "interval": "1h", "range": "1"},
            cache_ttl=60,
        )

        data = result["data"]
        items = data.get("data", [])

        long_ratio = "0.5"
        short_ratio = "0.5"
        ls_ratio = "1.0"
        if items and isinstance(items, list) and len(items) > 0:
            latest = items[-1] if isinstance(items[-1], dict) else {}
            long_ratio = str(latest.get("longRate", "0.5"))
            short_ratio = str(latest.get("shortRate", "0.5"))
            try:
                sr = float(short_ratio)
                ls_ratio = f"{float(long_ratio) / sr:.4f}" if sr > 0 else "inf"
            except (ValueError, TypeError):
                ls_ratio = "1.0"

        parsed = CrossExchangeLSRatio(
            symbol=symbol,
            long_ratio=long_ratio,
            short_ratio=short_ratio,
            long_short_ratio=ls_ratio,
            timestamp="",
        )

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def health_check(self) -> bool:
        """Quick connectivity test."""
        try:
            result = await self.http.get(
                "/api/futures/funding/current",
                params={"symbol": "BTC"},
                use_cache=False,
            )
            data = result["data"]
            return data.get("code") == "0" or data.get("success", False)
        except Exception:
            return False
