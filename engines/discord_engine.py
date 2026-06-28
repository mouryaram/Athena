"""
ATHENA – Discord Learning Engine
Reads professional watchlists (pasted text).
Extracts: Ticker, Direction, Trigger, Stop, Target, Notes.
ATHENA never copies Discord trades — it validates them using its own rules.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.discord")


@dataclass
class DiscordIdea:
    ticker: str
    direction: str              = "NEUTRAL"
    trigger: Optional[float]   = None
    stop: Optional[float]      = None
    target: Optional[float]    = None
    target2: Optional[float]   = None
    notes: str                 = ""
    raw_text: str              = ""
    validated: bool            = False
    validation_score: float    = 0.0
    athena_agrees: bool        = False
    reason: str                = ""


class DiscordEngine:
    """
    Parses raw Discord watchlist text into structured DiscordIdea objects.
    Then validates each idea against ATHENA's price action rules.
    """

    # Regex patterns for common watchlist formats
    TICKER_PATTERN = re.compile(r'\b([A-Z]{1,5})\b')
    PRICE_PATTERN  = re.compile(r'\$?([\d]+\.[\d]{0,2})')
    DIR_BULLISH    = re.compile(r'\b(bull|long|calls?|upside|buy)\b', re.I)
    DIR_BEARISH    = re.compile(r'\b(bear|short|puts?|downside|sell)\b', re.I)
    STOP_PATTERN   = re.compile(r'stop[\s:@]?\$?([\d]+\.[\d]{0,2})', re.I)
    TARGET_PATTERN = re.compile(r'(?:target|tp|tgt)[\s:@]?\$?([\d]+\.[\d]{0,2})', re.I)
    TRIGGER_PATTERN= re.compile(r'(?:trigger|entry|above|below|over|under)[\s:@]?\$?([\d]+\.[\d]{0,2})', re.I)

    def parse_watchlist(self, text: str) -> list[DiscordIdea]:
        """Parse a raw pasted Discord watchlist into structured ideas."""
        ideas: list[DiscordIdea] = []
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

        for line in lines:
            idea = self._parse_line(line)
            if idea:
                ideas.append(idea)

        log.info(f"Discord: parsed {len(ideas)} ideas from {len(lines)} lines")
        return ideas

    def parse_file(self, filepath: Optional[str] = None) -> list[DiscordIdea]:
        """Read Discord watchlist from a text file."""
        fp = filepath or config.DISCORD_WATCHLIST_FILE
        if not os.path.exists(fp):
            log.warning(f"Discord watchlist file not found: {fp}")
            return self._mock_ideas()
        with open(fp, "r") as f:
            return self.parse_watchlist(f.read())

    def validate(self, ideas: list[DiscordIdea], pa_engine, market_bias) -> list[DiscordIdea]:
        """
        Validate each Discord idea using ATHENA's price action rules.
        NEVER blindly copies the idea — uses our own analysis.
        """
        validated = []
        for idea in ideas:
            try:
                pa = pa_engine.analyze(
                    idea.ticker,
                    timeframe="1h",
                    direction_bias=idea.direction,
                )
                idea.validated = True
                idea.validation_score = pa.score
                idea.athena_agrees = (
                    pa.valid and
                    self._direction_aligns(idea.direction, pa.trend) and
                    self._direction_aligns(idea.direction, market_bias.direction)
                )
                idea.reason = (
                    f"ATHENA {'agrees' if idea.athena_agrees else 'disagrees'}: "
                    f"PA score {pa.score:.0f}/100 | {pa.reason}"
                )
            except Exception as e:
                idea.reason = f"Validation error: {e}"
            validated.append(idea)

        agreed = sum(1 for i in validated if i.athena_agrees)
        log.info(f"Discord validation: {agreed}/{len(validated)} ideas ATHENA agrees with")
        return validated

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_line(self, line: str) -> Optional[DiscordIdea]:
        """Extract idea from a single watchlist line."""
        # Find ticker (first all-caps word 1-5 chars)
        tickers = [t for t in self.TICKER_PATTERN.findall(line) if len(t) >= 1 and t not in {
            "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "ANY",
            "CAN", "HER", "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS",
            "HIM", "HIS", "HOW", "ITS", "LET", "MAY", "NEW", "NOW", "OLD",
            "OWN", "WAY", "WHO", "WHY", "SPX", "SPY", "QQQ", "VIX",
        }]
        if not tickers:
            # Still allow SPX, SPY, QQQ explicitly
            for special in ["SPX", "SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "META", "AMZN"]:
                if special in line.upper():
                    tickers = [special]
                    break
        if not tickers:
            return None

        ticker = tickers[0].upper()

        # Direction
        direction = "NEUTRAL"
        if self.DIR_BULLISH.search(line):
            direction = "BULLISH"
        elif self.DIR_BEARISH.search(line):
            direction = "BEARISH"

        # Prices
        prices = [float(p) for p in self.PRICE_PATTERN.findall(line)]

        stop_m    = self.STOP_PATTERN.search(line)
        target_m  = self.TARGET_PATTERN.search(line)
        trigger_m = self.TRIGGER_PATTERN.search(line)

        stop    = float(stop_m.group(1))    if stop_m    else (prices[2] if len(prices) > 2 else None)
        target  = float(target_m.group(1)) if target_m  else (prices[1] if len(prices) > 1 else None)
        trigger = float(trigger_m.group(1)) if trigger_m else (prices[0] if prices else None)

        return DiscordIdea(
            ticker=ticker,
            direction=direction,
            trigger=trigger,
            stop=stop,
            target=target,
            notes=line,
            raw_text=line,
        )

    def _direction_aligns(self, idea_dir: str, trend_or_bias: str) -> bool:
        if idea_dir == "BULLISH":
            return trend_or_bias in ("BULLISH", "UPTREND")
        if idea_dir == "BEARISH":
            return trend_or_bias in ("BEARISH", "DOWNTREND")
        return True

    def _mock_ideas(self) -> list[DiscordIdea]:
        """Return demo ideas when no Discord file is found."""
        return [
            DiscordIdea("NVDA", "BULLISH", 875.0, 860.0, 900.0, 920.0,
                        "NVDA bull above 875 stop 860 target 900/920", raw_text="[MOCK]"),
            DiscordIdea("AAPL", "BEARISH", 182.0, 185.0, 175.0, 170.0,
                        "AAPL short below 182 stop 185 target 175/170", raw_text="[MOCK]"),
            DiscordIdea("QQQ",  "BULLISH", 458.0, 452.0, 465.0, None,
                        "QQQ calls above 458 stop 452 target 465",      raw_text="[MOCK]"),
        ]
