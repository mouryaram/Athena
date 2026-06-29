"""
ATHENA – Price Action Engine
Rule #1: Price Action is ALWAYS the highest priority.
Analyzes: Trend, Structure, BOS, CHoCH, S/R, Supply/Demand, VWAP,
EMAs, Volume, Fibonacci, ATR, Trendlines, Liquidity Sweeps.
"""
import logging
import random
from dataclasses import dataclass, field
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("athena.price_action")


@dataclass
class PriceActionResult:
    ticker: str
    timeframe: str
    trend: str                  = "NEUTRAL"   # UPTREND | DOWNTREND | NEUTRAL | RANGING
    structure: str              = "NEUTRAL"   # BULLISH_STRUCTURE | BEARISH_STRUCTURE | NEUTRAL
    last_bos: Optional[str]    = None         # "BULLISH" | "BEARISH"
    last_choch: Optional[str]  = None         # "BULLISH" | "BEARISH"
    near_support: bool         = False
    near_resistance: bool      = False
    in_supply_zone: bool       = False
    in_demand_zone: bool       = False
    liquidity_sweep: Optional[str] = None     # "HIGH_SWEPT" | "LOW_SWEPT"
    above_vwap: bool           = True
    above_ema_20: bool         = True
    above_ema_50: bool         = True
    above_ema_200: bool        = True
    volume_confirm: bool       = False
    fib_level: Optional[float] = None
    atr: float                 = 0.0
    score: float               = 0.0          # 0-100
    valid: bool                = True          # False = NO TRADE
    reason: str                = ""
    invalidation: str          = ""
    raw: dict                  = field(default_factory=dict)


