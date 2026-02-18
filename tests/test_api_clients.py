"""Tests for API clients (Bybit, Coinglass, Claude) with mocked HTTP."""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

from tools.bybit_client import BybitClient, FundingRateData, OrderBookData, LongShortRatioData
from tools.coinglass_client import CoinglassClient, LiquidationData, CrossExchangeLSRatio
from tools.claude_client import ClaudeClient, CostTracker, AnalysisResult, ANALYSIS_SYSTEM_PROMPT


class TestBybitClient:
    def test_sign_params_produces_headers(self):
        client = BybitClient(api_key="test_key", api_secret="test_secret")
        headers = client._sign_params({"symbol": "BTCUSDT"})
        assert "X-BAPI-API-KEY" in headers
        assert "X-BAPI-SIGN" in headers
        assert headers["X-BAPI-API-KEY"] == "test_key"

    def test_sign_params_deterministic(self):
        client = BybitClient(api_key="key", api_secret="secret")
        # Same params at same time should produce same signature
        # (time changes, but the structure is correct)
        headers = client._sign_params({"a": "1", "b": "2"})
        assert len(headers["X-BAPI-SIGN"]) == 64  # SHA256 hex

    @pytest.mark.asyncio
    async def test_get_funding_rate_parses_response(self):
        client = BybitClient(api_key="test", api_secret="test")
        mock_response = {
            "data": {
                "retCode": 0,
                "result": {
                    "list": [{
                        "symbol": "BTCUSDT",
                        "fundingRate": "0.0001",
                        "fundingRateTimestamp": "1700000000",
                        "nextFundingTime": "1700003600",
                    }]
                }
            },
            "stale": False,
            "source": "api",
        }
        client.http.get = AsyncMock(return_value=mock_response)
        result = await client.get_funding_rate("BTCUSDT")
        assert len(result["data"]) == 1
        assert result["data"][0].funding_rate == "0.0001"
        assert result["data"][0].rate_pct == "0.0100%"

    @pytest.mark.asyncio
    async def test_get_orderbook_calculates_imbalance(self):
        client = BybitClient(api_key="test", api_secret="test")
        mock_response = {
            "data": {
                "result": {
                    "b": [["50000", "10"], ["49999", "5"]],
                    "a": [["50001", "8"], ["50002", "7"]],
                    "ts": "1700000000",
                }
            },
            "stale": False,
            "source": "api",
        }
        client.http.get = AsyncMock(return_value=mock_response)
        result = await client.get_orderbook("BTCUSDT")
        book = result["data"]
        assert book.bid_depth == "15.0000"
        assert book.ask_depth == "15.0000"
        assert book.imbalance_ratio == "1.0000"

    @pytest.mark.asyncio
    async def test_get_long_short_ratio(self):
        client = BybitClient(api_key="test", api_secret="test")
        mock_response = {
            "data": {
                "result": {
                    "list": [{
                        "symbol": "BTCUSDT",
                        "buyRatio": "0.55",
                        "sellRatio": "0.45",
                        "timestamp": "1700000000",
                    }]
                }
            },
            "stale": False,
            "source": "api",
        }
        client.http.get = AsyncMock(return_value=mock_response)
        result = await client.get_long_short_ratio("BTCUSDT")
        assert result["data"][0].buy_ratio == "0.55"
        assert result["data"][0].sell_ratio == "0.45"


class TestFundingRateData:
    def test_rate_pct(self):
        frd = FundingRateData(
            symbol="BTCUSDT", funding_rate="0.0001",
            funding_rate_timestamp="123"
        )
        assert frd.rate_pct == "0.0100%"

    def test_rate_pct_negative(self):
        frd = FundingRateData(
            symbol="BTCUSDT", funding_rate="-0.0005",
            funding_rate_timestamp="123"
        )
        assert frd.rate_pct == "-0.0500%"


class TestOrderBookData:
    def test_imbalance_more_bids(self):
        book = OrderBookData(
            symbol="BTCUSDT",
            bids=[["50000", "20"]],
            asks=[["50001", "10"]],
            timestamp="123",
        )
        assert book.imbalance_ratio == "2.0000"

    def test_imbalance_empty_asks(self):
        book = OrderBookData(
            symbol="BTCUSDT", bids=[["50000", "10"]], asks=[], timestamp="123"
        )
        assert book.imbalance_ratio == "inf"


class TestCoinglassClient:
    def test_strip_usdt(self):
        client = CoinglassClient(api_key="test")
        assert client._strip_usdt("BTCUSDT") == "BTC"
        assert client._strip_usdt("BTC") == "BTC"

    @pytest.mark.asyncio
    async def test_get_aggregated_funding(self):
        client = CoinglassClient(api_key="test")
        mock_response = {
            "data": {
                "data": [
                    {"exchangeName": "Binance", "rate": "0.0001"},
                    {"exchangeName": "OKX", "rate": "0.0002"},
                ],
                "dateList": ["1700000000"],
            },
            "stale": False,
            "source": "api",
        }
        client.http.get = AsyncMock(return_value=mock_response)
        result = await client.get_aggregated_funding("BTCUSDT")
        assert result["data"].symbol == "BTCUSDT"
        assert len(result["data"].exchanges) == 2
        assert result["data"].average_rate == "0.00015000"

    @pytest.mark.asyncio
    async def test_get_liquidations(self):
        client = CoinglassClient(api_key="test")
        mock_response = {
            "data": {
                "data": [{
                    "longLiquidationUsd": "5000000",
                    "shortLiquidationUsd": "3000000",
                }]
            },
            "stale": False,
            "source": "api",
        }
        client.http.get = AsyncMock(return_value=mock_response)
        result = await client.get_liquidations("BTCUSDT")
        liq = result["data"]
        assert liq.long_liquidations == "5000000"
        assert liq.short_liquidations == "3000000"
        assert liq.total_liquidations == "8000000.0"


