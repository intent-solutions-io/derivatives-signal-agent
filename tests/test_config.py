"""Tests for configuration schema and loader."""

import pytest
import tempfile
from pathlib import Path

import yaml

from config.schema import (
    ConfigSchema, BybitConfig, CoinglassConfig, ClaudeConfig,
    AnalysisConfig, NotificationConfig, StorageConfig, CacheConfig,
    RateLimitConfig, ScheduleConfig, DisclaimerConfig, GuardrailsConfig,
    NotificationChannel, StorageBackendType, SlackConfig,
)
from config.loader import load_config, validate_config


class TestConfigSchema:
    """Test Pydantic schema validation."""

    def test_default_config_valid(self):
        config = ConfigSchema()
        assert config.version == "1.0.0"
        assert config.guardrails.read_only is True
        assert config.storage.backend == StorageBackendType.SQLITE

    def test_bybit_config_defaults(self):
        bybit = BybitConfig()
        assert bybit.base_url == "https://api.bybit.com"
        assert bybit.api_key_env == "BYBIT_API_KEY"
        assert bybit.timeout_seconds == 10.0

    def test_coinglass_config_defaults(self):
        cg = CoinglassConfig()
        assert cg.base_url == "https://open-api-v3.coinglass.com"
        assert cg.api_key_env == "COINGLASS_API_KEY"

    def test_claude_config_defaults(self):
        claude = ClaudeConfig()
        assert claude.model == "claude-sonnet-4-5-20250929"
        assert claude.max_tokens == 2048
        assert claude.temperature == 0.3

    def test_claude_config_rejects_invalid_model(self):
        with pytest.raises(ValueError, match="Model must start with"):
            ClaudeConfig(model="gpt-4")

    def test_analysis_symbols_uppercased(self):
        analysis = AnalysisConfig(symbols=["btcusdt", "ethusdt"])
        assert analysis.symbols == ["BTCUSDT", "ETHUSDT"]

    def test_analysis_rejects_non_usdt(self):
        with pytest.raises(ValueError, match="must end with USDT"):
            AnalysisConfig(symbols=["BTCUSD"])

    def test_guardrails_read_only_enforced(self):
        with pytest.raises(ValueError, match="read_only cannot be disabled"):
            GuardrailsConfig(read_only=False)

    def test_guardrails_always_true(self):
        g = GuardrailsConfig()
        assert g.read_only is True
        assert g.max_analyses_per_day == 500

    def test_notification_channels(self):
        nc = NotificationConfig(channels=[NotificationChannel.SLACK, NotificationChannel.WEBHOOK])
        assert len(nc.channels) == 2

    def test_storage_sqlite_defaults(self):
        sc = StorageConfig()
        assert sc.backend == StorageBackendType.SQLITE
        assert sc.sqlite.path == "data/signals.db"
        assert sc.sqlite.retention_days == 90

    def test_storage_supabase(self):
        sc = StorageConfig(backend=StorageBackendType.SUPABASE)
        assert sc.backend == StorageBackendType.SUPABASE
        assert sc.supabase.table_name == "signals"

    def test_cache_defaults(self):
        cc = CacheConfig()
        assert cc.funding_ttl_seconds == 60
        assert cc.orderbook_ttl_seconds == 15
        assert cc.degraded_mode is True

    def test_rate_limit_bounds(self):
        with pytest.raises(ValueError):
            RateLimitConfig(bybit_requests_per_minute=1)  # Below minimum

    def test_schedule_bounds(self):
        with pytest.raises(ValueError):
            ScheduleConfig(interval_seconds=10)  # Below 60

    def test_disclaimer_defaults(self):
        d = DisclaimerConfig()
        assert "informational purposes" in d.text
        assert "DYOR" in d.short_text

    def test_full_config_from_dict(self):
        data = {
            "version": "1.0.0",
            "analysis": {
                "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
                "strong_signal_threshold": 60,
            },
            "schedule": {"interval_seconds": 600},
        }
        config = ConfigSchema(**data)
        assert len(config.analysis.symbols) == 3
        assert config.schedule.interval_seconds == 600


class TestConfigLoader:
    """Test YAML config loading."""

    def test_load_valid_config(self, tmp_path):
        config_data = {
            "version": "1.0.0",
            "analysis": {"symbols": ["BTCUSDT"]},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        config, raw = load_config(str(config_file))
        assert config.version == "1.0.0"
        assert config.analysis.symbols == ["BTCUSDT"]
        assert raw["version"] == "1.0.0"

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_load_invalid_schema(self, tmp_path):
        config_data = {
            "version": "1.0.0",
            "analysis": {"symbols": ["BTCUSD"]},  # Invalid: no USDT suffix
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data))

        with pytest.raises(Exception):
            load_config(str(config_file))

    def test_load_example_config(self):
        """Verify config.example.yaml parses correctly."""
        example = Path(__file__).parent.parent / "config.example.yaml"
        if example.exists():
            config, raw = load_config(str(example))
            assert config.version == "1.0.0"
            assert "BTCUSDT" in config.analysis.symbols


class TestConfigValidator:
    """Test additional config validation."""

    def test_validate_missing_api_keys(self, monkeypatch):
        monkeypatch.delenv("BYBIT_API_KEY", raising=False)
        monkeypatch.delenv("BYBIT_API_SECRET", raising=False)
        monkeypatch.delenv("COINGLASS_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        config = ConfigSchema()
        result = validate_config(config)
        assert result["valid"] is False
        assert len(result["errors"]) >= 4

    def test_validate_with_all_keys(self, monkeypatch):
        monkeypatch.setenv("BYBIT_API_KEY", "test")
        monkeypatch.setenv("BYBIT_API_SECRET", "test")
        monkeypatch.setenv("COINGLASS_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        config = ConfigSchema(
            notifications=NotificationConfig(
                channels=[NotificationChannel.SLACK],
                slack=SlackConfig(webhook_url="https://hooks.slack.com/test"),
            )
        )
        result = validate_config(config)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_validate_slack_without_url(self, monkeypatch):
        monkeypatch.setenv("BYBIT_API_KEY", "test")
        monkeypatch.setenv("BYBIT_API_SECRET", "test")
        monkeypatch.setenv("COINGLASS_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        config = ConfigSchema(
            notifications=NotificationConfig(
                channels=[NotificationChannel.SLACK],
                slack=SlackConfig(webhook_url=None),
            )
        )
        result = validate_config(config)
        assert result["valid"] is False
        assert any("Slack" in e for e in result["errors"])

    def test_validate_many_symbols_warning(self, monkeypatch):
        monkeypatch.setenv("BYBIT_API_KEY", "test")
        monkeypatch.setenv("BYBIT_API_SECRET", "test")
        monkeypatch.setenv("COINGLASS_API_KEY", "test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

        symbols = [f"TOKEN{i}USDT" for i in range(25)]
        config = ConfigSchema(
            analysis=AnalysisConfig(symbols=symbols),
            notifications=NotificationConfig(channels=[]),
        )
        result = validate_config(config)
        assert any("rate limits" in w for w in result["warnings"])
