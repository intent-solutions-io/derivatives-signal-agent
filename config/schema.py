"""
Configuration schema definitions using Pydantic.

Defines the structure for config.yaml validation.
"""

from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, field_validator


class NotificationChannel(str, Enum):
    """Supported notification channels."""
    SLACK = "slack"
    WEBHOOK = "webhook"
    EMAIL = "email"
    TELEGRAM = "telegram"


class StorageBackendType(str, Enum):
    """Supported storage backends."""
    SQLITE = "sqlite"
    SUPABASE = "supabase"


class BybitConfig(BaseModel):
    """Bybit API v5 configuration."""
    base_url: str = Field("https://api.bybit.com", description="Bybit API base URL")
    api_key_env: str = Field("BYBIT_API_KEY", description="Env var name for API key")
    api_secret_env: str = Field("BYBIT_API_SECRET", description="Env var name for API secret")
    timeout_seconds: float = Field(10.0, ge=1.0, le=60.0)


class CoinglassConfig(BaseModel):
    """Coinglass API configuration."""
    base_url: str = Field("https://open-api-v3.coinglass.com", description="Coinglass API base URL")
    api_key_env: str = Field("COINGLASS_API_KEY", description="Env var name for API key")
    timeout_seconds: float = Field(10.0, ge=1.0, le=60.0)


class ClaudeConfig(BaseModel):
    """Claude AI API configuration."""
    api_key_env: str = Field("ANTHROPIC_API_KEY", description="Env var name for API key")
    model: str = Field("claude-sonnet-4-5-20250929", description="Claude model ID")
    max_tokens: int = Field(2048, ge=256, le=8192)
    temperature: float = Field(0.3, ge=0.0, le=1.0)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        allowed_prefixes = ("claude-", "anthropic.")
        if not any(v.startswith(p) for p in allowed_prefixes):
            raise ValueError(f"Model must start with one of: {allowed_prefixes}")
        return v


class AnalysisConfig(BaseModel):
    """Analysis settings for symbols and thresholds."""
    symbols: List[str] = Field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT"],
        description="Trading pairs to analyze"
    )
    strong_signal_threshold: int = Field(50, ge=10, le=90, description="Score magnitude for strong signal")
    orderbook_depth: int = Field(25, ge=5, le=200, description="Orderbook depth levels to fetch")

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, v: List[str]) -> List[str]:
        result = [s.upper() for s in v]
        for s in result:
            if not s.endswith("USDT"):
                raise ValueError(f"Symbol must end with USDT: {s}")
        return result


class SlackConfig(BaseModel):
    """Slack notification configuration."""
    webhook_url: Optional[str] = Field(None, description="Slack incoming webhook URL")
    channel: Optional[str] = Field(None, description="Channel override")
    mention_on_strong: Optional[str] = Field(None, description="User/group to @mention on strong signals")


class WebhookConfig(BaseModel):
    """Generic webhook notification configuration."""
    url: Optional[str] = None
    headers: Optional[dict] = None


class EmailNotificationConfig(BaseModel):
    """Email notification configuration."""
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    email_from: Optional[str] = None
    email_to: Optional[List[str]] = None


class TelegramNotificationConfig(BaseModel):
    """Telegram notification configuration."""
    chat_id: Optional[str] = None
    bot_token_env: str = Field("TELEGRAM_BOT_TOKEN", description="Env var for bot token")


class NotificationConfig(BaseModel):
    """Notification channel configurations."""
    channels: List[NotificationChannel] = Field(
        default_factory=lambda: [NotificationChannel.SLACK],
        description="Active notification channels"
    )
    slack: SlackConfig = Field(default_factory=SlackConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    email: EmailNotificationConfig = Field(default_factory=EmailNotificationConfig)
    telegram: TelegramNotificationConfig = Field(default_factory=TelegramNotificationConfig)


class SQLiteStorageConfig(BaseModel):
    """SQLite storage configuration."""
    path: str = Field("data/signals.db", description="Path to SQLite database")
    retention_days: int = Field(90, ge=7, le=365, description="Days to retain signals")


class SupabaseStorageConfig(BaseModel):
    """Supabase storage configuration."""
    url_env: str = Field("SUPABASE_URL", description="Env var for Supabase URL")
    key_env: str = Field("SUPABASE_ANON_KEY", description="Env var for Supabase anon key")
    table_name: str = Field("signals", description="Table name in Supabase")


class StorageConfig(BaseModel):
    """Storage configuration."""
    backend: StorageBackendType = Field(StorageBackendType.SQLITE, description="Storage backend type")
    sqlite: SQLiteStorageConfig = Field(default_factory=SQLiteStorageConfig)
    supabase: SupabaseStorageConfig = Field(default_factory=SupabaseStorageConfig)


class CacheConfig(BaseModel):
    """Cache TTL settings."""
    funding_ttl_seconds: int = Field(60, ge=10, le=600)
    orderbook_ttl_seconds: int = Field(15, ge=5, le=120)
    open_interest_ttl_seconds: int = Field(60, ge=10, le=600)
    degraded_mode: bool = Field(True, description="Serve stale data on API failure")


class RateLimitConfig(BaseModel):
    """Rate limiting settings."""
    bybit_requests_per_minute: int = Field(60, ge=10, le=120)
    coinglass_requests_per_minute: int = Field(30, ge=5, le=60)
    circuit_breaker_failures: int = Field(5, ge=3, le=10)
    circuit_breaker_backoff_seconds: int = Field(30, ge=10, le=300)


class ScheduleConfig(BaseModel):
    """Schedule settings for loop mode."""
    interval_seconds: int = Field(300, ge=60, le=3600, description="Seconds between analysis cycles")


class DisclaimerConfig(BaseModel):
    """Disclaimer text for SEC compliance."""
    text: str = Field(
        "This analysis is for informational purposes only and does not constitute "
        "financial advice. Trading derivatives carries substantial risk of loss. "
        "Past performance is not indicative of future results. Do your own research.",
        description="Disclaimer appended to all outputs"
    )
    short_text: str = Field(
        "Not financial advice. DYOR.",
        description="Short disclaimer for compact outputs"
    )


class QuietHoursConfig(BaseModel):
    """Quiet hours for notification suppression."""
    enabled: bool = False
    start_utc: str = Field("22:00", description="Start of quiet hours (UTC)")
    end_utc: str = Field("08:00", description="End of quiet hours (UTC)")


class GuardrailsConfig(BaseModel):
    """Hardcoded safety guardrails."""
    read_only: bool = Field(True, description="Agent cannot execute trades (hardcoded)")
    max_analyses_per_day: int = Field(500, ge=10, le=1000)
    max_cost_per_day_usd: str = Field("10.00", description="Max Claude API spend per day")
    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)

    @field_validator("read_only")
    @classmethod
    def enforce_read_only(cls, v: bool) -> bool:
        if not v:
            raise ValueError("read_only cannot be disabled — no trade execution exists")
        return True


class ConfigSchema(BaseModel):
    """Root configuration schema."""
    version: str = Field("1.0.0", description="Config schema version")
    membership_id: str = Field("", description="Whop membership ID for license tracking")
    bybit: BybitConfig = Field(default_factory=BybitConfig)
    coinglass: CoinglassConfig = Field(default_factory=CoinglassConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    rate_limits: RateLimitConfig = Field(default_factory=RateLimitConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    disclaimer: DisclaimerConfig = Field(default_factory=DisclaimerConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