class TestLiquidationData:
    def test_liquidation_bias_bearish(self):
        liq = LiquidationData(
            symbol="BTCUSDT",
            long_liquidations="7000000",
            short_liquidations="3000000",
            total_liquidations="10000000",
            timestamp="",
        )
        # More longs liquidated = bearish bias
        assert float(liq.liquidation_bias) > 0

    def test_liquidation_bias_neutral(self):
        liq = LiquidationData(
            symbol="BTCUSDT",
            long_liquidations="0",
            short_liquidations="0",
            total_liquidations="0",
            timestamp="",
        )
        assert liq.liquidation_bias == "0.0000"


class TestCostTracker:
    def test_records_cost(self):
        tracker = CostTracker()
        cost = tracker.record("claude-sonnet-4-5-20250929", 1000, 500)
        assert cost > 0
        assert tracker.total_requests == 1
        assert tracker.total_input_tokens == 1000
        assert tracker.total_output_tokens == 500

    def test_accumulates(self):
        tracker = CostTracker()
        tracker.record("claude-sonnet-4-5-20250929", 1000, 500)
        tracker.record("claude-sonnet-4-5-20250929", 2000, 1000)
        assert tracker.total_requests == 2
        assert tracker.total_input_tokens == 3000

    def test_unknown_model_uses_default(self):
        tracker = CostTracker()
        cost = tracker.record("claude-unknown-model", 1000000, 0)
        # Should use default pricing (3.00 per million input)
        assert abs(cost - 3.00) < 0.01


class TestClaudeClient:
    def test_build_prompt_with_all_data(self):
        client = ClaudeClient(api_key="test")
        market_data = {
            "symbol": "BTCUSDT",
            "funding": {"rate": "0.0001"},
            "open_interest": {"oi": "1000000"},
            "orderbook": {"imbalance": "1.2"},
            "long_short_ratio": {"ratio": "1.1"},
            "aggregated_funding": {"avg": "0.00015"},
            "aggregated_oi": {"total": "5000000"},
            "liquidations": {"long": "100000"},
            "cross_exchange_ls": {"ratio": "1.05"},
        }
        prompt = client._build_prompt(market_data, [])
        assert "BTCUSDT" in prompt
        assert "Funding Rate" in prompt
        assert "Orderbook" in prompt

    def test_build_prompt_with_failed_sources(self):
        client = ClaudeClient(api_key="test")
        prompt = client._build_prompt(
            {"symbol": "BTCUSDT", "funding": {"rate": "0.0001"}},
            ["coinglass_funding", "coinglass_oi"]
        )
        assert "Missing Data Sources" in prompt
        assert "coinglass_funding" in prompt

    def test_system_prompt_contains_rules(self):
        assert "-100" in ANALYSIS_SYSTEM_PROMPT
        assert "+100" in ANALYSIS_SYSTEM_PROMPT
        assert "JSON" in ANALYSIS_SYSTEM_PROMPT
        assert "NEVER" in ANALYSIS_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_analyze_parses_valid_response(self):
        client = ClaudeClient(api_key="test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": json.dumps({
                "symbol": "BTCUSDT",
                "score": 42,
                "bias": "bullish",
                "confidence": "medium",
                "findings": ["Funding rate positive"],
                "warnings": [],
                "data_quality": "complete",
            })}],
            "usage": {"input_tokens": 500, "output_tokens": 200},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await client.analyze({"symbol": "BTCUSDT", "funding": {}})

        assert result.score == 42
        assert result.bias == "bullish"
        assert result.cost_estimate_usd > 0

    @pytest.mark.asyncio
    async def test_analyze_handles_json_error(self):
        client = ClaudeClient(api_key="test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": "This is not JSON"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await client.analyze({"symbol": "BTCUSDT"})

        assert result.score == 0
        assert result.bias == "neutral"
        assert result.data_quality == "degraded"

    def test_get_cost_summary(self):
        client = ClaudeClient(api_key="test")
        client.cost_tracker.record("claude-sonnet-4-5-20250929", 1000, 500)
        summary = client.get_cost_summary()
        assert summary["total_requests"] == 1
        assert float(summary["total_cost_usd"]) > 0

    @pytest.mark.asyncio
    async def test_analyze_clamps_score(self):
        client = ClaudeClient(api_key="test")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": json.dumps({
                "symbol": "BTCUSDT",
                "score": 999,  # Out of range
                "bias": "strong_bullish",
                "confidence": "high",
                "findings": [],
                "warnings": [],
                "data_quality": "complete",
            })}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await client.analyze({"symbol": "BTCUSDT"})

        assert result.score == 100  # Clamped to max
