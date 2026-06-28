"""
ATHENA – Telegram Alert System
Sends formatted trade alerts to a Telegram channel/group.
"""
import logging
import httpx
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.telegram")


class TelegramAlert:
    """Send ATHENA trade alerts via Telegram Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def send_alert(self, conf, idea=None):
        """Send a formatted trade alert."""
        if not config.ALERTS_ENABLED:
            log.debug(f"[Telegram disabled] Would alert: {conf.ticker} {conf.direction} @ {conf.confidence:.0f}")
            return

        message = self._format_alert(conf, idea)
        self._send(message)

    def send_recommendation(self, ticker: str, action: str, reason: str, current_price: float):
        """Send a trade management recommendation."""
        if not config.ALERTS_ENABLED:
            log.debug(f"[Telegram disabled] {ticker} → {action}: {reason}")
            return
        msg = (
            f"⚙️ *ATHENA TRADE MANAGEMENT*\n"
            f"Ticker: `{ticker}`\n"
            f"Action: *{action}*\n"
            f"Price: `${current_price:.2f}`\n"
            f"Reason: {reason}"
        )
        self._send(msg)

    def send_market_bias(self, bias):
        """Send daily premarket bias summary."""
        if not config.ALERTS_ENABLED:
            return
        emoji = "🟢" if bias.direction == "BULLISH" else "🔴" if bias.direction == "BEARISH" else "🟡"
        msg = (
            f"{emoji} *ATHENA PREMARKET BIAS*\n"
            f"Direction: *{bias.direction}* ({bias.strength:.0f}/100)\n"
            f"SPY: `${bias.spy_price:.2f}` ({bias.spy_change_pct:+.2f}%)\n"
            f"QQQ: `${bias.qqq_price:.2f}` ({bias.qqq_change_pct:+.2f}%)\n"
            f"VIX:  `{bias.vix_price:.2f}` ({bias.vix_change_pct:+.1f}%)\n"
            f"ES: `{bias.futures_es:.0f}` | NQ: `{bias.futures_nq:.0f}`"
        )
        self._send(msg)

    # ──────────────────────────────────────────────────────────────────────────

    def _format_alert(self, conf, idea) -> str:
        dir_emoji = "🟢" if conf.direction == "BULLISH" else "🔴"
        rr = f"{conf.risk_reward:.1f}:1" if conf.risk_reward else "N/A"
        lines = [
            f"{'='*30}",
            f"{dir_emoji} *ATHENA TRADE ALERT*",
            f"{'='*30}",
            f"Ticker:     `{conf.ticker}`",
            f"Direction:  *{conf.direction}*",
            f"Entry:      `${conf.entry:.2f}`"       if conf.entry  else "",
            f"Stop:       `${conf.stop:.2f}`"        if conf.stop   else "",
            f"Target 1:   `${conf.target1:.2f}`"     if conf.target1 else "",
            f"Target 2:   `${conf.target2:.2f}`"     if conf.target2 else "",
            f"R:R Ratio:  `{rr}`",
            f"Confidence: *{conf.confidence:.0f}/100*",
            f"",
            f"📊 *Price Action*",
            f"{conf.pa_summary}",
            f"",
            f"🌍 *Market Context*",
            f"{conf.ctx_summary}",
            f"",
            f"📈 *Quant Confirmation*",
            f"{conf.quant_summary}",
            f"",
            f"⛔ *Invalidation*",
            f"{conf.invalidation}",
        ]
        return "\n".join(l for l in lines if l is not None)

    def _send(self, text: str):
        try:
            url = self.BASE_URL.format(token=config.TELEGRAM_BOT_TOKEN)
            resp = httpx.post(url, json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            }, timeout=10)
            if not resp.is_success:
                log.error(f"Telegram error: {resp.status_code} {resp.text}")
            else:
                log.info("Telegram alert sent")
        except Exception as e:
            log.error(f"Telegram send failed: {e}")