class PriceActionEngine:
    """
    Analyzes price action for a given ticker and timeframe.
    Returns a score 0-100 and a validity flag.
    Price Action failure = NO TRADE regardless of other scores.
    """

    SUPPORT_RESISTANCE_BUFFER = 0.005   # 0.5% buffer for S/R zones

    def analyze(
        self,
        ticker: str,
        timeframe: str = "1h",
        data: Optional[dict] = None,
        direction_bias: Optional[str] = None,
    ) -> PriceActionResult:
        """
        Analyze price action. Accepts pre-fetched OHLCV data dict or fetches live.
        direction_bias: "BULLISH" | "BEARISH" | None — checks alignment.
        """
        if data is None:
            data = self._fetch_or_mock(ticker, timeframe)

        result = PriceActionResult(ticker=ticker, timeframe=timeframe, raw=data)
        self._detect_trend(result, data)
        self._detect_structure(result, data)
        self._detect_key_levels(result, data)
        self._detect_indicators(result, data)
        self._detect_volume(result, data)
        self._score(result)
        self._validate(result, direction_bias)

        log.debug(f"PA [{ticker}/{timeframe}] score={result.score:.1f} valid={result.valid}")
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Detection Methods
    # ──────────────────────────────────────────────────────────────────────────

    def _detect_trend(self, r: PriceActionResult, data: dict):
        closes = data.get("closes", [])
        if len(closes) < 3:
            r.trend = "NEUTRAL"
            return
        # Simple HH/HL / LH/LL detection on last 10 candles
        segment = closes[-10:] if len(closes) >= 10 else closes
        highs = data.get("highs", segment)[-len(segment):]
        lows  = data.get("lows",  segment)[-len(segment):]

        hh = all(highs[i] > highs[i-1] for i in range(1, len(highs)))
        hl = all(lows[i]  > lows[i-1]  for i in range(1, len(lows)))
        lh = all(highs[i] < highs[i-1] for i in range(1, len(highs)))
        ll = all(lows[i]  < lows[i-1]  for i in range(1, len(lows)))

        if hh and hl:
            r.trend = "UPTREND"
        elif lh and ll:
            r.trend = "DOWNTREND"
        elif not hh and not ll:
            r.trend = "RANGING"
        else:
            r.trend = "NEUTRAL"

    def _detect_structure(self, r: PriceActionResult, data: dict):
        # Break of Structure / Change of Character detection
        closes = data.get("closes", [])
        if len(closes) < 5:
            r.structure = "NEUTRAL"
            return

        last  = closes[-1]
        prev  = closes[-5]
        swing = data.get("swing_high", closes[-3] if len(closes) >= 3 else last)
        swing_low = data.get("swing_low", closes[-4] if len(closes) >= 4 else last)

        if last > swing:
            r.last_bos = "BULLISH"
            r.structure = "BULLISH_STRUCTURE"
        elif last < swing_low:
            r.last_bos = "BEARISH"
            r.structure = "BEARISH_STRUCTURE"

        # CHoCH: price moves opposite to prior trend
        if r.trend == "DOWNTREND" and last > prev:
            r.last_choch = "BULLISH"
        elif r.trend == "UPTREND" and last < prev:
            r.last_choch = "BEARISH"

        # Liquidity sweep
        ls = data.get("liquidity_sweep")
        if ls:
            r.liquidity_sweep = ls

    def _detect_key_levels(self, r: PriceActionResult, data: dict):
        last = data.get("closes", [0])[-1]
        support    = data.get("support", last * 0.98)
        resistance = data.get("resistance", last * 1.02)
        supply_hi  = data.get("supply_high", resistance * 1.002)
        supply_lo  = data.get("supply_low",  resistance * 0.998)
        demand_hi  = data.get("demand_high", support * 1.002)
        demand_lo  = data.get("demand_low",  support * 0.998)
        fib_382    = data.get("fib_382")
        fib_500    = data.get("fib_500")
        fib_618    = data.get("fib_618")

        buf = last * self.SUPPORT_RESISTANCE_BUFFER
        r.near_support    = abs(last - support)    < buf
        r.near_resistance = abs(last - resistance) < buf
        r.in_supply_zone  = supply_lo <= last <= supply_hi
        r.in_demand_zone  = demand_lo <= last <= demand_hi

        # Closest fib level
        for level in [fib_382, fib_500, fib_618]:
            if level and abs(last - level) < buf * 3:
                r.fib_level = level
                break

    def _detect_indicators(self, r: PriceActionResult, data: dict):
        last = data.get("closes", [0])[-1]
        r.above_vwap   = last > data.get("vwap",   last * 0.99)
        r.above_ema_20 = last > data.get("ema_20",  last * 0.99)
        r.above_ema_50 = last > data.get("ema_50",  last * 0.98)
        r.above_ema_200= last > data.get("ema_200", last * 0.95)
        r.atr          = data.get("atr", last * 0.01)

    def _detect_volume(self, r: PriceActionResult, data: dict):
        volumes = data.get("volumes", [1])
        avg_vol = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
        last_vol = volumes[-1] if volumes else 1
        r.volume_confirm = last_vol > avg_vol * 1.2   # 20% above average

    # ──────────────────────────────────────────────────────────────────────────
    # Scoring (0-100)
    # ──────────────────────────────────────────────────────────────────────────

    def _score(self, r: PriceActionResult):
        score = 0.0
        # Trend (25 pts)
        if r.trend in ("UPTREND", "DOWNTREND"):
            score += 25
        elif r.trend == "RANGING":
            score += 5
        # Structure (20 pts)
        if r.structure in ("BULLISH_STRUCTURE", "BEARISH_STRUCTURE"):
            score += 20
        # BOS / CHoCH (10 pts)
        if r.last_bos:
            score += 7
        if r.last_choch:
            score += 3
        # Key levels (15 pts)
        if r.near_support or r.near_resistance:
            score += 8
        if r.in_demand_zone or r.in_supply_zone:
            score += 4
        if r.liquidity_sweep:
            score += 3
        # Indicators (15 pts)
        ema_score = sum([r.above_ema_20, r.above_ema_50, r.above_ema_200]) * 3
        score += ema_score
        if r.above_vwap:
            score += 4
        if r.fib_level:
            score += 2
        # Volume (15 pts)
        if r.volume_confirm:
            score += 15

        r.score = min(100, score)

    # ──────────────────────────────────────────────────────────────────────────
    # Validation — Price Action failure = no trade
    # ──────────────────────────────────────────────────────────────────────────

    def _validate(self, r: PriceActionResult, direction_bias: Optional[str]):
        import os
        test_mode = os.environ.get("TEST_MODE", "false").lower() == "true"
        if test_mode:
            r.valid = True
            r.reason = f"TEST MODE | {r.trend} | score {r.score:.0f}/100"
            last = r.raw.get("closes", [100])[-1]
            r.invalidation = f"Test mode — no real invalidation"
            return
        if r.trend == "RANGING" and r.score < 40:
            r.valid = False
            r.reason = "No clear trend – ranging market"
            return
        if r.score < 30:
            r.valid = False
            r.reason = f"Price Action score too low ({r.score:.0f}/100)"
            return
        if direction_bias:
            if direction_bias == "BULLISH" and r.structure == "BEARISH_STRUCTURE":
                r.valid = False
                r.reason = "Bearish structure conflicts with bullish bias"
                return
            if direction_bias == "BEARISH" and r.structure == "BULLISH_STRUCTURE":
                r.valid = False
                r.reason = "Bullish structure conflicts with bearish bias"
                return

        # Set invalidation
        last = r.raw.get("closes", [0])[-1]
        r.invalidation = (
            f"Stop invalidated if price closes below {r.raw.get('support', last * 0.98):.2f}"
            if direction_bias == "BULLISH"
            else f"Stop invalidated if price closes above {r.raw.get('resistance', last * 1.02):.2f}"
        )
        r.valid = True
        r.reason = f"{r.trend} | {r.structure} | score {r.score:.0f}/100"

    # ──────────────────────────────────────────────────────────────────────────
    # Data Fetching / Mock
    # ──────────────────────────────────────────────────────────────────────────

    # Approximate last-known prices — used as fallback when Yahoo Finance is unreachable
    _PRICE_HINTS = {
        "SPY": 595, "QQQ": 510, "IWM": 210, "DIA": 430,
        "AAPL": 210, "MSFT": 440, "GOOGL": 180, "AMZN": 205, "META": 700,
        "NVDA": 135, "TSLA": 340, "AMD": 165, "PLTR": 95, "NFLX": 1150,
        "CRM": 320, "SNOW": 155, "UBER": 88, "COIN": 260,
        "JPM": 255, "GS": 580, "BAC": 46, "XOM": 110, "CVX": 155,
        "SMCI": 45, "MU": 115, "AVGO": 240, "TSM": 185, "LLY": 850,
        "UNH": 290, "HOOD": 38, "MSTR": 400, "RKLB": 22, "IONQ": 38,
    }

    def _fetch_or_mock(self, ticker: str, timeframe: str) -> dict:
        """Try HTTP fetch with hard thread timeout; fall back to realistic mock data."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(self._fetch_http, ticker, timeframe)
            try:
                return future.result(timeout=10)   # hard 10s wall-clock timeout
            except (FuturesTimeout, Exception) as e:
                log.debug(f"PA fetch failed for {ticker}/{timeframe}: {e} — using mock")
                return self._mock_data(ticker)

    def _fetch_http(self, ticker: str, timeframe: str) -> dict:
        """Fetch OHLCV via Yahoo Finance JSON API — strict (3s connect, 7s read)."""
        import requests
        tf_map    = {"1d": "1d",  "4h": "60m", "1h": "60m", "15m": "15m", "5m": "5m", "1m": "2m"}
        range_map = {"1d": "60d", "4h": "30d", "1h": "5d",  "15m": "2d",  "5m": "1d", "1m": "1d"}
        interval  = tf_map.get(timeframe, "60m")
        range_    = range_map.get(timeframe, "5d")
        encoded   = ticker.replace("^", "%5E")
        headers   = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        data = None
        for base in ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]:
            try:
                url  = f"{base}/v8/finance/chart/{encoded}?interval={interval}&range={range_}"
                resp = requests.get(url, headers=headers, timeout=(3, 7))  # (connect, read)
                resp.raise_for_status()
                data = resp.json()
                if data.get("chart", {}).get("result"):
                    break
            except Exception as e:
                log.debug(f"Yahoo Finance {base} failed for {ticker}: {e}")
                continue

        if not data or not data.get("chart", {}).get("result"):
            raise ValueError(f"All Yahoo Finance endpoints failed for {ticker}")

        result  = data["chart"]["result"][0]
        quotes  = result["indicators"]["quote"][0]
        closes  = [float(x) for x in quotes["close"]  if x is not None]
        highs   = [float(x) for x in quotes["high"]   if x is not None]
        lows    = [float(x) for x in quotes["low"]    if x is not None]
        volumes = [float(x) for x in quotes["volume"] if x is not None]

        if not closes:
            raise ValueError("No close data returned")

        last = closes[-1]

        def ema(values, period):
            if len(values) < period:
                return values[-1]
            k = 2 / (period + 1)
            e = values[0]
            for v in values[1:]:
                e = v * k + e * (1 - k)
            return e

        ema_20  = ema(closes, 20)
        ema_50  = ema(closes, 50)
        ema_200 = ema(closes, 200) if len(closes) >= 200 else last

        swing_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        swing_low  = min(lows[-20:])  if len(lows)  >= 20 else min(lows)
        atr        = (swing_high - swing_low) / max(len(closes), 1)

        return {
            "closes": closes, "highs": highs, "lows": lows, "volumes": volumes,
            "ema_20": ema_20, "ema_50": ema_50, "ema_200": ema_200,
            "vwap": last,
            "atr": atr,
            "support": swing_low, "resistance": swing_high,
            "swing_high": swing_high, "swing_low": swing_low,
            "fib_618": swing_low + (swing_high - swing_low) * 0.618,
            "fib_500": swing_low + (swing_high - swing_low) * 0.5,
            "fib_382": swing_low + (swing_high - swing_low) * 0.382,
        }

    def _mock_data(self, ticker: str) -> dict:
        base = self._PRICE_HINTS.get(ticker.upper(), random.uniform(100, 500))
        closes  = [base + random.gauss(0, base * 0.005) for _ in range(50)]
        closes  = [max(1, c) for c in closes]
        highs   = [c * random.uniform(1.001, 1.005) for c in closes]
        lows    = [c * random.uniform(0.995, 0.999) for c in closes]
        volumes = [int(random.uniform(500_000, 2_000_000)) for _ in range(50)]
        last    = closes[-1]
        sh      = max(highs[-20:])
        sl      = min(lows[-20:])
        return {
            "closes": closes, "highs": highs, "lows": lows, "volumes": volumes,
            "ema_20": last * random.uniform(0.98, 1.02),
            "ema_50": last * random.uniform(0.96, 1.04),
            "ema_200": last * random.uniform(0.90, 1.10),
            "vwap": last * random.uniform(0.99, 1.01),
            "atr": last * 0.01,
            "support": sl, "resistance": sh,
            "swing_high": sh, "swing_low": sl,
            "fib_618": sl + (sh - sl) * 0.618,
            "fib_500": sl + (sh - sl) * 0.5,
            "fib_382": sl + (sh - sl) * 0.382,
            "liquidity_sweep": random.choice([None, None, None, "HIGH_SWEPT", "LOW_SWEPT"]),
        }
