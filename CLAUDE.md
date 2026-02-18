# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

Derivatives Signal Agent is a read-only derivatives market analysis tool that aggregates data from Bybit and Coinglass, runs Claude AI analysis, and produces directional bias scores (-100 to +100). Sold as a premium product ($49-99) on Gumroad and Whop.

## Version Control

**Semantic versioning is required.** Version tracked in `VERSION` file.
- MAJOR: Breaking config/API changes
- MINOR: New data sources, analysis features
- PATCH: Bug fixes, dependency bumps

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run once
python main.py --config config.yaml --once

# Run single symbol
python main.py --config config.yaml --once --symbol BTCUSDT

# Run continuous loop (5-min default)
python main.py --config config.yaml

# Run API server
python main.py --config config.yaml --serve --port 8000

# Run acceptance tests (doctor)
python doctor.py --config config.yaml

# Run test suite
pytest tests/ -v

# Docker
docker build -t derivatives-signal-agent .
docker-compose up agent
docker-compose --profile doctor run doctor
```

## Architecture

Pipeline: **Config -> Tools (data fetch) -> Services (orchestrate + analyze) -> Output**

### Data Flow

1. `main.py` loads config via `config/loader.py` (Pydantic validation)
2. `services/analysis_engine.py` fetches 8 data sources in parallel (4 Bybit + 4 Coinglass)
3. Partial data: if sources fail, analysis proceeds with available data
4. `tools/claude_client.py` sends aggregated data to Claude for scoring
5. `services/notification_dispatcher.py` sends signals to Slack/webhook/email/Telegram
6. `storage/` persists signals to SQLite or Supabase

### tools/ — API Clients

- `http_client.py` — Circuit breaker, rate limiter, response cache (shared by all clients)
- `bybit_client.py` — Bybit v5 API with HMAC signing (funding, OI, orderbook, L/S ratio)
- `coinglass_client.py` — Coinglass API (aggregated funding, OI, liquidations, cross-exchange L/S)
- `claude_client.py` — Claude Messages API with JSON parsing and cost tracking

### services/ — Business Logic

- `analysis_engine.py` — Orchestrates fetch → Claude → store pipeline. Enforces daily limits.
- `notification_dispatcher.py` — Multi-channel dispatch with Slack Block Kit formatting
- `storage_service.py` — Factory for SQLite/Supabase backends

### api/ — REST Server

- `server.py` — FastAPI app factory with lifespan management
- `routes.py` — /analyze, /health, /signals, /metrics endpoints

## Key Rules

- All monetary values as decimal strings (never float)
- Every response carries `stale: bool` from cache
- Every output includes SEC disclaimer
- `guardrails.read_only: true` — hardcoded, cannot be disabled
- Secrets via env vars only — never in config YAML
- Structured JSON logging (`severity`, `component`, `event`)

## Testing

Tests use pytest with `tmp_path` for SQLite. No network calls — all API responses are mocked. Test fixtures create config objects directly.
