"""
ATHENA – Market Engine
Collects SPY, QQQ, SPX, VIX, Futures, Sector ETFs, Breadth, Calendar, News.
Produces a market bias object consumed by all other engines.
"""
import logging
import random
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger("athena.market")


@dataclass
class MarketBias:
    direction: str          = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    strength: float         = 50.0        # 0-100
    spy_price: float        = 0.0
    spy_change_pct: float   = 0.0
    qqq_price: float        = 0.0
    qqq_change_pct: float   = 0.0
    vix_price: float        = 0.0
    vix_change_pct: float   = 0.0
    spx_price: float        = 0.0
    futures_es: float       = 0.0
    futures_nq: float       = 0.0
    breadth_adv_dec: float  = 1.0         # >1 bullish, <1 bearish
    above_vwap_pct: float   = 50.0
    sector_data: dict       = field(default_factory=dict)
    economic_events: list   = field(default_factory=list)
    summary: str            = ""
    timestamp: datetime     = field(default_factory=datetime.utcnow)


class MarketEngine:
    """Fetches and aggregates top-level market data."""

    def __init__(self):
        self._provider = config.MARKET_DATA_PROVIDER
        self._last_bias: Optional[MarketBias] = None

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def get_bias(self) -> MarketBias:
        """Return current market bias. Uses real data if provider is configured."""
        if self._provider == "yfinance":
            try:
                return self._fetch_yfinance()
            except Exception as e:
                log.warning(f"yfinance fetch failed ({e}), falling back to mock")
        return self._mock_bias()

    def get_economic_calendar(self) -> list[dict]:
        """Return today's high-impact economic events."""
        return self._mock_calendar()

    # ──────────────────────────────────────────────────────────────────────────
    # Real Data (yfinance)
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_yfinance(self) -> MarketBias:
        import yfinance as yf

        def fetch_quote_http(symbol):
            """Fetch via Yahoo Finance JSON API — strict timeouts to avoid hanging."""
            import requests as req_lib
            encoded = symbol.replace("^", "%5E")
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json",
            }
            for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
                try:
                    url  = f"{base}/v8/finance/chart/{encoded}?interval=1d&range=5d"
                    resp = req_lib.get(url, headers=headers, timeout=(3, 7))
                    resp.raise_for_status()
                    data   = resp.json()
                    meta   = data["chart"]["result"][0]["meta"]
                    price  = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
                    prev   = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
                    chg    = round((price - prev) / prev * 100, 2) if prev else 0.0
                    if price > 0:
                        return price, chg
                except Exception:
                    continue
            return 0.0, 0.0

        def fetch_quote(symbol):
            """Try yfinance fast_info first, fall back to direct HTTP."""
            try:
                t = yf.Ticker(symbol)
                info = t.fast_info
                price = float(info.last_price or 0)
                prev  = float(info.previous_close or 0)
                if price > 0:
                    chg = round((price - prev) / prev * 100, 2) if prev else 0.0
                    return price, chg
            except Exception:
                pass
            return fetch_quote_http(symbol)

        spy,  spy_chg  = fetch_quote("SPY")
        qqq,  qqq_chg  = fetch_quote("QQQ")
        vix,  vix_chg  = fetch_quote("^VIX")
        spx,  _        = fetch_quote("^GSPC")
        es,   _        = fetch_quote("ES=F")
        nq,   _        = fetch_quote("NQ=F")

        if spy == 0.0 and qqq == 0.0:
            raise ValueError("Core tickers returned 0 — yfinance unreachable")

        sector_data = {}
        for s in config.SECTOR_ETFS:
            try:
                price, chg = fetch_quote(s)
                sector_data[s] = chg
            except Exception:
                sector_data[s] = 0.0

        direction, strength = self._compute_direction(spy_chg, qqq_chg, vix, vix_chg)
        bias = MarketBias(
            direction=direction,
            strength=strength,
            spy_price=spy,
            spy_change_pct=spy_chg,
            qqq_price=qqq,
            qqq_change_pct=qqq_chg,
            vix_price=vix,
            vix_change_pct=vix_chg,
            spx_price=spx,
            futures_es=es,
            futures_nq=nq,
            sector_data=sector_data,
            economic_events=self._mock_calendar(),
        )
        bias.summary = self._build_summary(bias)
        self._last_bias = bias
        log.info(f"Market bias: {direction} (strength={strength:.0f})")
        return bias

    # ──────────────────────────────────────────────────────────────────────────
    # Mock Data (fallback / dev mode)
    # ──────────────────────────────────────────────────────────────────────────

    def _mock_bias(self) -> MarketBias:
        spy_chg = round(random.uniform(-1.5, 1.5), 2)
        qqq_chg = round(spy_chg + random.uniform(-0.3, 0.3), 2)
        vix = round(random.uniform(14, 22), 2)
        vix_chg = round(random.uniform(-5, 5), 2)
        sector_data = {s: round(random.uniform(-1.5, 1.5), 2) for s in config.SECTOR_ETFS}
        direction, strength = self._compute_direction(spy_chg, qqq_chg, vix, vix_chg)
        bias = MarketBias(
            direction=direction,
            strength=strength,
            spy_price=round(random.uniform(500, 530), 2),
            spy_change_pct=spy_chg,
            qqq_price=round(random.uniform(440, 470), 2),
            qqq_change_pct=qqq_chg,
            vix_price=vix,
            vix_change_pct=vix_chg,
            spx_price=round(random.uniform(5000, 5300), 2),
            futures_es=round(random.uniform(5000, 5300), 2),
            futures_nq=round(random.uniform(18000, 19000), 2),
            breadth_adv_dec=round(random.uniform(0.5, 2.0), 2),
            above_vwap_pct=round(random.uniform(30, 80), 1),
            sector_data=sector_data,
            economic_events=self._mock_calendar(),
        )
        bias.summary = self._build_summary(bias)
        self._last_bias = bias
        return bias

    def _mock_calendar(self) -> list[dict]:
        today = date.today().strftime("%Y-%m-%d")
        return [
            {"time": "08:30", "event": "Initial Jobless Claims", "impact": "MEDIUM", "date": today},
            {"time": "10:00", "event": "ISM Manufacturing PMI",  "impact": "HIGH",   "date": today},
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _compute_direction(
        self, spy_chg: float, qqq_chg: float, vix: float, vix_chg: float
    ) -> tuple[str, float]:
        score = 50.0
        # SPY/QQQ signal
        avg_chg = (spy_chg + qqq_chg) / 2
        score += avg_chg * 10
        # VIX signal
        if vix > 20:
            score -= 10
        elif vix < 15:
            score += 10
        if vix_chg > 5:
            score -= 10
        elif vix_chg < -5:
            score += 10
        score = max(0, min(100, score))
        if score >= 60:
            return "BULLISH", score
        elif score <= 40:
            return "BEARISH", 100 - score
        return "NEUTRAL", score

    def _build_summary(self, b: MarketBias) -> str:
        parts = [
            f"SPY {b.spy_change_pct:+.2f}%",
            f"QQQ {b.qqq_change_pct:+.2f}%",
            f"VIX {b.vix_price:.2f} ({b.vix_change_pct:+.1f}%)",
        ]
        return f"{b.direction} ({b.strength:.0f}/100) | " + " | ".join(parts)

    @property
    def last_bias(self) -> Optional[MarketBias]:
        return self._last_bias
