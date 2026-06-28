"""
ATHENA – SPX Engine
Rule #4: SPX requires VIX confirmation.
  Bullish SPX → VIX must be weak (falling/low)
  Bearish SPX → VIX must be strong (rising/high)
Dedicated logic for SPX/SPY, VIX, Gamma, 0DTE, Breadth, Time-of-day.
"""
import logging
import random
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("athena.spx")

# Key VIX thresholds
VIX_LOW       = 15.0   # calm market
VIX_ELEVATED  = 20.0   # caution
VIX_HIGH      = 25.0   # fear
VIX_EXTREME   = 35.0   # extreme fear

# Time-of-day regimes (ET)
OPEN_PERIOD   = (time(9, 30), time(10, 30))   # high volatility open
MIDDAY_PERIOD = (time(11, 0), time(13, 0))    # chop / low volatility
LUNCH_PERIOD  = (time(12, 0), time(13, 0))    # avoid
AFTERNOON     = (time(13, 0), time(15, 0))    # trend resumes
POWER_HOUR    = (time(15, 0), time(16, 0))    # high vol / reversals


@dataclass
class SPXResult:
    direction: str              = "NEUTRAL"
    vix_confirmed: bool         = False
    vix_price: float            = 0.0
    vix_trend: str              = "NEUTRAL"    # RISING | FALLING | STABLE
    vix_regime: str             = "CALM"       # CALM | ELEVATED | HIGH | EXTREME
    gamma_regime: str           = "NEUTRAL"    # POSITIVE | NEGATIVE | NEUTRAL
    gamma_exposure: float       = 0.0
    zero_dte_risk: bool         = False        # True = elevated 0DTE pin risk
    breadth_score: float        = 50.0         # 0-100
    time_regime: str            = "NORMAL"     # OPEN_VOL | MIDDAY_CHOP | TREND | POWER_HOUR | AVOID
    favorable_time: bool        = True
    spx_score: float            = 0.0          # 0-100
    summary: str                = ""


