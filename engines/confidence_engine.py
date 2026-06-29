"""
ATHENA – Confidence Engine
Combines all sub-scores into a final 0-100 confidence score.
Weights: Price Action 50%, MTF 20%, Market Context 10%, Quant 10%, Evidence 10%.
Rule: Price Action failure = NO TRADE, no matter the other scores.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.confidence")


@dataclass
class ConfidenceResult:
    ticker: str
    direction: str
    confidence: float           = 0.0      # 0-100 final score
    pa_score: float             = 0.0
    mtf_score: float            = 0.0
    ctx_score: float            = 0.0
    quant_score: float          = 0.0
    ev_score: float             = 0.0
    trade_allowed: bool         = False    # True only if >= threshold AND PA valid
    reason: str                 = ""
    entry: Optional[float]      = None
    stop: Optional[float]       = None
    target1: Optional[float]    = None
    target2: Optional[float]    = None
    risk_reward: Optional[float]= None
    pa_summary: str             = ""
    ctx_summary: str            = ""
    quant_summary: str          = ""
    invalidation: str           = ""


class ConfidenceEngine:
    """
    Aggregates all engine outputs into a single confidence score and trade decision.
    """

    WEIGHTS = config.CONFIDENCE_WEIGHTS

    def evaluate(
        self,
        ticker: str,
        direction: str,
        pa_result,            # PriceActionResult (from primary execution TF)
        mtf_result,           # MTFResult
        market_bias,          # MarketBias
        quant_result,         # QuantResult
        evidence_adj: float,  # -10 to +10 adjustment from EvidenceEngine
        spx_result=None,      # SPXResult (optional, for SPX/SPY trades)
    ) -> ConfidenceResult:

        result = ConfidenceResult(ticker=ticker, direction=direction)

        # ── Step 1: Price Action (Rule #1 — gates everything) ────────────────
        if not pa_result.valid:
            result.trade_allowed = False
            result.reason = f"NO TRADE – Price Action invalid: {pa_result.reason}"
            log.info(f"[{ticker}] {result.reason}")
            return result

        result.pa_score    = pa_result.score
        result.pa_summary  = pa_result.reason
        result.invalidation= pa_result.invalidation

        # ── Step 2: SPX/VIX check (Rule #4) ──────────────────────────────────
        if spx_result and ticker.upper() in ("SPX", "SPY", "QQQ", "ES", "NQ"):
            if not spx_result.vix_confirmed:
                result.trade_allowed = False
                result.reason = f"NO TRADE – VIX not confirmed for {direction} SPX trade"
                log.info(f"[{ticker}] {result.reason}")
                return result

        # ── Step 3: Multi-Timeframe score ─────────────────────────────────────
        result.mtf_score = mtf_result.alignment_score

        # ── Step 4: Market Context ────────────────────────────────────────────
        ctx_score = self._market_context_score(market_bias, direction, spx_result)
        result.ctx_score = ctx_score
        result.ctx_summary = market_bias.summary

        # ── Step 5: Quant Confirmation (Rule #3 — confirms, never creates) ────
        result.quant_score   = quant_result.confirmation_score
        result.quant_summary = quant_result.summary

        # ── Step 6: Evidence Adjustment ───────────────────────────────────────
        result.ev_score = max(-10, min(10, evidence_adj))

        # ── Step 7: Weighted Score ────────────────────────────────────────────
        raw = (
            result.pa_score   * (self.WEIGHTS["price_action"]       / 100) +
            result.mtf_score  * (self.WEIGHTS["multi_timeframe"]     / 100) +
            result.ctx_score  * (self.WEIGHTS["market_context"]      / 100) +
            result.quant_score* (self.WEIGHTS["quant_confirmation"]  / 100)
        )
        # Evidence adjustment is additive (±10)
        result.confidence = round(min(100, max(0, raw + result.ev_score)), 1)

        # ── Step 8: Trade Decision ────────────────────────────────────────────
        test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
        threshold = config.CONFIDENCE_THRESHOLD
        if result.confidence >= threshold or test_mode:
            result.trade_allowed = True
            prefix = "TEST ALERT – " if test_mode else "TRADE ALERT – "
            result.reason = (
                f"{prefix}Confidence {result.confidence:.0f}/100 "
                f"(threshold {threshold}) | {direction}"
            )
        else:
            result.trade_allowed = False
            result.reason = (
                f"NO TRADE – Confidence {result.confidence:.0f}/100 "
                f"below threshold {threshold}"
            )

        # ── Step 9: Risk/Reward ───────────────────────────────────────────────
        result.entry   = pa_result.raw.get("closes", [None])[-1]
        result.stop    = pa_result.raw.get("support" if direction == "BULLISH" else "resistance")
        result.target1 = pa_result.raw.get("fib_618") or pa_result.raw.get("resistance")
        result.target2 = pa_result.raw.get("resistance") if direction == "BULLISH" else pa_result.raw.get("support")

        if result.entry and result.stop and result.target1:
            risk   = abs(result.entry - result.stop)
            reward = abs(result.target1 - result.entry)
            result.risk_reward = round(reward / max(risk, 0.01), 2)
            # Skip R:R check in TEST_MODE — mock data produces unrealistic ratios
            if result.risk_reward < config.MIN_REWARD_RATIO and not test_mode:
                result.trade_allowed = False
                result.reason = (
                    f"NO TRADE – R:R {result.risk_reward:.1f} below minimum {config.MIN_REWARD_RATIO}"
                )

        log.info(f"[{ticker}] Confidence={result.confidence:.0f} | {result.reason}")
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Market Context Scorer
    # ──────────────────────────────────────────────────────────────────────────

    def _market_context_score(self, bias, direction: str, spx=None) -> float:
        score = 50.0

        # Market bias alignment
        if direction == "BULLISH" and bias.direction == "BULLISH":
            score += 25
        elif direction == "BEARISH" and bias.direction == "BEARISH":
            score += 25
        elif bias.direction == "NEUTRAL":
            score += 0
        else:
            score -= 20   # trading against market

        # VIX context
        if bias.vix_price < 15:
            score += 10
        elif bias.vix_price > 25:
            score -= 10

        # Breadth
        if bias.breadth_adv_dec > 1.5 and direction == "BULLISH":
            score += 10
        elif bias.breadth_adv_dec < 0.7 and direction == "BEARISH":
            score += 10

        # SPX engine bonus
        if spx:
            score += (spx.spx_score - 50) * 0.2

        return round(max(0, min(100, score)), 1)
