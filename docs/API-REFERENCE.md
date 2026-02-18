# API Reference

Derivatives Signal Agent REST API.

Start the server: `python main.py --config config.yaml --serve --port 8000`

## Endpoints

### POST /analyze

Trigger analysis for all configured symbols.

**Response:**
```json
{
  "signals": [
    {
      "id": "uuid",
      "symbol": "BTCUSDT",
      "score": 42,
      "bias": "bullish",
      "confidence": "medium",
      "findings": ["Funding rate positive across exchanges"],
      "warnings": [],
      "data_quality": "complete",
      "cost_estimate_usd": "0.003200",
      "model": "claude-sonnet-4-5-20250929",
      "disclaimer": "...",
      "stale": false,
      "sources_available": 8,
      "sources_failed": [],
      "timestamp": "2025-01-01T00:00:00Z"
    }
  ],
  "count": 1,
  "disclaimer": "..."
}
```

### POST /analyze/{symbol}

Analyze a specific symbol. Symbol must end with `USDT`.

**Example:** `POST /analyze/BTCUSDT`

**Response:**
```json
{
  "signal": { ... },
  "disclaimer": "..."
}
```

### GET /signals/latest

Get the most recent signal for each configured symbol.

**Response:**
```json
{
  "signals": {
    "BTCUSDT": { ... },
    "ETHUSDT": { ... }
  },
  "disclaimer": "..."
}
```

### GET /signals/{symbol}/history

Get signal history with pagination.

**Query Parameters:**
- `limit` (int, default 50, max 200)
- `offset` (int, default 0)

**Example:** `GET /signals/BTCUSDT/history?limit=10&offset=0`

### GET /health

Health check for all service dependencies.

**Response:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "service": "derivatives-signal-agent",
  "checks": {
    "bybit": "ok",
    "coinglass": "ok",
    "claude": "ok",
    "storage": "ok"
  },
  "disclaimer": "Not financial advice. DYOR."
}
```

### GET /metrics

Agent metrics including costs and uptime.

**Response:**
```json
{
  "uptime_seconds": 3600,
  "analysis": {
    "count_today": 24,
    "max_per_day": 500
  },
  "cost": {
    "total_requests": 24,
    "total_input_tokens": 48000,
    "total_output_tokens": 12000,
    "total_cost_usd": "0.076800",
    "model": "claude-sonnet-4-5-20250929"
  },
  "http_clients": {
    "bybit": { "cache_size": 12, "circuit_state": "closed" },
    "coinglass": { "cache_size": 8, "circuit_state": "closed" }
  }
}
```

## Score System

| Range | Bias | Meaning |
|-------|------|---------|
| 50 to 100 | `strong_bullish` | Strong buying pressure indicators |
| 30 to 49 | `bullish` | Moderate bullish signals |
| -29 to 29 | `neutral` | Mixed or no clear direction |
| -49 to -30 | `bearish` | Moderate bearish signals |
| -100 to -50 | `strong_bearish` | Strong selling pressure indicators |

## Disclaimer

All API responses include a disclaimer field. This software is for informational purposes only and does not constitute financial advice.
