"""Tests for analysis engine and notification dispatcher."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.analysis_engine import (
    AnalysisEngine, MarketSnapshot, SignalReport
)
from services.notification_dispatcher import (
    NotificationDispatcher, NotificationResult,
    _score_color, _score_emoji, _bias_label,
)
from config.schema import (
    ConfigSchema, NotificationConfig, NotificationChannel,
    SlackConfig,
)


class TestMarketSnapshot:
    def test_empty_snapshot(self):
        snap = MarketSnapshot(symbol="BTCUSDT")
        assert snap.source_count == 0
        assert not snap.has_any_data

    def test_partial_snapshot(self):
        snap = MarketSnapshot(
            symbol="BTCUSDT",
            funding={"rate": "0.0001"},
            orderbook={"imbalance": "1.2"},
        )
        assert snap.source_count == 2
        assert snap.has_any_data

    def test_full_snapshot(self):
        snap = MarketSnapshot(
            symbol="BTCUSDT",
            funding={}, open_interest={}, orderbook={}, long_short_ratio={},
            aggregated_funding={}, aggregated_oi={}, liquidations={}, cross_exchange_ls={},
        )
        assert snap.source_count == 8

    def test_to_dict(self):
        snap = MarketSnapshot(
            symbol="BTCUSDT",
            funding={"rate": "0.0001"},
        )
        d = snap.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert "funding" in d
        assert "orderbook" not in d  # None excluded

    def test_sources_failed_tracked(self):
        snap = MarketSnapshot(symbol="BTCUSDT")
        snap.sources_failed.append("bybit_funding")
        snap.sources_stale.append("cg_oi")
        assert "bybit_funding" in snap.sources_failed
        assert "cg_oi" in snap.sources_stale


class TestSignalReport:
    def test_to_dict(self):
        report = SignalReport(
            id="test-123",
            symbol="BTCUSDT",
            score=42,
            bias="bullish",
            confidence="medium",
            findings=["Finding 1"],
            warnings=[],
            data_quality="complete",
            cost_estimate_usd=0.001234,
            model="claude-sonnet-4-5-20250929",
            disclaimer="Not financial advice.",
            stale=False,
            sources_available=8,
            sources_failed=[],
            timestamp="2025-01-01T00:00:00Z",
        )
        d = report.to_dict()
        assert d["score"] == 42
        assert d["cost_estimate_usd"] == "0.001234"
        assert d["disclaimer"] == "Not financial advice."


class TestScoreFormatting:
    def test_bullish_color(self):
        assert _score_color(50) == "#2ecc71"

    def test_bearish_color(self):
        assert _score_color(-50) == "#e74c3c"

    def test_neutral_color(self):
        assert _score_color(0) == "#f39c12"

    def test_bullish_emoji(self):
        assert _score_emoji(50) == "🟢"

    def test_bearish_emoji(self):
        assert _score_emoji(-50) == "🔴"

    def test_neutral_emoji(self):
        assert _score_emoji(0) == "⚪"

    def test_bias_labels(self):
        assert _bias_label("strong_bullish") == "STRONG BULLISH"
        assert _bias_label("bearish") == "BEARISH"
        assert _bias_label("neutral") == "NEUTRAL"
        assert _bias_label("unknown") == "UNKNOWN"


class TestNotificationDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_slack_success(self):
        config = NotificationConfig(
            channels=[NotificationChannel.SLACK],
            slack=SlackConfig(webhook_url="https://hooks.slack.com/test"),
        )
        dispatcher = NotificationDispatcher(config)

        signal = {
            "symbol": "BTCUSDT",
            "score": 42,
            "bias": "bullish",
            "confidence": "medium",
            "findings": ["Test finding"],
            "warnings": [],
            "data_quality": "complete",
            "cost_estimate_usd": "0.001",
            "disclaimer": "Not financial advice.",
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            results = await dispatcher.dispatch(signal)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].channel == "slack"

    @pytest.mark.asyncio
    async def test_dispatch_slack_no_url(self):
        config = NotificationConfig(
            channels=[NotificationChannel.SLACK],
            slack=SlackConfig(webhook_url=None),
        )
        dispatcher = NotificationDispatcher(config)
        results = await dispatcher.dispatch({"symbol": "TEST", "score": 0})
        assert results[0].success is False
        assert "No Slack webhook" in results[0].message

    @pytest.mark.asyncio
    async def test_dispatch_webhook_no_url(self):
        config = NotificationConfig(channels=[NotificationChannel.WEBHOOK])
        dispatcher = NotificationDispatcher(config)
        results = await dispatcher.dispatch({"symbol": "TEST"})
        assert results[0].success is False

    @pytest.mark.asyncio
    async def test_dispatch_email_no_smtp(self):
        config = NotificationConfig(channels=[NotificationChannel.EMAIL])
        dispatcher = NotificationDispatcher(config)
        results = await dispatcher.dispatch({"symbol": "TEST"})
        assert results[0].success is False

    @pytest.mark.asyncio
    async def test_dispatch_telegram_no_chat(self):
        config = NotificationConfig(channels=[NotificationChannel.TELEGRAM])
        dispatcher = NotificationDispatcher(config)
        results = await dispatcher.dispatch({"symbol": "TEST"})
        assert results[0].success is False


class TestAnalysisEngine:
    def test_daily_limit_check(self):
        config = ConfigSchema()
        config.guardrails.max_analyses_per_day = 5
        engine = AnalysisEngine(config)
        assert engine._check_daily_limit()

        engine._analysis_count_today = 5
        assert not engine._check_daily_limit()

    def test_daily_limit_resets(self):
        from datetime import date
        config = ConfigSchema()
        engine = AnalysisEngine(config)
        engine._analysis_count_today = 999
        engine._analysis_date = date(2020, 1, 1)  # Old date
        assert engine._check_daily_limit()
        assert engine._analysis_count_today == 0
