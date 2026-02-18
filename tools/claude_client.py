"""
Claude AI client for derivatives analysis.

Constructs analysis prompts, parses JSON responses, and tracks costs.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Claude pricing per million tokens (as of 2025)
MODEL_PRICING = {
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

ANALYSIS_SYSTEM_PROMPT = """You are a derivatives market analyst. Analyze the provided market data and produce a directional bias assessment.

IMPORTANT RULES:
1. Output ONLY valid JSON — no markdown, no commentary
2. Score range: -100 (extreme bearish) to +100 (extreme bullish)
3. 0 = neutral/no clear bias
4. List specific evidence for your score
5. Note any missing data sources and how it affects confidence
6. Include warnings for extreme readings or conflicting signals
7. NEVER provide trade recommendations — analysis only

Output schema:
{
  "symbol": "string",
  "score": integer (-100 to 100),
  "bias": "strong_bearish|bearish|neutral|bullish|strong_bullish",
  "confidence": "low|medium|high",
  "findings": ["string", ...],
  "warnings": ["string", ...],
  "data_quality": "complete|partial|degraded"
}"""


@dataclass
class CostTracker:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    total_cost_usd: float = 0.0

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_requests += 1

        pricing = MODEL_PRICING.get(model, {"input": 3.00, "output": 15.00})
        cost = (input_tokens / 1_000_000 * pricing["input"] +
                output_tokens / 1_000_000 * pricing["output"])
        self.total_cost_usd += cost
        return cost


@dataclass
class AnalysisResult:
    symbol: str
    score: int
    bias: str
    confidence: str
    findings: list
    warnings: list
    data_quality: str
    cost_estimate_usd: float
    model: str
    input_tokens: int
    output_tokens: int
    raw_response: Optional[str] = None


class ClaudeClient:
    """Claude API client for derivatives analysis."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.cost_tracker = CostTracker()

    def _build_prompt(self, market_data: Dict[str, Any], sources_failed: list) -> str:
        """Build analysis prompt from market data."""
        prompt_parts = [f"Analyze the following derivatives market data for {market_data.get('symbol', 'UNKNOWN')}:\n"]

        # Funding rates
        if "funding" in market_data:
            prompt_parts.append(f"## Funding Rate\n{json.dumps(market_data['funding'], indent=2, default=str)}\n")

        # Open interest
        if "open_interest" in market_data:
            prompt_parts.append(f"## Open Interest\n{json.dumps(market_data['open_interest'], indent=2, default=str)}\n")

        # Orderbook
        if "orderbook" in market_data:
            prompt_parts.append(f"## Orderbook\n{json.dumps(market_data['orderbook'], indent=2, default=str)}\n")

        # Long/short ratio
        if "long_short_ratio" in market_data:
            prompt_parts.append(f"## Long/Short Ratio\n{json.dumps(market_data['long_short_ratio'], indent=2, default=str)}\n")

        # Aggregated data
        if "aggregated_funding" in market_data:
            prompt_parts.append(f"## Aggregated Funding (Cross-Exchange)\n{json.dumps(market_data['aggregated_funding'], indent=2, default=str)}\n")

        if "aggregated_oi" in market_data:
            prompt_parts.append(f"## Aggregated Open Interest (Cross-Exchange)\n{json.dumps(market_data['aggregated_oi'], indent=2, default=str)}\n")

        if "liquidations" in market_data:
            prompt_parts.append(f"## Liquidations\n{json.dumps(market_data['liquidations'], indent=2, default=str)}\n")

        if "cross_exchange_ls" in market_data:
            prompt_parts.append(f"## Cross-Exchange Long/Short\n{json.dumps(market_data['cross_exchange_ls'], indent=2, default=str)}\n")

        # Note failed sources
        if sources_failed:
            prompt_parts.append(f"\n## Missing Data Sources\nThe following sources failed and are NOT included: {', '.join(sources_failed)}")
            prompt_parts.append("Adjust your confidence level accordingly.\n")

        return "\n".join(prompt_parts)

    async def analyze(
        self, market_data: Dict[str, Any], sources_failed: Optional[list] = None
    ) -> AnalysisResult:
        """Run Claude analysis on market data and return structured result."""
        sources_failed = sources_failed or []
        user_prompt = self._build_prompt(market_data, sources_failed)
        symbol = market_data.get("symbol", "UNKNOWN")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                        "system": ANALYSIS_SYSTEM_PROMPT,
                        "messages": [{"role": "user", "content": user_prompt}],
                    },
                )
                response.raise_for_status()
                resp_data = response.json()

            # Extract token usage
            usage = resp_data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cost = self.cost_tracker.record(self.model, input_tokens, output_tokens)

            # Extract text content
            content_blocks = resp_data.get("content", [])
            raw_text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    raw_text += block.get("text", "")

            # Parse JSON response
            parsed = json.loads(raw_text)

            # Clamp score
            score = max(-100, min(100, int(parsed.get("score", 0))))

            return AnalysisResult(
                symbol=symbol,
                score=score,
                bias=parsed.get("bias", "neutral"),
                confidence=parsed.get("confidence", "low"),
                findings=parsed.get("findings", []),
                warnings=parsed.get("warnings", []),
                data_quality=parsed.get("data_quality", "partial"),
                cost_estimate_usd=cost,
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                raw_response=raw_text,
            )

        except json.JSONDecodeError as e:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "claude_client",
                "event": "json_parse_failed",
                "symbol": symbol,
                "error": str(e),
            }))
            return AnalysisResult(
                symbol=symbol,
                score=0,
                bias="neutral",
                confidence="low",
                findings=["AI analysis failed to produce valid JSON"],
                warnings=["Response parsing error — treating as neutral"],
                data_quality="degraded",
                cost_estimate_usd=0.0,
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                raw_response=raw_text if 'raw_text' in dir() else None,
            )
        except Exception as e:
            logger.error(json.dumps({
                "severity": "ERROR",
                "component": "claude_client",
                "event": "analysis_failed",
                "symbol": symbol,
                "error": str(e),
            }))
            return AnalysisResult(
                symbol=symbol,
                score=0,
                bias="neutral",
                confidence="low",
                findings=["AI analysis request failed"],
                warnings=[f"API error: {str(e)}"],
                data_quality="degraded",
                cost_estimate_usd=0.0,
                model=self.model,
                input_tokens=0,
                output_tokens=0,
            )

    async def health_check(self) -> bool:
        """Minimal API connectivity test."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "max_tokens": 16,
                        "messages": [{"role": "user", "content": "Reply with: ok"}],
                    },
                )
                return response.status_code == 200
        except Exception:
            return False

    def get_cost_summary(self) -> Dict[str, Any]:
        return {
            "total_requests": self.cost_tracker.total_requests,
            "total_input_tokens": self.cost_tracker.total_input_tokens,
            "total_output_tokens": self.cost_tracker.total_output_tokens,
            "total_cost_usd": f"{self.cost_tracker.total_cost_usd:.6f}",
            "model": self.model,
        }
