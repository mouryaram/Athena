"""
ATHENA – Daily Workflow Orchestrator
Runs all phases of the daily trading workflow in sequence.
Each phase maps to a time slot in the trading day.
"""
import logging
from datetime import datetime, date, timedelta
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config
from engines.market_engine     import MarketEngine,     MarketBias
from engines.price_action_engine import PriceActionEngine
from engines.multi_timeframe_engine import MultiTimeframeEngine
from engines.quant_engine      import QuantEngine
from engines.spx_engine        import SPXEngine
from engines.discord_engine    import DiscordEngine
from engines.confidence_engine import ConfidenceEngine
from engines.evidence_engine   import EvidenceEngine
from alerts.telegram           import TelegramAlert
from database.db               import SessionLocal
from database.models           import (
    Watchlist, TradeIdea, ActiveTrade, TradeJournal, DailyStatistic,
    MarketSnapshot, QuantSnapshot, DiscordWatchlist,
    Direction, TradeStatus, Outcome, Recommendation,
)

log = logging.getLogger("athena.workflow")


class ATHENAWorkflow:
    """
    Master workflow controller. Instantiate once; call the phase methods on schedule.
    All state is stored in the database between phases.
    """

    # Tickers to scan each day (augmented from Discord and config)
    DEFAULT_WATCHLIST = [
        "SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "META", "AMZN", "GOOGL",
        "AMD", "NFLX", "CRM", "PLTR",
    ]

    def __init__(self):
        self.market    = MarketEngine()
        self.pa        = PriceActionEngine()
        self.mtf       = MultiTimeframeEngine()
        self.quant     = QuantEngine()
        self.spx       = SPXEngine()
        self.discord   = DiscordEngine()
        self.confidence= ConfidenceEngine()
        self.evidence  = EvidenceEngine()
        self.telegram  = TelegramAlert()

        self._market_bias: Optional[MarketBias] = None
        self._scan_tickers: list[str] = list(self.DEFAULT_WATCHLIST)
        log.info("ATHENA workflow initialized")

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 1 – 06:00  Premarket Bias
    # ══════════════════════════════════════════════════════════════════════════

    def phase_premarket_bias(self):
        """06:00 – Collect market data, build market bias, check calendar."""
        log.info("=== PHASE 1: Premarket Bias (06:00) ===")
        db = SessionLocal()
        try:
            bias = self.market.get_bias()
            self._market_bias = bias
            calendar = self.market.get_economic_calendar()

            # Store snapshot
            snap = MarketSnapshot(
                spy_price=bias.spy_price, spy_change_pct=bias.spy_change_pct,
                qqq_price=bias.qqq_price, qqq_change_pct=bias.qqq_change_pct,
                vix_price=bias.vix_price, vix_change_pct=bias.vix_change_pct,
                spx_price=bias.spx_price, futures_es=bias.futures_es,
                futures_nq=bias.futures_nq,
                market_bias=Direction[bias.direction],
                bias_strength=bias.strength,
                sector_data=bias.sector_data,
                notes=f"Calendar: {[e['event'] for e in calendar]}",
            )
            db.add(snap)
            db.commit()

            log.info(f"Market bias: {bias.summary}")
            # High-impact events warning
            high_impact = [e for e in calendar if e.get("impact") == "HIGH"]
            if high_impact:
                log.warning(f"HIGH-IMPACT events today: {[e['event'] for e in high_impact]}")

        finally:
            db.close()

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 2 – 07:00  Quant Download
    # ══════════════════════════════════════════════════════════════════════════

    def phase_quant_download(self):
        """07:00 – Download options flow, dark pool data, OI."""
        log.info("=== PHASE 2: Quant Download (07:00) ===")
        db = SessionLocal()
        try:
            bias_dir = self._market_bias.direction if self._market_bias else "NEUTRAL"
            for ticker in self._scan_tickers:
                try:
                    q = self.quant.analyze(ticker, direction_bias=bias_dir)
                    snap = QuantSnapshot(
                        ticker=ticker,
                        call_flow=q.call_flow, put_flow=q.put_flow,
                        flow_bias=Direction[q.flow_bias] if q.flow_bias != "NEUTRAL" else Direction.NEUTRAL,
                        dark_pool_prints=q.dark_pool_prints,
                        gamma_exposure=q.gamma_exposure, delta_exposure=q.delta_exposure,
                        open_interest_c=q.open_interest_calls,
                        open_interest_p=q.open_interest_puts,
                        put_call_ratio=q.put_call_ratio,
                        sweeps_bullish=q.sweeps_bullish, sweeps_bearish=q.sweeps_bearish,
                        block_trades=q.block_trades,
                        confirmation_score=q.confirmation_score,
                    )
                    db.add(snap)
                except Exception as e:
                    log.warning(f"Quant download failed for {ticker}: {e}")
            db.commit()
            log.info(f"Quant data stored for {len(self._scan_tickers)} tickers")
        finally:
            db.close()

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 3 – 08:00  Discord Read
    # ══════════════════════════════════════════════════════════════════════════

    def phase_discord_read(self):
        """08:00 – Parse Discord watchlists, validate against ATHENA rules."""
        log.info("=== PHASE 3: Discord Read (08:00) ===")
        db = SessionLocal()
        try:
            ideas = self.discord.parse_file()
            if self._market_bias:
                ideas = self.discord.validate(ideas, self.pa, self._market_bias)

            for idea in ideas:
                # Add to scan list if ATHENA agrees
                if idea.ticker not in self._scan_tickers:
                    self._scan_tickers.append(idea.ticker)

                # Store in DB
                row = DiscordWatchlist(
                    ticker=idea.ticker,
                    direction=Direction[idea.direction] if idea.direction in ("BULLISH","BEARISH") else Direction.NEUTRAL,
                    trigger=idea.trigger, stop=idea.stop, target=idea.target,
                    notes=idea.notes, source_text=idea.raw_text,
                    validated=idea.validated,
                    validation_score=idea.validation_score,
                    athena_agrees=idea.athena_agrees,
                    reason=idea.reason,
                )
                db.add(row)

            db.commit()
            agreed = sum(1 for i in ideas if i.athena_agrees)
            log.info(f"Discord: {len(ideas)} ideas parsed, {agreed} validated by ATHENA")
        finally:
            db.close()

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 4 – 08:15  Premarket Scanner
    # ══════════════════════════════════════════════════════════════════════════

    def phase_premarket_scan(self) -> list[dict]:
        """08:15 – Score all tickers, rank by composite score."""
        log.info("=== PHASE 4: Premarket Scanner (08:15) ===")
        results = []
        bias = self._market_bias

        for ticker in self._scan_tickers:
            try:
                direction = bias.direction if bias else "NEUTRAL"
                pa    = self.pa.analyze(ticker, "1h", direction_bias=direction)
                if not pa.valid:
                    continue
                mtf   = self.mtf.analyze(ticker, direction)
                quant = self.quant.analyze(ticker, direction)
                ev_adj = 0.0   # no DB in premarket scan (uses in-memory)

                score = (
                    pa.score   * 0.50 +
                    mtf.alignment_score * 0.20 +
                    (50 if direction == bias.direction else 30) * 0.10 +
                    quant.confirmation_score * 0.10 +
                    ev_adj     * 0.10
                )
                results.append({
                    "ticker":     ticker,
                    "direction":  direction,
                    "pa_score":   pa.score,
                    "mtf_score":  mtf.alignment_score,
                    "quant_score":quant.confirmation_score,
                    "total_score":round(score, 1),
                    "reason":     pa.reason,
                })
            except Exception as e:
                log.warning(f"Scanner error for {ticker}: {e}")

        results.sort(key=lambda x: x["total_score"], reverse=True)
        log.info(f"Scanner ranked {len(results)} tickers. Top: {[r['ticker'] for r in results[:5]]}")
        return results

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 5 – 09:00  Build Watchlist
    # ══════════════════════════════════════════════════════════════════════════

    def phase_build_watchlist(self, scan_results: Optional[list] = None) -> list[Watchlist]:
        """09:00 – Build final watchlist from top scanner results."""
        log.info("=== PHASE 5: Build Watchlist (09:00) ===")
        db = SessionLocal()
        watchlist_rows = []
        try:
            if not scan_results:
                scan_results = self.phase_premarket_scan()

            top = scan_results[:10]   # Top 10 only
            bias = self._market_bias
            direction = bias.direction if bias else "NEUTRAL"

            for item in top:
                ticker = item["ticker"]
                try:
                    pa    = self.pa.analyze(ticker, "1h", direction_bias=direction)
                    mtf   = self.mtf.analyze(ticker, direction)
                    quant = self.quant.analyze(ticker, direction)
                    spx   = None
                    if ticker in ("SPY", "SPX", "QQQ") and bias:
                        spx = self.spx.analyze(
                            direction, bias.vix_price, bias.vix_change_pct,
                            bias.breadth_adv_dec
                        )
                    conf = self.confidence.evaluate(
                        ticker, direction, pa, mtf, bias or type("B",(),{"direction":"NEUTRAL","strength":50,"vix_price":18,"vix_change_pct":0,"breadth_adv_dec":1,"summary":"","sector_data":{}})(),
                        quant, 0.0, spx
                    )

                    row = Watchlist(
                        ticker=ticker,
                        direction=Direction[direction] if direction in ("BULLISH","BEARISH") else Direction.NEUTRAL,
                        entry_price=conf.entry, stop_price=conf.stop,
                        target1=conf.target1, target2=conf.target2,
                        confidence=conf.confidence,
                        reason=conf.reason, invalidation=conf.invalidation,
                        pa_score=conf.pa_score, mtf_score=conf.mtf_score,
                        ctx_score=conf.ctx_score, quant_score=conf.quant_score,
                        ev_score=conf.ev_score, active=True,
                    )
                    db.add(row)
                    watchlist_rows.append(row)
                except Exception as e:
                    log.warning(f"Watchlist build error for {ticker}: {e}")

            db.commit()
            log.info(f"Watchlist built: {len(watchlist_rows)} items")
        finally:
            db.close()

        return watchlist_rows

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 6 – 09:30  Live Evaluation Loop
    # ══════════════════════════════════════════════════════════════════════════

    def run_live_cycle(self) -> list[dict]:
        """
        09:30+ – One cycle of live evaluation.
        Call this every 1-5 minutes during market hours.
        Returns list of alerts fired.
        """
        alerts_fired = []
        db = SessionLocal()
        try:
            # Refresh market bias
            bias = self.market.get_bias()
            self._market_bias = bias

            # Evaluate each watchlist item
            watchlist = db.query(Watchlist).filter(Watchlist.active == True).all()
            for item in watchlist:
                try:
                    direction = item.direction.value if item.direction else bias.direction
                    pa    = self.pa.analyze(item.ticker, "5m", direction_bias=direction)
                    mtf   = self.mtf.analyze(item.ticker, direction)
                    quant = self.quant.analyze(item.ticker, direction)
                    spx   = None
                    if item.ticker in ("SPY", "SPX", "QQQ"):
                        spx = self.spx.analyze(direction, bias.vix_price, bias.vix_change_pct)
                    conf = self.confidence.evaluate(item.ticker, direction, pa, mtf, bias, quant, 0.0, spx)

                    # Update confidence on watchlist item
                    item.confidence = conf.confidence
                    db.add(item)

                    # Fire alert if threshold crossed
                    if conf.trade_allowed:
                        idea = self._create_trade_idea(db, item, conf, pa, quant)
                        self.telegram.send_alert(conf, idea)
                        alerts_fired.append({"ticker": item.ticker, "confidence": conf.confidence, "direction": direction})
                        log.info(f"ALERT fired: {item.ticker} {direction} @ {conf.confidence:.0f}")

                except Exception as e:
                    log.warning(f"Live cycle error for {item.ticker}: {e}")

            # Monitor active trades
            self._monitor_active_trades(db, bias)
            db.commit()

        finally:
            db.close()

        return alerts_fired

    # ══════════════════════════════════════════════════════════════════════════
    # PHASE 7 – End of Day
    # ══════════════════════════════════════════════════════════════════════════

    def phase_end_of_day(self):
        """17:00 – Store statistics, update evidence, mark watchlist inactive."""
        log.info("=== PHASE 7: End of Day ===")
        db = SessionLocal()
        try:
            today = date.today()
            journals = [j for j in db.query(TradeJournal).all()
                        if j.entered_at and j.entered_at.date() == today]

            wins   = sum(1 for j in journals if j.outcome and j.outcome.value == "WIN")
            losses = sum(1 for j in journals if j.outcome and j.outcome.value == "LOSS")
            total  = len(journals)
            total_r= sum(j.pnl_r or 0 for j in journals)

            stat = DailyStatistic(
                date=datetime.combine(today, datetime.min.time()),
                trades_taken=total,
                alerts_sent=db.query(TradeIdea).filter(TradeIdea.alerted==True).count(),
                wins=wins, losses=losses,
                win_rate=wins/max(total,1),
                total_r=round(total_r,2),
                avg_r=round(total_r/max(total,1),2),
                market_bias=Direction[self._market_bias.direction] if self._market_bias else Direction.NEUTRAL,
                vix_open=self._market_bias.vix_price if self._market_bias else 0,
            )
            db.add(stat)

            # Update evidence for each closed trade
            for j in journals:
                if j.outcome:
                    self.evidence.record_outcome(
                        db=db,
                        ticker=j.ticker,
                        setup_type=j.setup_type or "UNKNOWN",
                        outcome=j.outcome.value,
                        pnl_r=j.pnl_r or 0,
                        weekday=j.weekday or today.strftime("%A"),
                        hour=j.hour_of_day or 10,
                    )

            # Deactivate today's watchlist
            for w in db.query(Watchlist).filter(Watchlist.active==True).all():
                w.active = False

            db.commit()
            log.info(f"EOD: {total} trades | {wins}W/{losses}L | {total_r:.2f}R")

        finally:
            db.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Trade Management
    # ──────────────────────────────────────────────────────────────────────────

    def _monitor_active_trades(self, db, bias: MarketBias):
        """Evaluate all open trades and issue recommendations."""
        active = db.query(ActiveTrade).filter(ActiveTrade.status == TradeStatus.ACTIVE).all()
        for trade in active:
            try:
                direction = trade.direction.value if trade.direction else "NEUTRAL"
                pa    = self.pa.analyze(trade.ticker, "5m", direction_bias=direction)
                quant = self.quant.analyze(trade.ticker, direction)
                rec, reason = self._decide_trade_action(trade, pa, quant, bias)
                trade.recommendation = rec
                trade.recommendation_reason = reason
                trade.last_updated = datetime.utcnow()
                db.add(trade)
            except Exception as e:
                log.warning(f"Trade monitor error for {trade.ticker}: {e}")

    def _decide_trade_action(self, trade: ActiveTrade, pa, quant, bias) -> tuple:
        """Return (Recommendation, reason) for an open trade."""
        if not trade.entry_price or not trade.current_price:
            return Recommendation.NO_ACTION, "Awaiting price data"

        current = trade.current_price
        entry   = trade.entry_price
        stop    = trade.stop_price
        t1      = trade.target1
        direction = trade.direction.value if trade.direction else "NEUTRAL"

        pnl_pct = (current - entry) / entry * 100 * (1 if direction == "BULLISH" else -1)

        # Hit stop
        if stop and ((direction == "BULLISH" and current < stop) or
                     (direction == "BEARISH" and current > stop)):
            return Recommendation.EXIT, f"Stop hit at {current:.2f}"

        # Hit target 1
        if t1 and ((direction == "BULLISH" and current >= t1) or
                   (direction == "BEARISH" and current <= t1)):
            if not trade.partial_taken:
                return Recommendation.TAKE_PARTIAL, f"Target 1 reached ({current:.2f})"
            return Recommendation.MOVE_STOP, "Partial taken, move stop to breakeven"

        # Structure break
        if (direction == "BULLISH" and pa.structure == "BEARISH_STRUCTURE") or \
           (direction == "BEARISH" and pa.structure == "BULLISH_STRUCTURE"):
            return Recommendation.EXIT, f"Structure broke against position"

        # VIX spike against bullish trade
        if direction == "BULLISH" and bias.vix_change_pct > 10:
            return Recommendation.TIGHTEN_STOP, "VIX spiking – tighten stop"

        return Recommendation.HOLD, f"Trend intact | P&L {pnl_pct:.1f}%"

    def _create_trade_idea(self, db, item: Watchlist, conf, pa, quant) -> TradeIdea:
        """Create and persist a TradeIdea when alert is fired."""
        direction = item.direction.value if item.direction else "NEUTRAL"
        idea = TradeIdea(
            ticker=item.ticker,
            direction=Direction[direction] if direction in ("BULLISH","BEARISH") else Direction.NEUTRAL,
            entry=conf.entry, stop=conf.stop,
            target1=conf.target1, target2=conf.target2,
            confidence=conf.confidence,
            pa_summary=conf.pa_summary,
            ctx_summary=conf.ctx_summary,
            quant_summary=conf.quant_summary,
            invalidation=conf.invalidation,
            alerted=True, alert_sent_at=datetime.utcnow(),
            status=TradeStatus.TRIGGERED,
        )
        db.add(idea)
        db.flush()
        return idea
