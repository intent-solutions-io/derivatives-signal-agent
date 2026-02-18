"""
Async HTTP client with circuit breaker, caching, and rate limiting.

Adapted from crypto-agent's RPC client for REST API usage.
"""

import time
import hashlib
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CacheEntry:
    data: Any
    timestamp: float
    ttl_seconds: int
    stale: bool = False

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl_seconds


@dataclass
class CircuitBreaker:
    failure_count: int = 0
    failure_threshold: int = 5
    backoff_seconds: int = 30
    last_failure_time: Optional[float] = None
    state: CircuitState = CircuitState.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(json.dumps({
                "severity": "WARNING",
                "component": "circuit_breaker",
                "event": "circuit_opened",
                "failure_count": self.failure_count
            }))

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def can_proceed(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self.last_failure_time and time.time() - self.last_failure_time > self.backoff_seconds:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN allows one request


@dataclass
class RateLimiter:
    tokens: float = 60.0
    max_tokens: float = 60.0
    refill_rate: float = 1.0  # tokens per second
    last_refill: float = field(default_factory=time.time)

    def acquire(self) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class HTTPClient:
    """Async HTTP client with reliability patterns for REST APIs."""

    def __init__(
        self,
        base_url: str,
        default_headers: Optional[Dict[str, str]] = None,
        cache_ttl: int = 60,
        rate_limit_rpm: int = 60,
        circuit_threshold: int = 5,
        circuit_backoff: int = 30,
        timeout: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.cache: Dict[str, CacheEntry] = {}
        self.rate_limiter = RateLimiter(
            max_tokens=float(rate_limit_rpm),
            tokens=float(rate_limit_rpm),
            refill_rate=rate_limit_rpm / 60.0,
        )
        self.circuit = CircuitBreaker(
            failure_threshold=circuit_threshold,
            backoff_seconds=circuit_backoff,
        )
        self._request_count = 0

    def _cache_key(self, method: str, path: str, params: Optional[Dict] = None) -> str:
        payload = json.dumps({
            "method": method, "path": path, "params": params or {}
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> Optional[CacheEntry]:
        entry = self.cache.get(key)
        if entry and not entry.is_expired():
            return entry
        return None

    def _get_stale_cached(self, key: str) -> Optional[CacheEntry]:
        entry = self.cache.get(key)
        if entry:
            entry.stale = True
            return entry
        return None

    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        return await self._request("GET", path, params=params, headers=headers,
                                   use_cache=use_cache, cache_ttl=cache_ttl)

    async def post(
        self,
        path: str,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cache: bool = False,
    ) -> Dict[str, Any]:
        return await self._request("POST", path, json_body=json_body,
                                   params=params, headers=headers, use_cache=use_cache)

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        use_cache: bool = True,
        cache_ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        ttl = cache_ttl or self.cache_ttl
        cache_key = self._cache_key(method, path, params)

        # Check cache
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                return {"data": cached.data, "stale": False, "source": "cache"}

        # Rate limiting
        if not self.rate_limiter.acquire():
            stale = self._get_stale_cached(cache_key)
            if stale:
                return {"data": stale.data, "stale": True, "source": "cache"}
            raise Exception("Rate limited and no cached data available")

        # Circuit breaker
        if not self.circuit.can_proceed():
            stale = self._get_stale_cached(cache_key)
            if stale:
                return {"data": stale.data, "stale": True, "source": "cache"}
            raise Exception("Circuit breaker open and no cached data available")

        # Execute request
        try:
            result = await self._do_request(method, path, params, json_body, headers)
            self.circuit.record_success()
            self._request_count += 1

            if use_cache:
                self.cache[cache_key] = CacheEntry(
                    data=result, timestamp=time.time(), ttl_seconds=ttl
                )
            return {"data": result, "stale": False, "source": "api"}

        except Exception as e:
            self.circuit.record_failure()
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "http_client",
                "event": "request_failed",
                "method": method,
                "path": path,
                "error": str(e)
            }))

            # Try stale cache as fallback
            stale = self._get_stale_cached(cache_key)
            if stale:
                return {"data": stale.data, "stale": True, "source": "cache"}
            raise

    async def _do_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        merged_headers = {**self.default_headers, **(headers or {})}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=merged_headers,
            )
            response.raise_for_status()
            return response.json()

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self.cache),
            "rate_limiter_tokens": round(self.rate_limiter.tokens, 1),
            "circuit_state": self.circuit.state.value,
            "circuit_failures": self.circuit.failure_count,
            "total_requests": self._request_count,
        }
