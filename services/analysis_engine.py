"""
Analysis engine — orchestrates data fetching, aggregation, and Claude analysis.

Flow: fetch 8 sources in parallel → MarketSnapshot → Claude → SignalReport
Partial data: if some sources fail, analysis proceeds with available data.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

from config.schema import ConfigSchema
from tools.bybit_client import BybitClient
from tools.coinglass_client import CoinglassClient
from tools.claude_client import ClaudeClient, AnalysisResult
from services.storage_service import create_storage
from storage.base import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class MarketSnapshot:
    """Aggregated market data from all sources."""
    symbol: str
    funding: Optional[Dict] = None
    open_interest: Optional[Dict] = None
    orderbook: Optional[Dict] = None
    long_short_ratio: Optional[Dict] = None
    aggregated_funding: Optional[Dict] = None
    aggregated_oi: Optional[Dict] = None
    liquidations: Optional[Dict] = None
    cross_exchange_ls: Optional[Dict] = None
    sources_failed: List[str] = field(default_factory=list)
    sources_stale: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def source_count(self) -> int:
        count = 0
        for attr in ("funding", "open_interest", "orderbook", "long_short_ratio",
                      "aggregated_funding", "aggregated_oi", "liquidations", "cross_exchange_ls"):
            if getattr(self, attr) is not None:
                count += 1
        return count

    @property
    def has_any_data(self) -> bool:
        return self.source_count > 0

    def to_dict(self) -> Dict[str, Any]:
        result = {"symbol": self.symbol}
        for attr in ("funding", "open_interest", "orderbook", "long_short_ratio",
                      "aggregated_funding", "aggregated_oi", "liquidations", "cross_exchange_ls"):
            val = getattr(self, attr)
            if val is not None:
                result[attr] = val
        return result


@dataclass
class SignalReport:
    """Complete analysis output."""
    id: str
    symbol: str
    score: int
    bias: str
    confidence: str
    findings: List[str]
    warnings: List[str]
    data_quality: str
    cost_estimate_usd: float
    model: str
    disclaimer: str
    stale: bool
    sources_available: int
    sources_failed: List[str]
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "score": self.score,
            "bias": self.bias,
            "confidence": self.confidence,
            "findings": self.findings,
            "warnings": self.warnings,
            "data_quality": self.data_quality,
            "cost_estimate_usd": f"{self.cost_estimate_usd:.6f}",
            "model": self.model,
            "disclaimer": self.disclaimer,
            "stale": self.stale,
            "sources_available": self.sources_available,
            "sources_failed": self.sources_failed,
            "timestamp": self.timestamp,
        }


class AnalysisEngine:
    """Orchestrates data fetch → Claude analysis → signal output."""

    def __init__(self, config: ConfigSchema):
        self.config = config
        self.bybit = BybitClient(
            base_url=config.bybit.base_url,
            rate_limit_rpm=config.rate_limits.bybit_requests_per_minute,
            circuit_threshold=config.rate_limits.circuit_breaker_failures,
            circuit_backoff=config.rate_limits.circuit_breaker_backoff_seconds,
            timeout=config.bybit.timeout_seconds,
        )
        self.coinglass = CoinglassClient(
            base_url=config.coinglass.base_url,
            rate_limit_rpm=config.rate_limits.coinglass_requests_per_minute,
            circuit_threshold=config.rate_limits.circuit_breaker_failures,
            circuit_backoff=config.rate_limits.circuit_breaker_backoff_seconds,
            timeout=config.coinglass.timeout_seconds,
        )
        self.claude = ClaudeClient(
            model=config.claude.model,
            max_tokens=config.claude.max_tokens,
            temperature=config.claude.temperature,
        )
        self.storage: StorageBackend = create_storage(config.storage)
        self._analysis_count_today = 0
        self._analysis_date = datetime.now(timezone.utc).date()

    async def initialize(self) -> None:
        """Initialize storage backend."""
        await self.storage.initialize()

    def _check_daily_limit(self) -> bool:
        """Enforce max analyses per day."""
        today = datetime.now(timezone.utc).date()
        if today != self._analysis_date:
            self._analysis_count_today = 0
            self._analysis_date = today
        return self._analysis_count_today < self.config.guardrails.max_analyses_per_day

    async def _fetch_bybit_data(self, symbol: str, snapshot: MarketSnapshot) -> None:
        """Fetch all Bybit data for a symbol. Failures are recorded, not raised."""
        # Funding rate
        try:
            result = await self.bybit.get_funding_rate(symbol)
            data = result["data"]
            if data:
                entry = data[0]
                snapshot.funding = {
                    "rate": entry.funding_rate,
                    "rate_pct": entry.rate_pct,
                    "timestamp": entry.funding_rate_timestamp,
                }
                if result.get("stale"):
                    snapshot.sources_stale.append("bybit_funding")
        except Exception as e:
            snapshot.sources_failed.append("bybit_funding")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "bybit_funding", "error": str(e)
            }))

        # Open interest
        try:
            result = await self.bybit.get_open_interest(symbol)
            data = result["data"]
            if data:
                entry = data[0]
                snapshot.open_interest = {
                    "value": entry.open_interest,
                    "timestamp": entry.timestamp,
                }
                if result.get("stale"):
                    snapshot.sources_stale.append("bybit_oi")
        except Exception as e:
            snapshot.sources_failed.append("bybit_oi")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "bybit_oi", "error": str(e)
            }))

        # Orderbook
        try:
            result = await self.bybit.get_orderbook(symbol, depth=self.config.analysis.orderbook_depth)
            book = result["data"]
            snapshot.orderbook = {
                "bid_depth": book.bid_depth,
                "ask_depth": book.ask_depth,
                "imbalance_ratio": book.imbalance_ratio,
                "bid_levels": len(book.bids),
                "ask_levels": len(book.asks),
            }
            if result.get("stale"):
                snapshot.sources_stale.append("bybit_orderbook")
        except Exception as e:
            snapshot.sources_failed.append("bybit_orderbook")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "bybit_orderbook", "error": str(e)
            }))

        # Long/short ratio
        try:
            result = await self.bybit.get_long_short_ratio(symbol)
            data = result["data"]
            if data:
                entry = data[0]
                snapshot.long_short_ratio = {
                    "buy_ratio": entry.buy_ratio,
                    "sell_ratio": entry.sell_ratio,
                }
                if result.get("stale"):
                    snapshot.sources_stale.append("bybit_ls")
        except Exception as e:
            snapshot.sources_failed.append("bybit_ls")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "bybit_ls", "error": str(e)
            }))

    async def _fetch_coinglass_data(self, symbol: str, snapshot: MarketSnapshot) -> None:
        """Fetch all Coinglass data. Failures are recorded, not raised."""
        # Aggregated funding
        try:
            result = await self.coinglass.get_aggregated_funding(symbol)
            data = result["data"]
            snapshot.aggregated_funding = {
                "average_rate": data.average_rate,
                "exchange_count": len(data.exchanges),
                "exchanges": data.exchanges[:5],  # Top 5
            }
            if result.get("stale"):
                snapshot.sources_stale.append("cg_funding")
        except Exception as e:
            snapshot.sources_failed.append("cg_funding")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "cg_funding", "error": str(e)
            }))

        # Aggregated OI
        try:
            result = await self.coinglass.get_aggregated_oi(symbol)
            data = result["data"]
            snapshot.aggregated_oi = {
                "total_oi": data.total_open_interest,
                "change_pct": data.open_interest_change_pct,
            }
            if result.get("stale"):
                snapshot.sources_stale.append("cg_oi")
        except Exception as e:
            snapshot.sources_failed.append("cg_oi")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "cg_oi", "error": str(e)
            }))

        # Liquidations
        try:
            result = await self.coinglass.get_liquidations(symbol)
            data = result["data"]
            snapshot.liquidations = {
                "long_usd": data.long_liquidations,
                "short_usd": data.short_liquidations,
                "total_usd": data.total_liquidations,
                "bias": data.liquidation_bias,
            }
            if result.get("stale"):
                snapshot.sources_stale.append("cg_liquidations")
        except Exception as e:
            snapshot.sources_failed.append("cg_liquidations")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "cg_liquidations", "error": str(e)
            }))

        # Cross-exchange L/S
        try:
            result = await self.coinglass.get_long_short_ratio(symbol)
            data = result["data"]
            snapshot.cross_exchange_ls = {
                "long_ratio": data.long_ratio,
                "short_ratio": data.short_ratio,
                "ls_ratio": data.long_short_ratio,
            }
            if result.get("stale"):
                snapshot.sources_stale.append("cg_ls")
        except Exception as e:
            snapshot.sources_failed.append("cg_ls")
            logger.warning(json.dumps({
                "severity": "WARNING", "component": "analysis_engine",
                "event": "source_failed", "source": "cg_ls", "error": str(e)
            }))

    async def fetch_market_data(self, symbol: str) -> MarketSnapshot:
        """Fetch all market data for a symbol in parallel."""
        snapshot = MarketSnapshot(symbol=symbol)

        await asyncio.gather(
            self._fetch_bybit_data(symbol, snapshot),
            self._fetch_coinglass_data(symbol, snapshot),
            return_exceptions=True,
        )

        logger.info(json.dumps({
            "severity": "INFO",
            "component": "analysis_engine",
            "event": "data_fetched",
            "symbol": symbol,
            "sources_available": snapshot.source_count,
            "sources_failed": snapshot.sources_failed,
            "sources_stale": snapshot.sources_stale,
        }))

        return snapshot

    async def analyze_symbol(self, symbol: str) -> Optional[SignalReport]:
        """Full pipeline: fetch → Claude → store → return."""
        if not self._check_daily_limit():
            logger.warning(json.dumps({
                "severity": "WARNING",
                "component": "analysis_engine",
                "event": "daily_limit_reached",
                "count": self._analysis_count_today,
            }))
            return None

        # Fetch market data
        snapshot = await self.fetch_market_data(symbol)

        if not snapshot.has_any_data:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "analysis_engine",
                "event": "no_data_available",
                "symbol": symbol,
                "sources_failed": snapshot.sources_failed,
            }))
            return None

        # Run Claude analysis
        analysis = await self.claude.analyze(
            market_data=snapshot.to_dict(),
            sources_failed=snapshot.sources_failed,
        )

        self._analysis_count_today += 1

        # Build signal report
        report = SignalReport(
            id=str(uuid.uuid4()),
            symbol=symbol,
            score=analysis.score,
            bias=analysis.bias,
            confidence=analysis.confidence,
            findings=analysis.findings,
            warnings=analysis.warnings,
            data_quality=analysis.data_quality,
            cost_estimate_usd=analysis.cost_estimate_usd,
            model=analysis.model,
            disclaimer=self.config.disclaimer.text,
            stale=len(snapshot.sources_stale) > 0,
            sources_available=snapshot.source_count,
            sources_failed=snapshot.sources_failed,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Store signal
        try:
            await self.storage.store(report.to_dict())
        except Exception as e:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "analysis_engine",
                "event": "storage_failed",
                "symbol": symbol,
                "error": str(e),
            }))

        logger.info(json.dumps({
            "severity": "INFO",
            "component": "analysis_engine",
            "event": "analysis_complete",
            "symbol": symbol,
            "score": report.score,
            "bias": report.bias,
            "confidence": report.confidence,
            "cost_usd": f"{report.cost_estimate_usd:.6f}",
        }))

        return report

    async def analyze_all(self) -> List[SignalReport]:
        """Analyze all configured symbols."""
        reports = []
        for symbol in self.config.analysis.symbols:
            report = await self.analyze_symbol(symbol)
            if report:
                reports.append(report)
        return reports

    def get_cost_summary(self) -> Dict[str, Any]:
        return self.claude.get_cost_summary()
