"""
Supabase storage backend — optional cloud adapter.

Uses Supabase REST API via httpx. Requires SUPABASE_URL and SUPABASE_ANON_KEY.
"""

import os
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import httpx

from .base import StorageBackend

logger = logging.getLogger(__name__)


class SupabaseBackend(StorageBackend):
    """Supabase REST API storage backend."""

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table_name: str = "signals",
    ):
        self.url = (url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.getenv("SUPABASE_ANON_KEY", "")
        self.table_name = table_name

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    @property
    def _rest_url(self) -> str:
        return f"{self.url}/rest/v1/{self.table_name}"

    async def initialize(self) -> None:
        # Supabase tables must be created via dashboard or migrations
        logger.info(json.dumps({
            "severity": "INFO",
            "component": "supabase_backend",
            "event": "initialize",
            "message": "Supabase tables should be created via dashboard/migrations",
        }))

    async def store(self, signal: Dict[str, Any]) -> str:
        signal_id = signal.get("id", str(uuid.uuid4()))
        row = {
            "id": signal_id,
            "symbol": signal["symbol"],
            "score": signal["score"],
            "bias": signal["bias"],
            "confidence": signal["confidence"],
            "findings": signal.get("findings", []),
            "warnings": signal.get("warnings", []),
            "data_quality": signal.get("data_quality", "unknown"),
            "cost_estimate_usd": signal.get("cost_estimate_usd", "0"),
            "model": signal.get("model", ""),
            "disclaimer": signal.get("disclaimer", ""),
            "stale": signal.get("stale", False),
            "raw_data": signal.get("raw_data"),
            "created_at": signal.get("created_at", datetime.now(timezone.utc).isoformat()),
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self._rest_url,
                headers=self._headers,
                json=row,
            )
            response.raise_for_status()

        return signal_id

    async def get_latest(self, symbol: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._rest_url,
                headers=self._headers,
                params={
                    "symbol": f"eq.{symbol}",
                    "order": "created_at.desc",
                    "limit": "1",
                },
            )
            response.raise_for_status()
            data = response.json()
            return data[0] if data else None

    async def get_history(
        self, symbol: str, limit: int = 50, offset: int = 0
    ) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self._rest_url,
                headers=self._headers,
                params={
                    "symbol": f"eq.{symbol}",
                    "order": "created_at.desc",
                    "limit": str(limit),
                    "offset": str(offset),
                },
            )
            response.raise_for_status()
            return response.json()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    self._rest_url,
                    headers=self._headers,
                    params={"limit": "1"},
                )
                return response.status_code == 200
        except Exception:
            return False

    async def cleanup(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    self._rest_url,
                    headers={**self._headers, "Prefer": "return=representation"},
                    params={"created_at": f"lt.{cutoff}"},
                )
                response.raise_for_status()
                return len(response.json())
        except Exception as e:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "supabase_backend",
                "event": "cleanup_failed",
                "error": str(e),
            }))
            return 0
