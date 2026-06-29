"""
ATHENA AI Trading Assistant – Main Entry Point
FastAPI server + APScheduler workflow.
Run: uvicorn main:app --reload --port 8000
"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(__file__))
import config
from database.db import get_db, init_db, SessionLocal
from database.models import (
    Watchlist, TradeIdea, ActiveTrade, TradeJournal,
    DailyStatistic, MarketSnapshot, QuantSnapshot,
    DiscordWatchlist, EvidenceRule,
    Direction, TradeStatus, Outcome, Recommendation,
)
from workflow.athena_workflow import ATHENAWorkflow
from workflow.scheduler        import create_scheduler
from engines.evidence_engine   import EvidenceEngine

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s | %(name)-22s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_FILE),
    ],
)
log = logging.getLogger("athena.main")

# ─── Global state ────────────────────────────────────────────────────────────
workflow  = ATHENAWorkflow()
scheduler = None
evidence  = EvidenceEngine()


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    log.info("ATHENA starting up...")
    init_db()
    scheduler = create_scheduler(workflow)
    scheduler.start()
    log.info("Scheduler started. ATHENA is live.")
    yield
    scheduler.shutdown()
    log.info("ATHENA shutdown complete.")


# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ATHENA AI Trading Assistant",
    description="Evidence-based AI trading assistant. Capital preservation first.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Serve dashboard
DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


# ═════════════════════════════════════════════════════════════════════════════
# REST API Routes
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    dashboard = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.exists(dashboard):
        return FileResponse(dashboard)
    return {"status": "ATHENA running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─── Market ──────────────────────────────────────────────────────────────────

@app.get("/api/market/bias")
def get_market_bias():
    """Current market bias."""
    bias = workflow.market.get_bias()
    return {
        "direction":       bias.direction,
        "strength":        bias.strength,
        "spy_price":       bias.spy_price,
        "spy_change_pct":  bias.spy_change_pct,
        "qqq_price":       bias.qqq_price,
        "qqq_change_pct":  bias.qqq_change_pct,
        "vix_price":       bias.vix_price,
        "vix_change_pct":  bias.vix_change_pct,
        "spx_price":       bias.spx_price,
        "futures_es":      bias.futures_es,
        "futures_nq":      bias.futures_nq,
        "breadth":         bias.breadth_adv_dec,
        "sector_data":     bias.sector_data,
        "summary":         bias.summary,
        "timestamp":       bias.timestamp.isoformat(),
    }


@app.get("/api/market/snapshots")
def get_market_snapshots(limit: int = 20, db: Session = Depends(get_db)):
    snaps = db.query(MarketSnapshot).order_by(MarketSnapshot.timestamp.desc()).limit(limit).all()
    return [{"timestamp": s.timestamp, "bias": s.market_bias.value if s.market_bias else None,
             "spy": s.spy_price, "vix": s.vix_price, "strength": s.bias_strength} for s in snaps]


# ─── Watchlist ───────────────────────────────────────────────────────────────

@app.get("/api/watchlist")
def get_watchlist(active_only: bool = True, db: Session = Depends(get_db)):
    q = db.query(Watchlist)
    if active_only:
        q = q.filter(Watchlist.active == True)
    items = q.order_by(Watchlist.confidence.desc()).all()
    return [{
        "id": w.id, "ticker": w.ticker,
        "direction": w.direction.value if w.direction else None,
        "entry": w.entry_price, "stop": w.stop_price,
        "target1": w.target1, "target2": w.target2,
        "confidence": w.confidence, "reason": w.reason,
        "pa_score": w.pa_score, "mtf_score": w.mtf_score,
        "quant_score": w.quant_score,
        "invalidation": w.invalidation,
        "created_at": w.created_at.isoformat() if w.created_at else None,
    } for w in items]


_rebuild_status = {"running": False, "last": "never", "items": 0}

def _do_rebuild():
    global _rebuild_status
    _rebuild_status["running"] = True
    try:
        workflow.phase_premarket_bias()
        items = workflow.phase_build_watchlist()
        _rebuild_status["items"] = len(items)
        _rebuild_status["last"] = datetime.utcnow().strftime("%H:%M:%S UTC")
        log.info(f"Rebuild complete: {len(items)} items")
    except Exception as e:
        log.error(f"Rebuild error: {e}")
        _rebuild_status["last"] = f"error: {e}"
    finally:
        _rebuild_status["running"] = False

@app.post("/api/watchlist/rebuild")
def rebuild_watchlist(background_tasks: BackgroundTasks):
    """Trigger watchlist rebuild in background — returns immediately."""
    if _rebuild_status["running"]:
        return {"status": "already_running", "message": "Rebuild already in progress…"}
    background_tasks.add_task(_do_rebuild)
    return {"status": "started", "message": "Rebuild started — watchlist will update in ~60 seconds"}

@app.get("/api/watchlist/rebuild/status")
def rebuild_status():
    return _rebuild_status


# ─── Trade Ideas ─────────────────────────────────────────────────────────────

@app.get("/api/ideas")
def get_trade_ideas(limit: int = 50, db: Session = Depends(get_db)):
    ideas = db.query(TradeIdea).order_by(TradeIdea.date.desc()).limit(limit).all()
    return [{
        "id": i.id, "ticker": i.ticker,
        "direction": i.direction.value if i.direction else None,
        "entry": i.entry, "stop": i.stop,
        "target1": i.target1, "target2": i.target2,
        "confidence": i.confidence,
        "status": i.status.value if i.status else None,
        "alerted": i.alerted,
        "pa_summary": i.pa_summary,
        "quant_summary": i.quant_summary,
        "invalidation": i.invalidation,
        "date": i.date.isoformat() if i.date else None,
    } for i in ideas]


# ─── Active Trades ───────────────────────────────────────────────────────────

@app.get("/api/trades/active")
def get_active_trades(db: Session = Depends(get_db)):
    trades = db.query(ActiveTrade).filter(ActiveTrade.status == TradeStatus.ACTIVE).all()
    return [{
        "id": t.id, "ticker": t.ticker,
        "direction": t.direction.value if t.direction else None,
        "entry": t.entry_price, "current": t.current_price,
        "stop": t.stop_price, "target1": t.target1,
        "unrealized_pnl": t.unrealized_pnl,
        "recommendation": t.recommendation.value if t.recommendation else None,
        "recommendation_reason": t.recommendation_reason,
        "entered_at": t.entered_at.isoformat() if t.entered_at else None,
    } for t in trades]


class OpenTradeRequest(BaseModel):
    ticker: str
    direction: str
    entry_price: float
    stop_price: float
    target1: float
    target2: Optional[float] = None
    size: float = 1.0
    idea_id: Optional[int] = None

@app.post("/api/trades/open")
def open_trade(req: OpenTradeRequest, db: Session = Depends(get_db)):
    """Manually open a trade."""
    trade = ActiveTrade(
        ticker=req.ticker,
        direction=Direction[req.direction] if req.direction in ("BULLISH","BEARISH") else Direction.NEUTRAL,
        entry_price=req.entry_price, current_price=req.entry_price,
        stop_price=req.stop_price, target1=req.target1, target2=req.target2,
        size=req.size, entered_at=datetime.utcnow(),
        status=TradeStatus.ACTIVE,
        idea_id=req.idea_id,
    )
    db.add(trade); db.commit(); db.refresh(trade)
    return {"id": trade.id, "message": f"Trade opened: {req.ticker} {req.direction}"}


class CloseTradeRequest(BaseModel):
    exit_price: float
    outcome: str    # WIN | LOSS | BREAKEVEN
    notes: Optional[str] = None
    lesson: Optional[str] = None

@app.post("/api/trades/{trade_id}/close")
def close_trade(trade_id: int, req: CloseTradeRequest, db: Session = Depends(get_db)):
    """Close an active trade and journal it."""
    trade = db.query(ActiveTrade).filter_by(id=trade_id).first()
    if not trade:
        raise HTTPException(404, "Trade not found")

    direction = trade.direction.value if trade.direction else "NEUTRAL"
    entry  = trade.entry_price or req.exit_price
    pnl    = (req.exit_price - entry) * (1 if direction == "BULLISH" else -1)
    risk   = abs(entry - (trade.stop_price or entry)) or 1
    pnl_r  = round(pnl / risk, 2)

    now = datetime.utcnow()
    duration = int((now - trade.entered_at).total_seconds() / 60) if trade.entered_at else 0

    journal = TradeJournal(
        active_trade_id=trade.id,
        ticker=trade.ticker,
        direction=trade.direction,
        entry_price=entry, exit_price=req.exit_price,
        stop_price=trade.stop_price,
        target1=trade.target1, target2=trade.target2,
        size=trade.size,
        pnl=round(pnl, 2), pnl_r=pnl_r,
        outcome=Outcome[req.outcome],
        entered_at=trade.entered_at, exited_at=now,
        duration_mins=duration,
        weekday=now.strftime("%A"),
        hour_of_day=now.hour,
        notes=req.notes, lesson=req.lesson,
    )
    db.add(journal)
    trade.status = TradeStatus.CLOSED
    db.commit()

    return {"message": f"Trade closed: {req.outcome} | {pnl_r:.2f}R", "pnl_r": pnl_r}


# ─── Journal ─────────────────────────────────────────────────────────────────

@app.get("/api/journal")
def get_journal(limit: int = 100, db: Session = Depends(get_db)):
    entries = db.query(TradeJournal).order_by(TradeJournal.exited_at.desc()).limit(limit).all()
    return [{
        "id": j.id, "ticker": j.ticker,
        "direction": j.direction.value if j.direction else None,
        "entry": j.entry_price, "exit": j.exit_price,
        "pnl": j.pnl, "pnl_r": j.pnl_r,
        "outcome": j.outcome.value if j.outcome else None,
        "duration_mins": j.duration_mins,
        "weekday": j.weekday, "hour": j.hour_of_day,
        "notes": j.notes, "lesson": j.lesson,
        "exited_at": j.exited_at.isoformat() if j.exited_at else None,
    } for j in entries]


# ─── Evidence / Stats ────────────────────────────────────────────────────────

@app.get("/api/evidence")
def get_evidence(db: Session = Depends(get_db)):
    return evidence.get_statistics(db)

@app.get("/api/evidence/rules")
def get_evidence_rules(db: Session = Depends(get_db)):
    rules = db.query(EvidenceRule).order_by(EvidenceRule.sample_size.desc()).all()
    return [{
        "type": r.rule_type, "value": r.rule_value,
        "samples": r.sample_size, "win_rate": round(r.win_rate*100,1),
        "avg_r": r.avg_r, "adj": r.confidence_adj,
    } for r in rules]

@app.get("/api/stats/daily")
def get_daily_stats(days: int = 30, db: Session = Depends(get_db)):
    stats = db.query(DailyStatistic).order_by(DailyStatistic.date.desc()).limit(days).all()
    return [{
        "date": s.date.strftime("%Y-%m-%d") if s.date else None,
        "trades": s.trades_taken, "wins": s.wins, "losses": s.losses,
        "win_rate": round(s.win_rate*100,1), "total_r": s.total_r,
        "market_bias": s.market_bias.value if s.market_bias else None,
    } for s in stats]


# ─── Quant ───────────────────────────────────────────────────────────────────

@app.get("/api/quant/{ticker}")
def get_quant(ticker: str, db: Session = Depends(get_db)):
    """Get latest quant snapshot for a ticker."""
    snap = db.query(QuantSnapshot).filter_by(ticker=ticker.upper())\
             .order_by(QuantSnapshot.timestamp.desc()).first()
    if snap:
        return {
            "ticker": snap.ticker,
            "call_flow": snap.call_flow, "put_flow": snap.put_flow,
            "flow_bias": snap.flow_bias.value if snap.flow_bias else None,
            "dark_pool": snap.dark_pool_prints,
            "sweeps_b": snap.sweeps_bullish, "sweeps_br": snap.sweeps_bearish,
            "pcr": snap.put_call_ratio,
            "confirmation_score": snap.confirmation_score,
            "timestamp": snap.timestamp.isoformat(),
        }
    # Fetch fresh
    bias = workflow.market.last_bias
    direction = bias.direction if bias else "NEUTRAL"
    q = workflow.quant.analyze(ticker.upper(), direction)
    return {
        "ticker": ticker.upper(),
        "call_flow": q.call_flow, "put_flow": q.put_flow,
        "flow_bias": q.flow_bias,
        "dark_pool": q.dark_pool_prints,
        "sweeps_b": q.sweeps_bullish, "sweeps_br": q.sweeps_bearish,
        "pcr": q.put_call_ratio,
        "confirmation_score": q.confirmation_score,
        "summary": q.summary,
    }


# ─── Discord ─────────────────────────────────────────────────────────────────

class DiscordPasteRequest(BaseModel):
    text: str

@app.post("/api/discord/parse")
def parse_discord(req: DiscordPasteRequest, db: Session = Depends(get_db)):
    """Parse a pasted Discord watchlist."""
    ideas = workflow.discord.parse_watchlist(req.text)
    bias  = workflow.market.last_bias
    if bias:
        ideas = workflow.discord.validate(ideas, workflow.pa, bias)
    return [{
        "ticker": i.ticker, "direction": i.direction,
        "trigger": i.trigger, "stop": i.stop, "target": i.target,
        "validated": i.validated, "athena_agrees": i.athena_agrees,
        "validation_score": i.validation_score, "reason": i.reason,
    } for i in ideas]

@app.get("/api/discord/watchlists")
def get_discord_watchlists(limit: int = 50, db: Session = Depends(get_db)):
    items = db.query(DiscordWatchlist).order_by(DiscordWatchlist.created_at.desc()).limit(limit).all()
    return [{
        "ticker": d.ticker, "direction": d.direction.value if d.direction else None,
        "trigger": d.trigger, "stop": d.stop, "target": d.target,
        "validated": d.validated, "athena_agrees": d.athena_agrees,
        "validation_score": d.validation_score, "reason": d.reason,
        "date": d.created_at.isoformat() if d.created_at else None,
    } for d in items]


# ─── Manual Triggers ─────────────────────────────────────────────────────────

@app.post("/api/run/premarket")
def run_premarket(background_tasks: BackgroundTasks):
    background_tasks.add_task(workflow.phase_premarket_bias)
    background_tasks.add_task(workflow.phase_quant_download)
    background_tasks.add_task(workflow.phase_discord_read)
    return {"status": "started", "message": "Premarket workflow triggered"}

@app.post("/api/run/scan")
def run_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(workflow.phase_premarket_scan)
    return {"status": "started", "message": "Scanner triggered"}

@app.post("/api/run/live-cycle")
def run_live_cycle():
    """Run live cycle synchronously and return alerts fired."""
    try:
        alerts = workflow.run_live_cycle()
        return {"status": "done", "alerts_fired": len(alerts), "alerts": alerts}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/run/eod")
def run_eod(background_tasks: BackgroundTasks):
    background_tasks.add_task(workflow.phase_end_of_day)
    return {"status": "started", "message": "EOD workflow triggered"}

@app.get("/api/analyze/{ticker}")
def analyze_ticker(ticker: str, direction: str = "BULLISH"):
    """On-demand full analysis for any ticker."""
    bias  = workflow.market.get_bias()
    pa    = workflow.pa.analyze(ticker.upper(), "1h", direction_bias=direction)
    mtf   = workflow.mtf.analyze(ticker.upper(), direction)
    quant = workflow.quant.analyze(ticker.upper(), direction)
    spx   = None
    if ticker.upper() in ("SPY", "SPX", "QQQ"):
        spx = workflow.spx.analyze(direction, bias.vix_price, bias.vix_change_pct)
    conf  = workflow.confidence.evaluate(ticker.upper(), direction, pa, mtf, bias, quant, 0.0, spx)
    return {
        "ticker":     ticker.upper(),
        "direction":  direction,
        "confidence": conf.confidence,
        "trade_allowed": conf.trade_allowed,
        "reason":     conf.reason,
        "entry":      conf.entry,
        "stop":       conf.stop,
        "target1":    conf.target1,
        "risk_reward":conf.risk_reward,
        "pa_score":   conf.pa_score,
        "mtf_score":  conf.mtf_score,
        "ctx_score":  conf.ctx_score,
        "quant_score":conf.quant_score,
        "pa_summary": conf.pa_summary,
        "ctx_summary":conf.ctx_summary,
        "quant_summary":conf.quant_summary,
        "invalidation":conf.invalidation,
        "mtf_detail": mtf.timeframe_results,
        "spx":        {"score": spx.spx_score, "vix_confirmed": spx.vix_confirmed, "summary": spx.summary} if spx else None,
    }


@app.post("/api/test/telegram")
def test_telegram():
    """Send a test Telegram alert to confirm the bot is working."""
    import httpx, os
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    enabled = os.environ.get("ALERTS_ENABLED", "false").lower() == "true"
    if not token or not chat_id:
        all_vars = [k for k in os.environ.keys() if "TELEGRAM" in k or "ALERT" in k]
        return {"status": "error", "message": f"TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment. Found vars: {all_vars}"}
    if not enabled:
        return {"status": "error", "message": "ALERTS_ENABLED is false — set it to true in Railway Variables"}
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = httpx.post(url, json={
            "chat_id": chat_id,
            "text": (
                "✅ *ATHENA TEST ALERT*\n\n"
                "If you see this message, Telegram alerts are working correctly\\!\n\n"
                "Ticker: SPY\n"
                "Direction: BULLISH\n"
                "Confidence: 85/100\n"
                "Entry: $730.00 | Stop: $725.00 | T1: $740.00"
            ),
        }, timeout=10)
        if resp.is_success and resp.json().get("ok"):
            return {"status": "success", "message": "Test alert sent — check your Telegram"}
        else:
            return {"status": "error", "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/debug/prices")
def debug_prices():
    """Check what prices yfinance actually returns for key tickers."""
    import yfinance as yf
    results = {}
    for ticker in ["SPY", "QQQ", "NVDA", "AAPL", "META"]:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = float(info.last_price or 0)
            prev  = float(info.previous_close or 0)
            results[ticker] = {"price": price, "prev_close": prev, "source": "yfinance"}
        except Exception as e:
            results[ticker] = {"price": 0, "error": str(e), "source": "failed"}
    return results


@app.get("/api/scheduler/jobs")
def get_jobs():
    """List all scheduled jobs."""
    if not scheduler:
        return []
    jobs = scheduler.get_jobs()
    return [{
        "id": j.id,
        "next_run": j.next_run_time.isoformat() if j.next_run_time else None,
    } for j in jobs]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
