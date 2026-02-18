"""Tests for HTTP client with reliability patterns."""

import pytest
import time

from tools.http_client import (
    HTTPClient, CircuitBreaker, RateLimiter, CacheEntry, CircuitState
)


class TestCacheEntry:
    def test_not_expired(self):
        entry = CacheEntry(data={"k": "v"}, timestamp=time.time(), ttl_seconds=60)
        assert not entry.is_expired()

    def test_expired(self):
        entry = CacheEntry(data={"k": "v"}, timestamp=time.time() - 120, ttl_seconds=60)
        assert entry.is_expired()

    def test_stale_flag(self):
        entry = CacheEntry(data={"k": "v"}, timestamp=time.time(), ttl_seconds=60)
        assert entry.stale is False
        entry.stale = True
        assert entry.stale is True


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_proceed()

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.can_proceed()  # Still closed
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.can_proceed()

    def test_half_open_after_backoff(self):
        cb = CircuitBreaker(failure_threshold=1, backoff_seconds=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.01)
        assert cb.can_proceed()  # Should transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


class TestRateLimiter:
    def test_acquire_succeeds(self):
        rl = RateLimiter(tokens=10.0, max_tokens=10.0)
        assert rl.acquire()
        assert rl.tokens < 10.0

    def test_acquire_fails_when_empty(self):
        rl = RateLimiter(tokens=0.0, max_tokens=10.0, refill_rate=0.0)
        assert not rl.acquire()

    def test_refills_over_time(self):
        rl = RateLimiter(tokens=0.0, max_tokens=10.0, refill_rate=1000.0)
        time.sleep(0.02)
        assert rl.acquire()


class TestHTTPClient:
    def test_cache_key_deterministic(self):
        client = HTTPClient(base_url="https://example.com")
        key1 = client._cache_key("GET", "/test", {"a": 1})
        key2 = client._cache_key("GET", "/test", {"a": 1})
        assert key1 == key2

    def test_cache_key_different_for_different_params(self):
        client = HTTPClient(base_url="https://example.com")
        key1 = client._cache_key("GET", "/test", {"a": 1})
        key2 = client._cache_key("GET", "/test", {"a": 2})
        assert key1 != key2

    def test_get_cached_returns_none_when_empty(self):
        client = HTTPClient(base_url="https://example.com")
        assert client._get_cached("nonexistent") is None

    def test_get_cached_returns_valid_entry(self):
        client = HTTPClient(base_url="https://example.com")
        client.cache["key1"] = CacheEntry(
            data={"test": True}, timestamp=time.time(), ttl_seconds=60
        )
        entry = client._get_cached("key1")
        assert entry is not None
        assert entry.data == {"test": True}

    def test_get_cached_returns_none_for_expired(self):
        client = HTTPClient(base_url="https://example.com")
        client.cache["key1"] = CacheEntry(
            data={"test": True}, timestamp=time.time() - 120, ttl_seconds=60
        )
        assert client._get_cached("key1") is None

    def test_get_stale_cached(self):
        client = HTTPClient(base_url="https://example.com")
        client.cache["key1"] = CacheEntry(
            data={"test": True}, timestamp=time.time() - 120, ttl_seconds=60
        )
        entry = client._get_stale_cached("key1")
        assert entry is not None
        assert entry.stale is True

    def test_metrics(self):
        client = HTTPClient(base_url="https://example.com")
        metrics = client.get_metrics()
        assert metrics["cache_size"] == 0
        assert metrics["circuit_state"] == "closed"
        assert metrics["total_requests"] == 0

    def test_base_url_strips_trailing_slash(self):
        client = HTTPClient(base_url="https://example.com/")
        assert client.base_url == "https://example.com"
