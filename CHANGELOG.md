# Changelog

All notable changes to Derivatives Signal Agent will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-02-17

### Added
- Initial release
- Bybit API v5 integration (funding rates, open interest, orderbook, L/S ratio)
- Coinglass API integration (aggregated funding, OI, liquidations, cross-exchange L/S)
- Claude AI analysis with -100 to +100 directional bias scoring
- Three interaction modes: background loop, one-shot CLI, REST API server
- Slack Block Kit notifications with color-coded scores
- Webhook, email (SMTP), and Telegram notification channels
- SQLite storage (default) with WAL mode and retention cleanup
- Optional Supabase storage adapter
- FastAPI REST API with /analyze, /health, /signals, /metrics endpoints
- Circuit breaker, rate limiting, and response caching for all API clients
- Doctor acceptance test with 7 validation checks
- Docker and docker-compose support
- SEC compliance disclaimers on all outputs
- Cost tracking and daily analysis limits
- Partial data analysis (graceful degradation when sources fail)
