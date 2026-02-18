"""
API route definitions for Derivatives Signal Agent.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.server import get_engine, get_dispatcher, get_start_time

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check — tests all API connections."""
    engine = get_engine()

    bybit_ok = await engine.bybit.health_check()
    coinglass_ok = await engine.coinglass.health_check()
    claude_ok = await engine.claude.health_check()
    storage_ok = await engine.storage.health_check()

    all_ok = bybit_ok and storage_ok
    # coinglass and claude are optional for health

    return {
        "status": "ok" if all_ok else "degraded",
        "version": "1.0.0",
        "service": "derivatives-signal-agent",
        "checks": {
            "bybit": "ok" if bybit_ok else "failed",
            "coinglass": "ok" if coinglass_ok else "failed",
            "claude": "ok" if claude_ok else "failed",
            "storage": "ok" if storage_ok else "failed",
        },
        "disclaimer": engine.config.disclaimer.short_text,
    }


@router.post("/analyze")
async def analyze_all():
    """Trigger analysis for all configured symbols."""
    engine = get_engine()
    dispatcher = get_dispatcher()

    reports = await engine.analyze_all()
    results = []
    for report in reports:
        await dispatcher.dispatch(report.to_dict())
        results.append(report.to_dict())

    return {
        "signals": results,
        "count": len(results),
        "disclaimer": engine.config.disclaimer.text,
    }


@router.post("/analyze/{symbol}")
async def analyze_symbol(symbol: str):
    """Trigger analysis for a specific symbol."""
    engine = get_engine()
    dispatcher = get_dispatcher()

    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        raise HTTPException(status_code=400, detail="Symbol must end with USDT")

    report = await engine.analyze_symbol(symbol)
    if not report:
        raise HTTPException(status_code=503, detail="Analysis failed — no data available")

    await dispatcher.dispatch(report.to_dict())

    return {
        "signal": report.to_dict(),
        "disclaimer": engine.config.disclaimer.text,
    }


@router.get("/signals/latest")
async def get_latest_signals():
    """Get latest signal per configured symbol."""
    engine = get_engine()

    signals = {}
    for symbol in engine.config.analysis.symbols:
        latest = await engine.storage.get_latest(symbol)
        if latest:
            signals[symbol] = latest

    return {
        "signals": signals,
        "disclaimer": engine.config.disclaimer.short_text,
    }


@router.get("/signals/{symbol}/history")
async def get_signal_history(symbol: str, limit: int = 50, offset: int = 0):
    """Get signal history for a symbol with pagination."""
    engine = get_engine()

    symbol = symbol.upper()
    if limit > 200:
        limit = 200

    history = await engine.storage.get_history(symbol, limit=limit, offset=offset)

    return {
        "symbol": symbol,
        "signals": history,
        "count": len(history),
        "limit": limit,
        "offset": offset,
        "disclaimer": engine.config.disclaimer.short_text,
    }


@router.get("/metrics")
async def get_metrics():
    """Get agent metrics: analysis count, costs, uptime."""
    engine = get_engine()
    start = get_start_time()

    uptime = (datetime.now(timezone.utc) - start).total_seconds()
    cost = engine.get_cost_summary()
    bybit_metrics = engine.bybit.http.get_metrics()
    coinglass_metrics = engine.coinglass.http.get_metrics()

    return {
        "uptime_seconds": int(uptime),
        "analysis": {
            "count_today": engine._analysis_count_today,
            "max_per_day": engine.config.guardrails.max_analyses_per_day,
        },
        "cost": cost,
        "http_clients": {
            "bybit": bybit_metrics,
            "coinglass": coinglass_metrics,
        },
        "storage": {
            "backend": engine.config.storage.backend.value,
        },
    }
