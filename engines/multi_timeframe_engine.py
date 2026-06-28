"""
ATHENA – Multi-Timeframe Engine
Rule #2: Higher TFs determine direction. Lower TFs determine execution.
Outputs: Alignment Score, Direction, Trend Strength.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from engines.price_action_engine import PriceActionEngine, PriceActionResult

log = logging.getLogger("athena.mtf")


@dataclass
class MTFResult:
    ticker: str
    direction: str          = "NEUTRAL"
    alignment_score: float  = 0.0        # 0-100
    trend_strength: float   = 0.0        # 0-100
    timeframe_results: dict = field(default_factory=dict)
    # Individual TF alignments
    daily_trend: str        = "NEUTRAL"
    h4_trend: str           = "NEUTRAL"
    h1_trend: str           = "NEUTRAL"
    m15_trend: str          = "NEUTRAL"
    m5_trend: str           = "NEUTRAL"
    m1_trend: str           = "NEUTRAL"
    aligned_count: int      = 0
    conflicts: list         = field(default_factory=list)
    summary: str            = ""


class MultiTimeframeEngine:
    """
    Runs Price Action analysis across all 6 timeframes.
    Higher timeframes get more weight.
    """

    # Weights must sum to 100
    TF_WEIGHTS = {
        "1d":  30,
        "4h":  25,
        "1h":  20,
        "15m": 13,
        "5m":  8,
        "1m":  4,
    }

    TF_ATTR = {
        "1d": "daily_trend", "4h": "h4_trend", "1h": "h1_trend",
        "15m": "m15_trend",  "5m": "m5_trend", "1m": "m1_trend",
    }

    def __init__(self):
        self._pa = PriceActionEngine()

    def analyze(self, ticker: str, direction_bias: Optional[str] = None) -> MTFResult:
        result = MTFResult(ticker=ticker)
        tf_results: dict[str, PriceActionResult] = {}
        weighted_score = 0.0
        bullish_weight = 0.0
        bearish_weight = 0.0

        for tf, weight in self.TF_WEIGHTS.items():
            pa = self._pa.analyze(ticker, tf, direction_bias=direction_bias)
            tf_results[tf] = pa
            attr = self.TF_ATTR[tf]
            setattr(result, attr, pa.trend)
            # Accumulate directional weight
            if pa.trend in ("UPTREND",):
                bullish_weight += weight
            elif pa.trend in ("DOWNTREND",):
                bearish_weight += weight
            weighted_score += (pa.score / 100) * weight

        result.timeframe_results = {tf: {
            "trend": r.trend, "structure": r.structure, "score": r.score,
            "bos": r.last_bos, "choch": r.last_choch, "valid": r.valid,
        } for tf, r in tf_results.items()}

        # Direction from dominant weight
        if bullish_weight > bearish_weight and bullish_weight >= 40:
            result.direction = "BULLISH"
        elif bearish_weight > bullish_weight and bearish_weight >= 40:
            result.direction = "BEARISH"
        else:
            result.direction = "NEUTRAL"

        # Alignment score: how many TFs agree with dominant direction
        dominant = result.direction
        aligned = 0
        for tf, pa in tf_results.items():
            if dominant == "BULLISH" and pa.trend == "UPTREND":
                aligned += 1
            elif dominant == "BEARISH" and pa.trend == "DOWNTREND":
                aligned += 1
            elif dominant == "NEUTRAL" and pa.trend in ("RANGING", "NEUTRAL"):
                aligned += 1
            else:
                result.conflicts.append(tf)

        result.aligned_count = aligned
        result.alignment_score = round(weighted_score, 1)
        result.trend_strength  = round(
            (bullish_weight if dominant == "BULLISH" else bearish_weight if dominant == "BEARISH" else 0)
            / sum(self.TF_WEIGHTS.values()) * 100, 1
        )

        result.summary = (
            f"{dominant} | Alignment {result.alignment_score:.0f}/100 | "
            f"Strength {result.trend_strength:.0f}/100 | "
            f"{aligned}/{len(self.TF_WEIGHTS)} TFs aligned"
        )
        log.info(f"MTF [{ticker}] {result.summary}")
        return result
