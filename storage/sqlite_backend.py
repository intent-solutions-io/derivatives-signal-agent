"""
SQLite storage backend — zero-setup default.

Uses WAL mode for concurrent reads, with retention cleanup.
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

import aiosqlite

from .base import StorageBackend

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    score INTEGER NOT NULL,
    bias TEXT NOT NULL,
    confidence TEXT NOT NULL,
    findings TEXT NOT NULL,
    warnings TEXT NOT NULL,
    data_quality TEXT NOT NULL,
    cost_estimate_usd TEXT NOT NULL,
    model TEXT NOT NULL,
    disclaimer TEXT NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    raw_data TEXT,
    created_at TEXT NOT NULL
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_signals_symbol_created
    ON signals(symbol, created_at DESC);
"""


class SQLiteBackend(StorageBackend):
    """SQLite storage with WAL mode and retention cleanup."""

    def __init__(self, db_path: str = "data/signals.db"):
        self.db_path = db_path

    async def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute(CREATE_TABLE_SQL)
            await db.execute(CREATE_INDEX_SQL)
            await db.commit()

    async def store(self, signal: Dict[str, Any]) -> str:
        signal_id = signal.get("id", str(uuid.uuid4()))
        created_at = signal.get("created_at", datetime.now(timezone.utc).isoformat())

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO signals
                   (id, symbol, score, bias, confidence, findings, warnings,
                    data_quality, cost_estimate_usd, model, disclaimer, stale,
                    raw_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal_id,
                    signal["symbol"],
                    signal["score"],
                    signal["bias"],
                    signal["confidence"],
                    json.dumps(signal.get("findings", [])),
                    json.dumps(signal.get("warnings", [])),
                    signal.get("data_quality", "unknown"),
                    signal.get("cost_estimate_usd", "0"),
                    signal.get("model", ""),
                    signal.get("disclaimer", ""),
                    1 if signal.get("stale", False) else 0,
                    json.dumps(signal.get("raw_data")) if signal.get("raw_data") else None,
                    created_at,
                ),
            )
            await db.commit()

        return signal_id

    async def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
                (symbol,),
            )
            row = await cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    async def get_history(
        self, symbol: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM signals WHERE symbol = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (symbol, limit, offset),
            )
            rows = await cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]

    async def health_check(self) -> bool:
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("SELECT 1")
                await cursor.fetchone()
            return True
        except Exception:
            return False

    async def cleanup(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM signals WHERE created_at < ?", (cutoff,)
            )
            await db.commit()
            return cursor.rowcount

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        d = dict(row)
        d["findings"] = json.loads(d.get("findings", "[]"))
        d["warnings"] = json.loads(d.get("warnings", "[]"))
        d["stale"] = bool(d.get("stale", 0))
        if d.get("raw_data"):
            d["raw_data"] = json.loads(d["raw_data"])
        return d
