# Derivatives Signal Agent

AI-powered derivatives market analysis that aggregates funding rates, open interest, order book depth, liquidations, and long/short ratios across exchanges — then produces directional bias scores using Claude AI.

## What It Does

- Fetches real-time derivatives data from **Bybit** (free) and **Coinglass** ($29/mo)
- Aggregates 8 data sources per symbol into a unified market snapshot
- Sends data to **Claude AI** for directional bias analysis (-100 to +100 score)
- Delivers color-coded signals to **Slack** with key findings and warnings
- Stores all signals in **SQLite** (or optional Supabase) for historical analysis
- Exposes a **REST API** for custom integrations

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Bybit API key](https://www.bybit.com/app/user/api-management) (free)
- [Coinglass API key](https://www.coinglass.com/pricing) ($29/mo minimum)
- [Anthropic API key](https://console.anthropic.com/)
- Slack incoming webhook URL

### 2. Configure

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your settings
```

### 3. Set Environment Variables

```bash
export BYBIT_API_KEY="your-key"
export BYBIT_API_SECRET="your-secret"
export COINGLASS_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"
```

### 4. Run Doctor (Acceptance Test)

```bash
pip install -r requirements.txt
python doctor.py --config config.yaml
```

All 7 checks should pass. Review `doctor-report.json` for details.

### 5. Run the Agent

```bash
# Background loop (every 5 minutes)
python main.py --config config.yaml

# Single analysis, all symbols
python main.py --config config.yaml --once

# Single symbol
python main.py --config config.yaml --once --symbol BTCUSDT

# REST API server
python main.py --config config.yaml --serve --port 8000
```

## Docker

```bash
# Build
docker build -t derivatives-signal-agent .

# Run loop mode
docker-compose up agent

# Run API server
docker-compose --profile api up api

# Run doctor
docker-compose --profile doctor run doctor
```

## REST API

When running with `--serve`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/analyze` | Analyze all configured symbols |
| `POST` | `/analyze/{symbol}` | Analyze specific symbol |
| `GET` | `/signals/latest` | Latest signal per symbol |
| `GET` | `/signals/{symbol}/history` | Signal history with pagination |
| `GET` | `/health` | Health check (all API connections) |
| `GET` | `/metrics` | Analysis count, costs, uptime |

### Example

```bash
# Analyze BTC
curl -X POST http://localhost:8000/analyze/BTCUSDT

# Get latest signals
curl http://localhost:8000/signals/latest

# Health check
curl http://localhost:8000/health
```

## Signal Output

Each signal includes:

- **Score**: -100 (extreme bearish) to +100 (extreme bullish)
- **Bias**: `strong_bearish`, `bearish`, `neutral`, `bullish`, `strong_bullish`
- **Confidence**: `low`, `medium`, `high`
- **Findings**: Key observations from the data
- **Warnings**: Conflicting signals or extreme readings
- **Data Quality**: `complete`, `partial`, `degraded`
- **Cost**: Claude API cost for the analysis

## Data Sources (8 per symbol)

| # | Source | Provider | Data |
|---|--------|----------|------|
| 1 | Funding Rate | Bybit | Current funding rate |
| 2 | Open Interest | Bybit | OI value and changes |
| 3 | Order Book | Bybit | Bid/ask depth and imbalance |
| 4 | Long/Short Ratio | Bybit | Account-level L/S ratio |
| 5 | Aggregated Funding | Coinglass | Cross-exchange funding rates |
| 6 | Aggregated OI | Coinglass | Cross-exchange open interest |
| 7 | Liquidations | Coinglass | Long/short liquidation volumes |
| 8 | Cross-Exchange L/S | Coinglass | Global long/short ratio |

If any source fails, analysis proceeds with available data. Claude is told which sources are missing.

## Configuration Reference

See `config.example.yaml` for all options. Key sections:

- **analysis**: Symbols to track, signal thresholds
- **notifications**: Slack, webhook, email, Telegram settings
- **storage**: SQLite (default) or Supabase
- **guardrails**: Daily limits, cost caps, quiet hours
- **cache**: TTL settings per data type
- **rate_limits**: Per-provider request limits with circuit breaker

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BYBIT_API_KEY` | Yes | Bybit API key |
| `BYBIT_API_SECRET` | Yes | Bybit API secret |
| `COINGLASS_API_KEY` | Yes | Coinglass API key ($29/mo) |
| `ANTHROPIC_API_KEY` | Yes | Claude API key |
| `SMTP_PASSWORD` | No | Email notification password |
| `TELEGRAM_BOT_TOKEN` | No | Telegram bot token |
| `SUPABASE_URL` | No | Supabase URL (if using Supabase storage) |
| `SUPABASE_ANON_KEY` | No | Supabase anon key |

## Costs

- **Bybit API**: Free
- **Coinglass API**: $29/month (buyer pays)
- **Claude API**: ~$0.001-0.005 per analysis (configurable daily cap)
- **Self-hosted**: No monthly platform fees

## Safety

- **Read-only**: No trade execution code exists. `guardrails.read_only: true` cannot be disabled.
- **Daily limits**: Configurable max analyses per day and cost cap.
- **Disclaimers**: Every output includes SEC compliance disclaimer.
- **Secrets**: All API keys via environment variables, never in config files.

## Disclaimer

**This software is for informational purposes only and does not constitute financial advice. Trading derivatives carries substantial risk of loss. Past performance is not indicative of future results. Do your own research.**

## License

See [LICENSE.md](LICENSE.md). Non-exclusive, non-transferable, perpetual usage license with 7-day defect warranty.
