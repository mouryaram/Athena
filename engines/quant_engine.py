"""
ATHENA – Quant Engine
Rule #3: Quant Data NEVER creates a trade. It only CONFIRMS one.
Collects: Call Flow, Put Flow, Dark Pools, GEX, DEX, OI, Sweeps, Blocks.
Produces: confirmation_score (0-100).
"""
import logging
import random
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.quant")


@dataclass
class QuantResult:
    ticker: str
    call_flow: float           = 0.0    # net call premium ($M)
    put_flow: float            = 0.0    # net put premium ($M)
    flow_bias: str             = "NEUTRAL"
    dark_pool_prints: float    = 0.0    # total DP volume ($M)
    dark_pool_bias: str        = "NEUTRAL"
    gamma_exposure: float      = 0.0    # GEX in $B
    delta_exposure: float      = 0.0    # DEX
    open_interest_calls: float = 0.0
    open_interest_puts: float  = 0.0
    put_call_ratio: float      = 1.0
    sweeps_bullish: int        = 0
    sweeps_bearish: int        = 0
    block_trades: int          = 0
    confirmation_score: float  = 0.0   # 0-100 (only confirms, never initiates)
    summary: str               = ""
    raw: dict                  = field(default_factory=dict)


class QuantEngine:
    """
    Fetches and scores quantitative / options flow data.
    Score is used ONLY to confirm a price action trade.
    """

    def __init__(self):
        self._provider = config.QUANT_PROVIDER

    def analyze(self, ticker: str, direction_bias: Optional[str] = None) -> QuantResult:
        """Return quant confirmation for ticker, aligned with direction_bias."""
        if self._provider == "unusual_whales":
            try:
                return self._fetch_unusual_whales(ticker, direction_bias)
            except Exception as e:
                log.warning(f"Unusual Whales failed: {e}")
        if self._provider == "tradier":
            try:
                return self._fetch_tradier(ticker, direction_bias)
            except Exception as e:
                log.warning(f"Tradier failed: {e}")
        return self._mock_result(ticker, direction_bias)

    # ──────────────────────────────────────────────────────────────────────────
    # Provider Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_unusual_whales(self, ticker: str, bias: Optional[str]) -> QuantResult:
        """
        Unusual Whales API stub.
        Wire in your API key and endpoints here.
        API Docs: https://unusualwhales.com/api
        """
        import httpx
        headers = {"Authorization": f"Bearer {config.UNUSUAL_WHALES_KEY}"}
        base = "https://api.unusualwhales.com/api"

        flow  = httpx.get(f"{base}/stock/{ticker}/options-flow", headers=headers, timeout=10).json()
        dark  = httpx.get(f"{base}/darkpool/{ticker}", headers=headers, timeout=10).json()

        # Parse — shape depends on UW API version
        call_flow  = sum(t.get("premium", 0) for t in flow.get("data", []) if t.get("side") == "call") / 1e6
        put_flow   = sum(t.get("premium", 0) for t in flow.get("data", []) if t.get("side") == "put") / 1e6
        dp_volume  = sum(t.get("size", 0) * t.get("price", 0) for t in dark.get("data", [])) / 1e6
        sweeps_b   = sum(1 for t in flow.get("data", []) if t.get("type") == "sweep" and t.get("side") == "call")
        sweeps_br  = sum(1 for t in flow.get("data", []) if t.get("type") == "sweep" and t.get("side") == "put")
        blocks     = sum(1 for t in flow.get("data", []) if t.get("type") == "block")

        result = QuantResult(
            ticker=ticker,
            call_flow=round(call_flow, 2),
            put_flow=round(put_flow, 2),
            dark_pool_prints=round(dp_volume, 2),
            sweeps_bullish=sweeps_b,
            sweeps_bearish=sweeps_br,
            block_trades=blocks,
        )
        self._score(result, bias)
        return result

    def _fetch_tradier(self, ticker: str, bias: Optional[str]) -> QuantResult:
        """Tradier options chain stub."""
        import httpx
        headers = {"Authorization": f"Bearer {config.TRADIER_KEY}", "Accept": "application/json"}
        resp = httpx.get(
            "https://api.tradier.com/v1/markets/options/chains",
            params={"symbol": ticker, "expiration": "nearest", "greeks": "true"},
            headers=headers, timeout=10
        ).json()
        options = resp.get("options", {}).get("option", [])
        call_flow = sum(o.get("volume", 0) * o.get("last", 0) for o in options if o.get("option_type") == "call") / 1e6
        put_flow  = sum(o.get("volume", 0) * o.get("last", 0) for o in options if o.get("option_type") == "put") / 1e6
        oi_calls  = sum(o.get("open_interest", 0) for o in options if o.get("option_type") == "call")
        oi_puts   = sum(o.get("open_interest", 0) for o in options if o.get("option_type") == "put")
        pcr       = oi_puts / max(oi_calls, 1)

        result = QuantResult(
            ticker=ticker, call_flow=round(call_flow,2), put_flow=round(put_flow,2),
            open_interest_calls=oi_calls, open_interest_puts=oi_puts, put_call_ratio=round(pcr,2),
        )
        self._score(result, bias)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Mock Data
    # ──────────────────────────────────────────────────────────────────────────

    def _mock_result(self, ticker: str, bias: Optional[str]) -> QuantResult:
        bullish = bias == "BULLISH"
        result = QuantResult(
            ticker=ticker,
            call_flow=round(random.uniform(2 if bullish else 0.5, 8 if bullish else 3), 2),
            put_flow=round(random.uniform(0.5 if bullish else 2, 3 if bullish else 8), 2),
            dark_pool_prints=round(random.uniform(5, 40), 2),
            dark_pool_bias="BULLISH" if bullish else "BEARISH",
            gamma_exposure=round(random.uniform(-2, 2), 3),
            delta_exposure=round(random.uniform(-1, 1), 3),
            open_interest_calls=int(random.uniform(5000, 50000)),
            open_interest_puts=int(random.uniform(5000, 50000)),
            sweeps_bullish=random.randint(3 if bullish else 0, 12 if bullish else 5),
            sweeps_bearish=random.randint(0 if bullish else 3, 5 if bullish else 12),
            block_trades=random.randint(1, 8),
        )
        result.put_call_ratio = round(result.open_interest_puts / max(result.open_interest_calls, 1), 2)
        self._score(result, bias)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Scoring (0-100 confirmation only)
    # ──────────────────────────────────────────────────────────────────────────

    def _score(self, r: QuantResult, bias: Optional[str]):
        score = 50.0  # neutral baseline

        # Flow bias
        if r.call_flow > r.put_flow:
            r.flow_bias = "BULLISH"
            score += min(20, (r.call_flow - r.put_flow) * 4)
        elif r.put_flow > r.call_flow:
            r.flow_bias = "BEARISH"
            score -= min(20, (r.put_flow - r.call_flow) * 4)

        # Sweeps
        net_sweeps = r.sweeps_bullish - r.sweeps_bearish
        score += net_sweeps * 2

        # PCR
        if r.put_call_ratio < 0.7:   # low PCR = bullish
            score += 8
        elif r.put_call_ratio > 1.3: # high PCR = bearish
            score -= 8

        # Dark pool
        if r.dark_pool_bias == "BULLISH":
            score += 5
        elif r.dark_pool_bias == "BEARISH":
            score -= 5

        # Align with requested bias
        if bias == "BULLISH" and r.flow_bias == "BEARISH":
            score -= 15  # quant conflicts with PA bias
        elif bias == "BEARISH" and r.flow_bias == "BULLISH":
            score -= 15

        r.confirmation_score = round(max(0, min(100, score)), 1)
        r.summary = (
            f"Flow: {r.flow_bias} (C ${r.call_flow}M / P ${r.put_flow}M) | "
            f"PCR {r.put_call_ratio:.2f} | Sweeps {r.sweeps_bullish}B/{r.sweeps_bearish}B | "
            f"DP ${r.dark_pool_prints}M | Score {r.confirmation_score:.0f}/100"
        )
        log.debug(f"Quant [{r.ticker}] {r.summary}")
