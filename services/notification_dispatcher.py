"""
Notification dispatcher for sending signals via multiple channels.

Primary: Slack Block Kit messages with color-coded scores.
Also supports: webhook, email (SMTP), Telegram.
"""

import os
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

import httpx

from config.schema import NotificationConfig, NotificationChannel

logger = logging.getLogger(__name__)


@dataclass
class NotificationResult:
    """Result of notification dispatch."""
    channel: str
    success: bool
    message: str


def _score_color(score: int) -> str:
    """Map score to hex color for Slack."""
    if score >= 30:
        return "#2ecc71"  # Green (bullish)
    elif score <= -30:
        return "#e74c3c"  # Red (bearish)
    else:
        return "#f39c12"  # Yellow (neutral)


def _score_emoji(score: int) -> str:
    if score >= 50:
        return "🟢"
    elif score >= 30:
        return "🟡"
    elif score <= -50:
        return "🔴"
    elif score <= -30:
        return "🟠"
    else:
        return "⚪"


def _bias_label(bias: str) -> str:
    labels = {
        "strong_bullish": "STRONG BULLISH",
        "bullish": "BULLISH",
        "neutral": "NEUTRAL",
        "bearish": "BEARISH",
        "strong_bearish": "STRONG BEARISH",
    }
    return labels.get(bias, bias.upper())