class SPXEngine:
    """SPX-specific engine integrating VIX, Gamma, 0DTE, Breadth, and time-of-day."""

    def analyze(
        self,
        direction: str,
        vix_price: float,
        vix_change_pct: float,
        breadth_adv_dec: Optional[float] = None,
        gamma_exposure: Optional[float]  = None,
        now: Optional[datetime]          = None,
    ) -> SPXResult:
        result = SPXResult(direction=direction, vix_price=vix_price)
        self._analyze_vix(result, vix_price, vix_change_pct, direction)
        self._analyze_gamma(result, gamma_exposure)
        self._analyze_breadth(result, breadth_adv_dec)
        self._analyze_time(result, now or datetime.now())
        self._score(result)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # VIX Analysis (Rule #4)
    # ──────────────────────────────────────────────────────────────────────────

    def _analyze_vix(self, r: SPXResult, vix: float, vix_chg: float, direction: str):
        # Regime
        if vix < VIX_LOW:
            r.vix_regime = "CALM"
        elif vix < VIX_ELEVATED:
            r.vix_regime = "ELEVATED"
        elif vix < VIX_HIGH:
            r.vix_regime = "HIGH"
        else:
            r.vix_regime = "EXTREME"

        # VIX trend (based on daily change)
        if vix_chg > 3:
            r.vix_trend = "RISING"
        elif vix_chg < -3:
            r.vix_trend = "FALLING"
        else:
            r.vix_trend = "STABLE"

        # Confirmation logic (Rule #4)
        if direction == "BULLISH":
            # VIX must be weak/falling
            r.vix_confirmed = (
                r.vix_trend in ("FALLING", "STABLE") and
                r.vix_regime in ("CALM", "ELEVATED")
            )
        elif direction == "BEARISH":
            # VIX must be strong/rising
            r.vix_confirmed = (
                r.vix_trend in ("RISING", "STABLE") and
                r.vix_regime in ("ELEVATED", "HIGH", "EXTREME")
            )
        else:
            r.vix_confirmed = True   # neutral doesn't require VIX confirmation

    # ──────────────────────────────────────────────────────────────────────────
    # Gamma Analysis
    # ──────────────────────────────────────────────────────────────────────────

    def _analyze_gamma(self, r: SPXResult, gex: Optional[float]):
        if gex is None:
            gex = random.uniform(-2, 2)
        r.gamma_exposure = round(gex, 3)
        if gex > 0.5:
            r.gamma_regime = "POSITIVE"   # market makers short gamma → mean reversion
        elif gex < -0.5:
            r.gamma_regime = "NEGATIVE"   # MMs long gamma → trending / higher vol
        else:
            r.gamma_regime = "NEUTRAL"

        # 0DTE risk: near expiry with extreme gamma
        if abs(gex) > 3:
            r.zero_dte_risk = True

    # ──────────────────────────────────────────────────────────────────────────
    # Breadth Analysis
    # ──────────────────────────────────────────────────────────────────────────

    def _analyze_breadth(self, r: SPXResult, adv_dec: Optional[float]):
        if adv_dec is None:
            adv_dec = random.uniform(0.5, 2.5)
        # A/D ratio → 0-100 score
        if adv_dec >= 2.0:
            r.breadth_score = 90
        elif adv_dec >= 1.5:
            r.breadth_score = 70
        elif adv_dec >= 1.0:
            r.breadth_score = 50
        elif adv_dec >= 0.7:
            r.breadth_score = 30
        else:
            r.breadth_score = 10

    # ──────────────────────────────────────────────────────────────────────────
    # Time-of-Day Regime
    # ──────────────────────────────────────────────────────────────────────────

    def _analyze_time(self, r: SPXResult, now: datetime):
        t = now.time()
        if OPEN_PERIOD[0] <= t < OPEN_PERIOD[1]:
            r.time_regime = "OPEN_VOL"
            r.favorable_time = True
        elif LUNCH_PERIOD[0] <= t < LUNCH_PERIOD[1]:
            r.time_regime = "AVOID"
            r.favorable_time = False
        elif MIDDAY_PERIOD[0] <= t < MIDDAY_PERIOD[1]:
            r.time_regime = "MIDDAY_CHOP"
            r.favorable_time = False
        elif AFTERNOON[0] <= t < AFTERNOON[1]:
            r.time_regime = "TREND"
            r.favorable_time = True
        elif POWER_HOUR[0] <= t < POWER_HOUR[1]:
            r.time_regime = "POWER_HOUR"
            r.favorable_time = True
        else:
            r.time_regime = "NORMAL"
            r.favorable_time = False

    # ──────────────────────────────────────────────────────────────────────────
    # Scoring
    # ──────────────────────────────────────────────────────────────────────────

    def _score(self, r: SPXResult):
        score = 50.0

        # VIX confirmation is critical for SPX (Rule #4)
        if r.vix_confirmed:
            score += 25
        else:
            score -= 30   # harsh penalty for VIX violation

        # Breadth
        score += (r.breadth_score - 50) * 0.3

        # Gamma
        if r.gamma_regime == "NEGATIVE":
            score += 10   # trending environment is better for directional trades
        elif r.gamma_regime == "POSITIVE":
            score -= 5

        # 0DTE risk
        if r.zero_dte_risk:
            score -= 10

        # Time
        if not r.favorable_time:
            score -= 15

        r.spx_score = round(max(0, min(100, score)), 1)
        r.summary = (
            f"VIX {r.vix_price:.2f} ({r.vix_regime}/{r.vix_trend}) | "
            f"VIX {'✓' if r.vix_confirmed else '✗'} | "
            f"Gamma {r.gamma_regime} | "
            f"Breadth {r.breadth_score:.0f}/100 | "
            f"Time {r.time_regime} | "
            f"Score {r.spx_score:.0f}/100"
        )
        log.debug(f"SPX: {r.summary}")
