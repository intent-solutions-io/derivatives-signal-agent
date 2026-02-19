"""
Derivatives Signal Agent — Main Entry Point

Three modes:
  python main.py --config config.yaml                         # Background loop
  python main.py --config config.yaml --once                  # Single analysis
  python main.py --config config.yaml --once --symbol BTCUSDT # Single symbol
  python main.py --config config.yaml --serve                 # REST API server
  python main.py --config config.yaml --serve --port 8000     # Custom port
"""

import argparse
import asyncio
import json
import logging
import sys

from config.loader import load_config, validate_config
from services.analysis_engine import AnalysisEngine
from services.notification_dispatcher import NotificationDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def run_analysis_cycle(
    engine: AnalysisEngine,
    dispatcher: NotificationDispatcher,
    symbol: str | None = None,
) -> None:
    """Run one analysis cycle for one or all symbols."""
    if symbol:
        symbols = [symbol]
    else:
        symbols = engine.config.analysis.symbols

    for sym in symbols:
        report = await engine.analyze_symbol(sym)
        if report:
            # Dispatch notifications
            await dispatcher.dispatch(report.to_dict())

            logger.info(json.dumps({
                "severity": "INFO",
                "component": "main",
                "event": "signal_produced",
                "symbol": report.symbol,
                "score": report.score,
                "bias": report.bias,
                "cost_usd": f"{report.cost_estimate_usd:.6f}",
            }))

    # Log cost summary
    cost = engine.get_cost_summary()
    logger.info(json.dumps({
        "severity": "INFO",
        "component": "main",
        "event": "cycle_complete",
        "symbols_analyzed": len(symbols),
        "total_cost_usd": cost["total_cost_usd"],
    }))


async def run_loop(
    engine: AnalysisEngine,
    dispatcher: NotificationDispatcher,
    interval: int,
) -> None:
    """Background loop mode."""
    logger.info(json.dumps({
        "severity": "INFO",
        "component": "main",
        "event": "loop_started",
        "interval_seconds": interval,
        "symbols": engine.config.analysis.symbols,
    }))

    while True:
        try:
            await run_analysis_cycle(engine, dispatcher)
        except Exception as e:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "main",
                "event": "cycle_failed",
                "error": str(e),
            }))
        await asyncio.sleep(interval)


async def main():
    """Main entrypoint."""
    parser = argparse.ArgumentParser(description="Derivatives Signal Agent")
    parser.add_argument("--config", "-c", required=True, help="Path to config.yaml")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--symbol", "-s", type=str, default=None, help="Analyze single symbol")
    parser.add_argument("--serve", action="store_true", help="Start REST API server")
    parser.add_argument("--port", type=int, default=8000, help="API server port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="API server host")
    args = parser.parse_args()

    # Load and validate config
    try:
        config, raw = load_config(args.config)
        validation = validate_config(config)
        if not validation["valid"]:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "main",
                "event": "config_invalid",
                "errors": validation["errors"],
            }))
            sys.exit(1)
        if validation["warnings"]:
            for warning in validation["warnings"]:
                logger.warning(json.dumps({
                    "severity": "WARNING",
                    "component": "main",
                    "message": warning,
                }))
    except Exception as e:
        logger.error(json.dumps({
            "severity": "ERROR",
            "component": "main",
            "event": "config_load_failed",
            "error": str(e),
        }))
        sys.exit(1)

    # API server mode
    if args.serve:
        import uvicorn
        from api.server import create_app

        app = create_app(config)
        logger.info(json.dumps({
            "severity": "INFO",
            "component": "main",
            "event": "api_server_starting",
            "host": args.host,
            "port": args.port,
        }))
        uvicorn.run(app, host=args.host, port=args.port)
        return

    # Initialize services
    engine = AnalysisEngine(config)
    await engine.initialize()
    dispatcher = NotificationDispatcher(config.notifications)

    logger.info(json.dumps({
        "severity": "INFO",
        "component": "main",
        "event": "agent_started",
        "mode": "once" if args.once else "loop",
        "symbols": config.analysis.symbols,
        "storage": config.storage.backend.value,
        "membership_id": config.membership_id or "unregistered",
    }))

    if args.once:
        await run_analysis_cycle(engine, dispatcher, symbol=args.symbol)
    else:
        await run_loop(engine, dispatcher, config.schedule.interval_seconds)


if __name__ == "__main__":
    asyncio.run(main())