class NotificationDispatcher:
    """Dispatches signal reports to configured notification channels."""

    def __init__(self, config: NotificationConfig):
        self.config = config

    async def dispatch(self, signal: Dict[str, Any]) -> List[NotificationResult]:
        """Dispatch signal to all configured channels."""
        results = []
        for channel in self.config.channels:
            if channel == NotificationChannel.SLACK:
                result = await self._send_slack(signal)
            elif channel == NotificationChannel.WEBHOOK:
                result = await self._send_webhook(signal)
            elif channel == NotificationChannel.EMAIL:
                result = await self._send_email(signal)
            elif channel == NotificationChannel.TELEGRAM:
                result = await self._send_telegram(signal)
            else:
                result = NotificationResult(
                    channel=channel.value, success=False,
                    message=f"Unknown channel: {channel}"
                )
            results.append(result)
            logger.info(json.dumps({
                "severity": "INFO" if result.success else "ERROR",
                "component": "notification_dispatcher",
                "channel": result.channel,
                "symbol": signal.get("symbol"),
                "success": result.success,
                "message": result.message,
            }))
        return results

    async def _send_slack(self, signal: Dict[str, Any]) -> NotificationResult:
        """Send signal via Slack Block Kit message."""
        webhook_url = self.config.slack.webhook_url
        if not webhook_url:
            return NotificationResult(
                channel="slack", success=False, message="No Slack webhook URL configured"
            )

        score = signal.get("score", 0)
        symbol = signal.get("symbol", "UNKNOWN")
        bias = signal.get("bias", "neutral")
        confidence = signal.get("confidence", "low")
        findings = signal.get("findings", [])
        warnings = signal.get("warnings", [])
        disclaimer = signal.get("disclaimer", "")
        cost = signal.get("cost_estimate_usd", "0")
        data_quality = signal.get("data_quality", "unknown")

        emoji = _score_emoji(score)
        color = _score_color(score)
        label = _bias_label(bias)

        # Format findings as bullet list
        findings_text = "\n".join(f"  • {f}" for f in findings[:8]) if findings else "  _No findings_"
        warnings_text = "\n".join(f"  ⚠️ {w}" for w in warnings[:5]) if warnings else ""

        # Build Slack Block Kit message
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {symbol} Derivatives Signal",
                }
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Score:* {score}/100"},
                    {"type": "mrkdwn", "text": f"*Bias:* {label}"},
                    {"type": "mrkdwn", "text": f"*Confidence:* {confidence.upper()}"},
                    {"type": "mrkdwn", "text": f"*Data Quality:* {data_quality}"},
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Key Findings:*\n{findings_text}"}
            },
        ]

        if warnings_text:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Warnings:*\n{warnings_text}"}
            })

        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Cost: ${cost} | {disclaimer}"},
            ]
        })

        # Mention on strong signals
        mention = self.config.slack.mention_on_strong
        if mention and abs(score) >= 50:
            blocks.insert(1, {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<{mention}> Strong signal detected!"}
            })

        payload = {
            "blocks": blocks,
            "attachments": [{"color": color, "blocks": []}],
        }

        if self.config.slack.channel:
            payload["channel"] = self.config.slack.channel

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
                return NotificationResult(
                    channel="slack", success=True, message="Slack message sent"
                )
        except Exception as e:
            return NotificationResult(channel="slack", success=False, message=str(e))

    async def _send_webhook(self, signal: Dict[str, Any]) -> NotificationResult:
        """Send signal via generic webhook."""
        url = self.config.webhook.url
        if not url:
            return NotificationResult(
                channel="webhook", success=False, message="No webhook URL configured"
            )

        try:
            headers = {"Content-Type": "application/json"}
            if self.config.webhook.headers:
                headers.update(self.config.webhook.headers)

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=signal, headers=headers)
                response.raise_for_status()
                return NotificationResult(
                    channel="webhook", success=True,
                    message=f"Webhook sent: {response.status_code}"
                )
        except Exception as e:
            return NotificationResult(channel="webhook", success=False, message=str(e))

    async def _send_email(self, signal: Dict[str, Any]) -> NotificationResult:
        """Send signal via email (SMTP)."""
        email_config = self.config.email
        if not email_config.smtp_host or not email_config.email_to:
            return NotificationResult(
                channel="email", success=False, message="SMTP not configured"
            )

        smtp_password = os.getenv("SMTP_PASSWORD")
        if not smtp_password:
            return NotificationResult(
                channel="email", success=False, message="SMTP_PASSWORD env var not set"
            )

        score = signal.get("score", 0)
        symbol = signal.get("symbol", "UNKNOWN")
        bias = _bias_label(signal.get("bias", "neutral"))
        findings = signal.get("findings", [])
        disclaimer = signal.get("disclaimer", "")

        try:
            msg = MIMEMultipart()
            msg["From"] = email_config.email_from or email_config.smtp_user
            msg["To"] = ", ".join(email_config.email_to)
            msg["Subject"] = f"[{bias}] {symbol} Derivatives Signal: {score}/100"

            body = f"""Derivatives Signal Agent

Symbol: {symbol}
Score: {score}/100
Bias: {bias}
Confidence: {signal.get('confidence', 'low').upper()}

Key Findings:
{chr(10).join(f'  - {f}' for f in findings)}

---
{disclaimer}
"""
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(email_config.smtp_host, email_config.smtp_port) as server:
                server.starttls()
                server.login(email_config.smtp_user, smtp_password)
                server.send_message(msg)

            return NotificationResult(
                channel="email", success=True,
                message=f"Email sent to {len(email_config.email_to)} recipients"
            )
        except Exception as e:
            return NotificationResult(channel="email", success=False, message=str(e))

    async def _send_telegram(self, signal: Dict[str, Any]) -> NotificationResult:
        """Send signal via Telegram Bot API."""
        chat_id = self.config.telegram.chat_id
        if not chat_id:
            return NotificationResult(
                channel="telegram", success=False,
                message="Telegram chat ID not configured"
            )

        bot_token = os.getenv(self.config.telegram.bot_token_env)
        if not bot_token:
            return NotificationResult(
                channel="telegram", success=False,
                message=f"{self.config.telegram.bot_token_env} not set"
            )

        score = signal.get("score", 0)
        symbol = signal.get("symbol", "UNKNOWN")
        bias = _bias_label(signal.get("bias", "neutral"))
        emoji = _score_emoji(score)
        findings = signal.get("findings", [])
        disclaimer = signal.get("disclaimer", "")

        findings_text = "\n".join(f"  - {f}" for f in findings[:5])

        message = f"""{emoji} *{symbol} Derivatives Signal*

*Score:* {score}/100
*Bias:* {bias}
*Confidence:* {signal.get('confidence', 'low').upper()}

*Key Findings:*
{findings_text}

_{disclaimer}_"""

        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                })
                response.raise_for_status()
                return NotificationResult(
                    channel="telegram", success=True, message="Telegram message sent"
                )
        except Exception as e:
            return NotificationResult(
                channel="telegram", success=False, message=str(e)
            )

    async def test_channel(self, channel: NotificationChannel) -> NotificationResult:
        """Send a test notification to verify channel configuration."""
        test_signal = {
            "symbol": "TEST",
            "score": 42,
            "bias": "bullish",
            "confidence": "high",
            "findings": ["This is a test signal from Derivatives Signal Agent"],
            "warnings": [],
            "data_quality": "test",
            "cost_estimate_usd": "0.000000",
            "disclaimer": "Test message — not a real signal.",
        }
        self.config.channels = [channel]
        results = await self.dispatch(test_signal)
        return results[0] if results else NotificationResult(
            channel=channel.value, success=False, message="No result"
        )
