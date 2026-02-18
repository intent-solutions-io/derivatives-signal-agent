"""
Bybit API v5 client for derivatives data.

Endpoints:
- /v5/market/funding/history -> FundingRateData
- /v5/market/open-interest -> OpenInterestData
- /v5/market/orderbook -> OrderBookData (with imbalance calculation)
- /v5/market/account-ratio -> LongShortRatioData
"""

import os
import time
import hmac
import hashlib
import logging
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from .http_client import HTTPClient

logger = logging.getLogger(__name__)


@dataclass
class FundingRateData:
    symbol: str
    funding_rate: str
    funding_rate_timestamp: str
    next_funding_time: Optional[str] = None

    @property
    def rate_pct(self) -> str:
        """Funding rate as percentage string."""
        try:
            return f"{float(self.funding_rate) * 100:.4f}%"
        except (ValueError, TypeError):
            return "N/A"


@dataclass
class OpenInterestData:
    symbol: str
    open_interest: str
    timestamp: str


@dataclass
class OrderBookData:
    symbol: str
    bids: List[List[str]]  # [[price, size], ...]
    asks: List[List[str]]
    timestamp: str

    @property
    def bid_depth(self) -> str:
        """Total bid volume as decimal string."""
        total = sum(float(b[1]) for b in self.bids)
        return f"{total:.4f}"

    @property
    def ask_depth(self) -> str:
        """Total ask volume as decimal string."""
        total = sum(float(a[1]) for a in self.asks)
        return f"{total:.4f}"

    @property
    def imbalance_ratio(self) -> str:
        """Bid/ask imbalance: >1 = more bids (bullish), <1 = more asks (bearish)."""
        bid_total = sum(float(b[1]) for b in self.bids)
        ask_total = sum(float(a[1]) for a in self.asks)
        if ask_total == 0:
            return "inf"
        return f"{bid_total / ask_total:.4f}"


@dataclass
class LongShortRatioData:
    symbol: str
    buy_ratio: str
    sell_ratio: str
    timestamp: str


class BybitClient:
    """Bybit API v5 client with HMAC SHA256 signing."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str = "https://api.bybit.com",
        rate_limit_rpm: int = 60,
        circuit_threshold: int = 5,
        circuit_backoff: int = 30,
        timeout: float = 10.0,
    ):
        self.api_key = api_key or os.getenv("BYBIT_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BYBIT_API_SECRET", "")
        self.http = HTTPClient(
            base_url=base_url,
            rate_limit_rpm=rate_limit_rpm,
            circuit_threshold=circuit_threshold,
            circuit_backoff=circuit_backoff,
            timeout=timeout,
        )

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, str]:
        """Generate HMAC SHA256 signature for Bybit v5 API."""
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"

        # Sort params and create query string
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sign_payload = f"{timestamp}{self.api_key}{recv_window}{param_str}"
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            sign_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
        }

    async def get_funding_rate(
        self, symbol: str, limit: int = 1
    ) -> Dict[str, Any]:
        """Get funding rate history for a symbol."""
        params = {
            "category": "linear",
            "symbol": symbol,
            "limit": str(limit),
        }
        headers = self._sign_params(params)
        result = await self.http.get(
            "/v5/market/funding/history",
            params=params,
            headers=headers,
            cache_ttl=60,
        )

        data = result["data"]
        entries = data.get("result", {}).get("list", [])

        parsed = []
        for entry in entries:
            parsed.append(FundingRateData(
                symbol=entry.get("symbol", symbol),
                funding_rate=entry.get("fundingRate", "0"),
                funding_rate_timestamp=entry.get("fundingRateTimestamp", ""),
                next_funding_time=entry.get("nextFundingTime"),
            ))

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_open_interest(
        self, symbol: str, interval: str = "1h", limit: int = 1
    ) -> Dict[str, Any]:
        """Get open interest for a symbol."""
        params = {
            "category": "linear",
            "symbol": symbol,
            "intervalTime": interval,
            "limit": str(limit),
        }
        headers = self._sign_params(params)
        result = await self.http.get(
            "/v5/market/open-interest",
            params=params,
            headers=headers,
            cache_ttl=60,
        )

        data = result["data"]
        entries = data.get("result", {}).get("list", [])

        parsed = []
        for entry in entries:
            parsed.append(OpenInterestData(
                symbol=entry.get("symbol", symbol),
                open_interest=entry.get("openInterest", "0"),
                timestamp=entry.get("timestamp", ""),
            ))

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_orderbook(
        self, symbol: str, depth: int = 25
    ) -> Dict[str, Any]:
        """Get orderbook with bid/ask imbalance calculation."""
        params = {
            "category": "linear",
            "symbol": symbol,
            "limit": str(depth),
        }
        result = await self.http.get(
            "/v5/market/orderbook",
            params=params,
            cache_ttl=15,
        )

        data = result["data"]
        book = data.get("result", {})

        parsed = OrderBookData(
            symbol=symbol,
            bids=book.get("b", []),
            asks=book.get("a", []),
            timestamp=str(book.get("ts", "")),
        )

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def get_long_short_ratio(
        self, symbol: str, period: str = "1h", limit: int = 1
    ) -> Dict[str, Any]:
        """Get account long/short ratio."""
        params = {
            "category": "linear",
            "symbol": symbol,
            "period": period,
            "limit": str(limit),
        }
        headers = self._sign_params(params)
        result = await self.http.get(
            "/v5/market/account-ratio",
            params=params,
            headers=headers,
            cache_ttl=60,
        )

        data = result["data"]
        entries = data.get("result", {}).get("list", [])

        parsed = []
        for entry in entries:
            parsed.append(LongShortRatioData(
                symbol=entry.get("symbol", symbol),
                buy_ratio=entry.get("buyRatio", "0"),
                sell_ratio=entry.get("sellRatio", "0"),
                timestamp=entry.get("timestamp", ""),
            ))

        return {
            "data": parsed,
            "stale": result.get("stale", False),
            "source": result.get("source", "api"),
        }

    async def health_check(self) -> bool:
        """Quick connectivity test."""
        try:
            result = await self.http.get(
                "/v5/market/funding/history",
                params={"category": "linear", "symbol": "BTCUSDT", "limit": "1"},
                use_cache=False,
            )
            return result["data"].get("retCode") == 0
        except Exception:
            return False
