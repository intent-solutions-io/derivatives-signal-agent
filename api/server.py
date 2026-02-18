"""
FastAPI REST API server for Derivatives Signal Agent.
"""

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from config.schema import ConfigSchema
from services.analysis_engine import AnalysisEngine
from services.notification_dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

# Module-level state (initialized in lifespan)
_engine: Optional[AnalysisEngine] = None
_dispatcher: Optional[NotificationDispatcher] = None
_config: Optional[ConfigSchema] = None
_start_time: Optional[datetime] = None


def create_app(config: ConfigSchema) -> FastAPI:
    """Create FastAPI app with the given config."""
    global _config
    _config = config

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global _engine, _dispatcher, _start_time
        _engine = AnalysisEngine(config)
        await _engine.initialize()
        _dispatcher = NotificationDispatcher(config.notifications)
        _start_time = datetime.now(timezone.utc)

        logger.info(json.dumps({
            "severity": "INFO",
            "component": "api_server",
            "event": "started",
            "symbols": config.analysis.symbols,
        }))
        yield

    app = FastAPI(
        title="Derivatives Signal Agent API",
        description="AI-powered derivatives market analysis",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    from api.routes import router
    app.include_router(router)

    return app


def get_engine() -> AnalysisEngine:
    if _engine is None:
        raise RuntimeError("Engine not initialized")
    return _engine


def get_dispatcher() -> NotificationDispatcher:
    if _dispatcher is None:
        raise RuntimeError("Dispatcher not initialized")
    return _dispatcher


def get_start_time() -> datetime:
    return _start_time or datetime.now(timezone.utc)
