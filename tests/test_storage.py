"""Tests for storage backends."""

import pytest
from datetime import datetime, timezone, timedelta

from storage.sqlite_backend import SQLiteBackend
from storage.base import StorageBackend
from services.storage_service import create_storage
from config.schema import StorageConfig, StorageBackendType


def _make_signal(symbol="BTCUSDT", score=42, bias="bullish", **overrides):
    base = {
        "symbol": symbol,
        "score": score,
        "bias": bias,
        "confidence": "medium",
        "findings": ["test finding"],
        "warnings": [],
        "data_quality": "complete",
        "cost_estimate_usd": "0.001",
        "model": "claude-sonnet-4-5-20250929",
        "disclaimer": "Not financial advice.",
        "stale": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


class TestSQLiteBackend:
    @pytest.mark.asyncio
    async def test_initialize_creates_db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()
        assert await backend.health_check()

    @pytest.mark.asyncio
    async def test_store_and_get_latest(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        signal = _make_signal()
        signal_id = await backend.store(signal)
        assert signal_id

        latest = await backend.get_latest("BTCUSDT")
        assert latest is not None
        assert latest["symbol"] == "BTCUSDT"
        assert latest["score"] == 42
        assert latest["bias"] == "bullish"
        assert latest["findings"] == ["test finding"]

    @pytest.mark.asyncio
    async def test_get_latest_returns_none(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        latest = await backend.get_latest("NONEXISTENT")
        assert latest is None

    @pytest.mark.asyncio
    async def test_get_history_pagination(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        # Store 5 signals
        for i in range(5):
            signal = _make_signal(
                score=i * 10,
                created_at=(datetime.now(timezone.utc) + timedelta(seconds=i)).isoformat(),
            )
            await backend.store(signal)

        # Get first page
        history = await backend.get_history("BTCUSDT", limit=3, offset=0)
        assert len(history) == 3

        # Get second page
        history2 = await backend.get_history("BTCUSDT", limit=3, offset=3)
        assert len(history2) == 2

    @pytest.mark.asyncio
    async def test_get_history_orders_by_newest(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        await backend.store(_make_signal(
            score=10,
            created_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        ))
        await backend.store(_make_signal(
            score=20,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))

        history = await backend.get_history("BTCUSDT", limit=10)
        assert history[0]["score"] == 20  # Newest first

    @pytest.mark.asyncio
    async def test_cleanup_removes_old(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        # Store an old signal
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        await backend.store(_make_signal(created_at=old_date))

        # Store a recent signal
        await backend.store(_make_signal(score=99))

        deleted = await backend.cleanup(retention_days=90)
        assert deleted == 1

        # Recent signal should still exist
        history = await backend.get_history("BTCUSDT")
        assert len(history) == 1
        assert history[0]["score"] == 99

    @pytest.mark.asyncio
    async def test_health_check(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()
        assert await backend.health_check()

    @pytest.mark.asyncio
    async def test_stale_flag_stored(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        await backend.store(_make_signal(stale=True))
        latest = await backend.get_latest("BTCUSDT")
        assert latest["stale"] is True

    @pytest.mark.asyncio
    async def test_stores_multiple_symbols(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        backend = SQLiteBackend(db_path=db_path)
        await backend.initialize()

        await backend.store(_make_signal(symbol="BTCUSDT", score=50))
        await backend.store(_make_signal(symbol="ETHUSDT", score=30))

        btc = await backend.get_latest("BTCUSDT")
        eth = await backend.get_latest("ETHUSDT")
        assert btc["score"] == 50
        assert eth["score"] == 30


class TestStorageService:
    def test_create_sqlite_backend(self):
        config = StorageConfig(backend=StorageBackendType.SQLITE)
        backend = create_storage(config)
        assert isinstance(backend, SQLiteBackend)

    def test_create_supabase_backend(self):
        config = StorageConfig(backend=StorageBackendType.SUPABASE)
        backend = create_storage(config)
        from storage.supabase_backend import SupabaseBackend
        assert isinstance(backend, SupabaseBackend)

    def test_backend_is_abstract(self):
        assert hasattr(StorageBackend, "store")
        assert hasattr(StorageBackend, "get_latest")
        assert hasattr(StorageBackend, "health_check")
