"""
Configuration loader and validator.

Loads config from YAML file and validates against schema.
"""

import os
import logging
import json
from pathlib import Path
from typing import Dict, Any, Tuple

import yaml
from pydantic import ValidationError

from .schema import ConfigSchema, NotificationChannel

logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Tuple[ConfigSchema, Dict[str, Any]]:
    """
    Load and validate configuration from YAML file.

    Returns:
        Tuple of (validated ConfigSchema, raw dict for reference)
    """
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info(json.dumps({
        "severity": "INFO",
        "component": "config_loader",
        "operation": "load_config",
        "config_path": str(path)
    }))

    with open(path, "r") as f:
        raw_config = yaml.safe_load(f)

    try:
        config = ConfigSchema(**raw_config)
        logger.info(json.dumps({
            "severity": "INFO",
            "component": "config_loader",
            "operation": "load_config",
            "status": "valid",
            "symbols": len(config.analysis.symbols),
            "backend": config.storage.backend.value
        }))
        return config, raw_config

    except ValidationError as e:
        logger.error(json.dumps({
            "severity": "ERROR",
            "component": "config_loader",
            "operation": "load_config",
            "status": "invalid",
            "errors": e.errors()
        }))
        raise


def validate_config(config: ConfigSchema) -> Dict[str, Any]:
    """
    Perform additional validation beyond schema.

    Returns:
        Dict with validation results:
        - valid: bool
        - warnings: List[str]
        - errors: List[str]
    """
    warnings = []
    errors = []

    # Check required API keys
    if not os.getenv(config.bybit.api_key_env):
        errors.append(f"Bybit API key not set: ${config.bybit.api_key_env}")
    if not os.getenv(config.bybit.api_secret_env):
        errors.append(f"Bybit API secret not set: ${config.bybit.api_secret_env}")
    if not os.getenv(config.coinglass.api_key_env):
        errors.append(f"Coinglass API key not set: ${config.coinglass.api_key_env}")
    if not os.getenv(config.claude.api_key_env):
        errors.append(f"Claude API key not set: ${config.claude.api_key_env}")

    # Check notification channels
    for channel in config.notifications.channels:
        if channel == NotificationChannel.SLACK and not config.notifications.slack.webhook_url:
            errors.append("Slack channel enabled but no webhook_url configured")
        elif channel == NotificationChannel.WEBHOOK and not config.notifications.webhook.url:
            errors.append("Webhook channel enabled but no URL configured")
        elif channel == NotificationChannel.EMAIL and not config.notifications.email.smtp_host:
            errors.append("Email channel enabled but no SMTP host configured")
        elif channel == NotificationChannel.TELEGRAM and not config.notifications.telegram.chat_id:
            errors.append("Telegram channel enabled but no chat_id configured")

    # Check SMTP password if email configured
    if config.notifications.email.smtp_host and not os.getenv("SMTP_PASSWORD"):
        warnings.append("SMTP configured but SMTP_PASSWORD env var not set")

    # Check telegram bot token
    if config.notifications.telegram.chat_id:
        if not os.getenv(config.notifications.telegram.bot_token_env):
            warnings.append(f"Telegram configured but ${config.notifications.telegram.bot_token_env} not set")

    # Storage warnings
    if config.storage.backend.value == "supabase":
        if not os.getenv(config.storage.supabase.url_env):
            errors.append(f"Supabase backend selected but ${config.storage.supabase.url_env} not set")
        if not os.getenv(config.storage.supabase.key_env):
            errors.append(f"Supabase backend selected but ${config.storage.supabase.key_env} not set")

    # Symbol warnings
    if len(config.analysis.symbols) > 20:
        warnings.append(f"Analyzing {len(config.analysis.symbols)} symbols — may hit rate limits")

    return {
        "valid": len(errors) == 0,
        "warnings": warnings,
        "errors": errors
    }
