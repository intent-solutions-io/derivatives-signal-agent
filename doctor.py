"""
Doctor command for self-test and acceptance verification.

Runs 7 validation checks and outputs doctor-report.json.

Usage:
    python doctor.py --config config.yaml
    python doctor.py --config config.yaml --output report.json
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from config.loader import load_config, validate_config

logger = logging.getLogger(__name__)


async def check_config(config_path: str) -> Dict[str, Any]:
    """Check 1: Validate configuration file."""
    try:
        config, raw = load_config(config_path)
        validation = validate_config(config)
        return {
            "test": "config_validation",
            "passed": validation["valid"],
            "details": {
                "symbols": config.analysis.symbols,
                "storage_backend": config.storage.backend.value,
                "notification_channels": [c.value for c in config.notifications.channels],
                "warnings": validation["warnings"],
                "errors": validation["errors"],
            }
        }
    except Exception as e:
        return {"test": "config_validation", "passed": False, "error": str(e)}


async def check_bybit(config) -> Dict[str, Any]:
    """Check 2: Bybit API connectivity."""
    from tools.bybit_client import BybitClient

    try:
        client = BybitClient(
            base_url=config.bybit.base_url,
            timeout=config.bybit.timeout_seconds,
        )
        result = await client.get_funding_rate("BTCUSDT", limit=1)
        data = result.get("data", [])
        return {
            "test": "bybit_connectivity",
            "passed": len(data) > 0,
            "details": {
                "symbol": "BTCUSDT",
                "funding_rate": data[0].funding_rate if data else None,
                "source": result.get("source"),
            }
        }
    except Exception as e:
        return {"test": "bybit_connectivity", "passed": False, "error": str(e)}


async def check_coinglass(config) -> Dict[str, Any]:
    """Check 3: Coinglass API connectivity."""
    from tools.coinglass_client import CoinglassClient

    try:
        client = CoinglassClient(
            base_url=config.coinglass.base_url,
            timeout=config.coinglass.timeout_seconds,
        )
        result = await client.get_aggregated_funding("BTCUSDT")
        data = result.get("data")
        return {
            "test": "coinglass_connectivity",
            "passed": data is not None and len(data.exchanges) > 0,
            "details": {
                "symbol": "BTCUSDT",
                "exchanges_found": len(data.exchanges) if data else 0,
                "average_rate": data.average_rate if data else None,
                "source": result.get("source"),
            }
        }
    except Exception as e:
        return {"test": "coinglass_connectivity", "passed": False, "error": str(e)}


async def check_claude(config) -> Dict[str, Any]:
    """Check 4: Claude API connectivity."""
    from tools.claude_client import ClaudeClient

    try:
        client = ClaudeClient(model=config.claude.model)
        ok = await client.health_check()
        return {
            "test": "claude_connectivity",
            "passed": ok,
            "details": {
                "model": config.claude.model,
                "connected": ok,
            }
        }
    except Exception as e:
        return {"test": "claude_connectivity", "passed": False, "error": str(e)}


async def check_slack(config) -> Dict[str, Any]:
    """Check 5: Slack webhook test."""
    from services.notification_dispatcher import NotificationDispatcher
    from config.schema import NotificationChannel

    if NotificationChannel.SLACK not in config.notifications.channels:
        return {
            "test": "slack_notification",
            "passed": True,
            "details": {"skipped": True, "reason": "Slack not in configured channels"}
        }

    try:
        dispatcher = NotificationDispatcher(config.notifications)
        result = await dispatcher.test_channel(NotificationChannel.SLACK)
        return {
            "test": "slack_notification",
            "passed": result.success,
            "details": {"message": result.message}
        }
    except Exception as e:
        return {"test": "slack_notification", "passed": False, "error": str(e)}


async def check_storage(config) -> Dict[str, Any]:
    """Check 6: Storage write/read/delete test."""
    from services.storage_service import create_storage
    from datetime import datetime, timezone

    try:
        storage = create_storage(config.storage)
        await storage.initialize()

        # Write test
        test_signal = {
            "id": "doctor-test-signal",
            "symbol": "DOCTOR_TEST",
            "score": 0,
            "bias": "neutral",
            "confidence": "test",
            "findings": ["Doctor test"],
            "warnings": [],
            "data_quality": "test",
            "cost_estimate_usd": "0",
            "model": "test",
            "disclaimer": "Test",
            "stale": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        signal_id = await storage.store(test_signal)

        # Read test
        latest = await storage.get_latest("DOCTOR_TEST")
        read_ok = latest is not None and latest.get("score") == 0

        # Cleanup test
        deleted = await storage.cleanup(retention_days=0)

        # Health
        health = await storage.health_check()

        return {
            "test": "storage",
            "passed": read_ok and health,
            "details": {
                "backend": config.storage.backend.value,
                "write_ok": signal_id is not None,
                "read_ok": read_ok,
                "cleanup_deleted": deleted,
                "health_ok": health,
            }
        }
    except Exception as e:
        return {"test": "storage", "passed": False, "error": str(e)}


async def check_end_to_end(config) -> Dict[str, Any]:
    """Check 7: Full analysis cycle (single symbol)."""
    from services.analysis_engine import AnalysisEngine

    try:
        engine = AnalysisEngine(config)
        await engine.initialize()

        report = await engine.analyze_symbol("BTCUSDT")
        if report:
            return {
                "test": "end_to_end",
                "passed": True,
                "details": {
                    "symbol": report.symbol,
                    "score": report.score,
                    "bias": report.bias,
                    "confidence": report.confidence,
                    "sources_available": report.sources_available,
                    "sources_failed": report.sources_failed,
                    "cost_usd": f"{report.cost_estimate_usd:.6f}",
                    "data_quality": report.data_quality,
                }
            }
        else:
            return {
                "test": "end_to_end",
                "passed": False,
                "error": "Analysis returned no report"
            }
    except Exception as e:
        return {"test": "end_to_end", "passed": False, "error": str(e)}


async def run_doctor(config_path: str) -> Dict[str, Any]:
    """Run all 7 doctor checks."""
    version = "1.0.0"
    try:
        version = Path("VERSION").read_text().strip()
    except Exception:
        pass

    results = {
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": config_path,
        "disclaimer": "This tool is for informational purposes only. Not financial advice.",
        "tests": [],
    }

    # Check 1: Config
    config_result = await check_config(config_path)
    results["tests"].append(config_result)

    if not config_result["passed"]:
        results["all_passed"] = False
        return results

    # Load config for remaining checks
    config, _ = load_config(config_path)

    # Checks 2-7
    checks = [
        check_bybit(config),
        check_coinglass(config),
        check_claude(config),
        check_slack(config),
        check_storage(config),
        check_end_to_end(config),
    ]

    for coro in checks:
        result = await coro
        results["tests"].append(result)

    results["all_passed"] = all(t.get("passed", False) for t in results["tests"])
    return results


async def main():
    """Main doctor entrypoint."""
    parser = argparse.ArgumentParser(description="Derivatives Signal Agent - Doctor")
    parser.add_argument("--config", "-c", required=True, help="Path to config.yaml")
    parser.add_argument("--output", "-o", default="doctor-report.json", help="Output file path")
    args = parser.parse_args()

    print(f"Derivatives Signal Agent - Doctor")
    print(f"Config: {args.config}")
    print("=" * 60)

    results = await run_doctor(args.config)

    # Print summary
    for test in results["tests"]:
        status = "PASS" if test.get("passed") else "FAIL"
        print(f"[{status}] {test['test']}")
        if not test.get("passed") and "error" in test:
            print(f"       Error: {test['error']}")

    print("=" * 60)
    passed = sum(1 for t in results["tests"] if t.get("passed"))
    total = len(results["tests"])
    print(f"Results: {passed}/{total} passed")
    print(f"All passed: {results['all_passed']}")

    # Save report
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Report saved to: {args.output}")

    sys.exit(0 if results["all_passed"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
