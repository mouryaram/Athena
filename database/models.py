"""
ATHENA Database Models
All 9 core tables as defined in the specification.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime,
    Text, JSON, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
import enum
from database.db import Base


# ─── Enums ────────────────────────────────────────────────────────────────────

class Direction(str, enum.Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"

class TradeStatus(str, enum.Enum):
    WATCHING  = "WATCHING"
    TRIGGERED = "TRIGGERED"
    ACTIVE    = "ACTIVE"
    CLOSED    = "CLOSED"
    CANCELLED = "CANCELLED"

class Outcome(str, enum.Enum):
    WIN      = "WIN"
    LOSS     = "LOSS"
    BREAKEVEN= "BREAKEVEN"
    OPEN     = "OPEN"

class Recommendation(str, enum.Enum):
    HOLD            = "HOLD"
    TAKE_PARTIAL    = "TAKE_PARTIAL"
    MOVE_STOP       = "MOVE_STOP"
    TIGHTEN_STOP    = "TIGHTEN_STOP"
    EXIT            = "EXIT"
    REENTRY_WATCH   = "REENTRY_WATCH"
    NO_ACTION       = "NO_ACTION"


# ─── 1. Watchlists ────────────────────────────────────────────────────────────

class Watchlist(Base):
    __tablename__ = "watchlists"

    id            = Column(Integer, primary_key=True, index=True)
    date          = Column(DateTime, default=datetime.utcnow, index=True)
    ticker        = Column(String(16), nullable=False, index=True)
    direction     = Column(Enum(Direction), nullable=False)
    entry_price   = Column(Float)
    stop_price    = Column(Float)
    target1       = Column(Float)
    target2       = Column(Float)
    risk_pct      = Column(Float)
    confidence    = Column(Float)
    reason        = Column(Text)
    invalidation  = Column(Text)
    pa_score      = Column(Float)   # Price Action sub-score
    mtf_score     = Column(Float)   # Multi-Timeframe sub-score
    ctx_score     = Column(Float)   # Market Context sub-score
    quant_score   = Column(Float)   # Quant sub-score
    ev_score      = Column(Float)   # Evidence sub-score
    source        = Column(String(32), default="ATHENA")  # ATHENA | DISCORD
    active        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)


# ─── 2. Trade Ideas ───────────────────────────────────────────────────────────

class TradeIdea(Base):
    __tablename__ = "trade_ideas"

    id            = Column(Integer, primary_key=True, index=True)
    date          = Column(DateTime, default=datetime.utcnow, index=True)
    ticker        = Column(String(16), nullable=False)
    direction     = Column(Enum(Direction))
    entry         = Column(Float)
    stop          = Column(Float)
    target1       = Column(Float)
    target2       = Column(Float)
    confidence    = Column(Float)
    pa_summary    = Column(Text)
    ctx_summary   = Column(Text)
    quant_summary = Column(Text)
    invalidation  = Column(Text)
    alerted       = Column(Boolean, default=False)
    alert_sent_at = Column(DateTime)
    status        = Column(Enum(TradeStatus), default=TradeStatus.WATCHING)
    source        = Column(String(32), default="ATHENA")
    raw_data      = Column(JSON)


# ─── 3. Active Trades ─────────────────────────────────────────────────────────

class ActiveTrade(Base):
    __tablename__ = "active_trades"

    id               = Column(Integer, primary_key=True, index=True)
    idea_id          = Column(Integer, ForeignKey("trade_ideas.id"))
    ticker           = Column(String(16), nullable=False)
    direction        = Column(Enum(Direction))
    entry_price      = Column(Float)
    current_price    = Column(Float)
    stop_price       = Column(Float)
    target1          = Column(Float)
    target2          = Column(Float)
    size             = Column(Float, default=1.0)  # position size / contracts
    entered_at       = Column(DateTime)
    last_updated     = Column(DateTime, default=datetime.utcnow)
    unrealized_pnl   = Column(Float, default=0.0)
    recommendation   = Column(Enum(Recommendation), default=Recommendation.NO_ACTION)
    recommendation_reason = Column(Text)
    partial_taken    = Column(Boolean, default=False)
    stop_moved       = Column(Boolean, default=False)
    notes            = Column(Text)
    status           = Column(Enum(TradeStatus), default=TradeStatus.ACTIVE)

    idea = relationship("TradeIdea", backref="active_trade")


# ─── 4. Trade Journal ─────────────────────────────────────────────────────────

class TradeJournal(Base):
    __tablename__ = "trade_journal"

    id             = Column(Integer, primary_key=True, index=True)
    active_trade_id= Column(Integer, ForeignKey("active_trades.id"))
    ticker         = Column(String(16), nullable=False)
    direction      = Column(Enum(Direction))
    entry_price    = Column(Float)
    exit_price     = Column(Float)
    stop_price     = Column(Float)
    target1        = Column(Float)
    target2        = Column(Float)
    size           = Column(Float)
    pnl            = Column(Float)
    pnl_r          = Column(Float)   # P&L in R multiples
    outcome        = Column(Enum(Outcome))
    entered_at     = Column(DateTime)
    exited_at      = Column(DateTime)
    duration_mins  = Column(Integer)
    pa_score       = Column(Float)
    confidence     = Column(Float)
    market_bias    = Column(String(16))
    vix_at_entry   = Column(Float)
    setup_type     = Column(String(64))
    weekday        = Column(String(16))
    hour_of_day    = Column(Integer)
    notes          = Column(Text)
    lesson         = Column(Text)
    screenshot_path= Column(String(256))
    tags           = Column(JSON)
    created_at     = Column(DateTime, default=datetime.utcnow)

    active_trade = relationship("ActiveTrade", backref="journal_entry")


# ─── 5. Evidence Rules ────────────────────────────────────────────────────────

class EvidenceRule(Base):
    __tablename__ = "evidence_rules"

    id              = Column(Integer, primary_key=True, index=True)
    rule_type       = Column(String(64), nullable=False, index=True)
    # e.g. "setup_type", "weekday", "hour", "ticker", "market_condition"
    rule_value      = Column(String(128), nullable=False)
    sample_size     = Column(Integer, default=0)
    win_count       = Column(Integer, default=0)
    loss_count      = Column(Integer, default=0)
    win_rate        = Column(Float, default=0.0)
    avg_r           = Column(Float, default=0.0)
    max_drawdown    = Column(Float, default=0.0)
    confidence_adj  = Column(Float, default=0.0)  # adjustment applied to confidence
    last_updated    = Column(DateTime, default=datetime.utcnow)
    notes           = Column(Text)


# ─── 6. Market Snapshots ─────────────────────────────────────────────────────

class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id             = Column(Integer, primary_key=True, index=True)
    timestamp      = Column(DateTime, default=datetime.utcnow, index=True)
    spy_price      = Column(Float)
    spy_change_pct = Column(Float)
    qqq_price      = Column(Float)
    qqq_change_pct = Column(Float)
    vix_price      = Column(Float)
    vix_change_pct = Column(Float)
    spx_price      = Column(Float)
    futures_es     = Column(Float)
    futures_nq     = Column(Float)
    market_bias    = Column(Enum(Direction))
    bias_strength  = Column(Float)   # 0-100
    breadth_advdec = Column(Float)   # advance/decline ratio
    above_vwap_pct = Column(Float)
    sector_data    = Column(JSON)    # {"XLK": 1.2, "XLF": -0.5, ...}
    notes          = Column(Text)


# ─── 7. Quant Snapshots ──────────────────────────────────────────────────────

class QuantSnapshot(Base):
    __tablename__ = "quant_snapshots"

    id              = Column(Integer, primary_key=True, index=True)
    timestamp       = Column(DateTime, default=datetime.utcnow, index=True)
    ticker          = Column(String(16), nullable=False, index=True)
    call_flow       = Column(Float)   # net premium call flow
    put_flow        = Column(Float)
    flow_bias       = Column(Enum(Direction))
    dark_pool_prints= Column(Float)
    gamma_exposure  = Column(Float)
    delta_exposure  = Column(Float)
    open_interest_c = Column(Float)   # call OI
    open_interest_p = Column(Float)   # put OI
    put_call_ratio  = Column(Float)
    sweeps_bullish  = Column(Integer, default=0)
    sweeps_bearish  = Column(Integer, default=0)
    block_trades    = Column(Integer, default=0)
    confirmation_score = Column(Float, default=0.0)
    raw_data        = Column(JSON)


# ─── 8. Discord Watchlists ───────────────────────────────────────────────────

class DiscordWatchlist(Base):
    __tablename__ = "discord_watchlists"

    id             = Column(Integer, primary_key=True, index=True)
    date           = Column(DateTime, default=datetime.utcnow, index=True)
    source_text    = Column(Text)   # raw paste
    ticker         = Column(String(16), nullable=False)
    direction      = Column(Enum(Direction))
    trigger        = Column(Float)
    stop           = Column(Float)
    target         = Column(Float)
    notes          = Column(Text)
    validated      = Column(Boolean, default=False)
    validation_score = Column(Float)
    athena_agrees  = Column(Boolean)
    reason         = Column(Text)
    created_at     = Column(DateTime, default=datetime.utcnow)


# ─── 9. Statistics ───────────────────────────────────────────────────────────

class DailyStatistic(Base):
    __tablename__ = "daily_statistics"

    id             = Column(Integer, primary_key=True, index=True)
    date           = Column(DateTime, nullable=False, unique=True, index=True)
    trades_taken   = Column(Integer, default=0)
    alerts_sent    = Column(Integer, default=0)
    wins           = Column(Integer, default=0)
    losses         = Column(Integer, default=0)
    win_rate       = Column(Float, default=0.0)
    total_r        = Column(Float, default=0.0)
    avg_r          = Column(Float, default=0.0)
    max_drawdown_r = Column(Float, default=0.0)
    best_trade     = Column(String(16))
    worst_trade    = Column(String(16))
    market_bias    = Column(Enum(Direction))
    vix_open       = Column(Float)
    vix_close      = Column(Float)
    notes          = Column(Text)
    created_at     = Column(DateTime, default=datetime.utcnow)


class WeeklyStatistic(Base):
    __tablename__ = "weekly_statistics"

    id          = Column(Integer, primary_key=True)
    week_start  = Column(DateTime, nullable=False, unique=True)
    week_end    = Column(DateTime)
    trades      = Column(Integer, default=0)
    wins        = Column(Integer, default=0)
    losses      = Column(Integer, default=0)
    win_rate    = Column(Float, default=0.0)
    total_r     = Column(Float, default=0.0)
    best_setup  = Column(String(64))
    worst_setup = Column(String(64))
    notes       = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)


class MonthlyStatistic(Base):
    __tablename__ = "monthly_statistics"

    id           = Column(Integer, primary_key=True)
    month        = Column(Integer)
    year         = Column(Integer)
    trades       = Column(Integer, default=0)
    wins         = Column(Integer, default=0)
    losses       = Column(Integer, default=0)
    win_rate     = Column(Float, default=0.0)
    total_r      = Column(Float, default=0.0)
    sharpe_ratio = Column(Float)
    max_drawdown = Column(Float)
    notes        = Column(Text)
    created_at   = Column(DateTime, default=datetime.utcnow)
