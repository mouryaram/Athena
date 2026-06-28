"""
ATHENA Configuration
All settings in one place. Override via environment variables or .env file.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Confidence Thresholds ────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD = int(os.getenv("CONFIDENCE_THRESHOLD", "80"))

# Confidence weight distribution (must sum to 100)
CONFIDENCE_WEIGHTS = {
    "price_action":        50,
    "multi_timeframe":     20,
    "market_context":      10,
    "quant_confirmation":  10,
    "evidence_adjustment": 10,
}

# ─── Market Data ─────────────────────────────────────────────────────────────
MARKET_DATA_PROVIDER = os.getenv("MARKET_DATA_PROVIDER", "yfinance")  # yfinance | polygon
POLYGON_API_KEY      = os.getenv("POLYGON_API_KEY", "")
ALPHA_VANTAGE_KEY    = os.getenv("ALPHA_VANTAGE_KEY", "")

# Tickers always monitored
CORE_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
VIX_TICKER   = "^VIX"
SPX_TICKER   = "^GSPC"

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLC", "XLY", "XLP", "XLU", "XLRE", "XLB"]

# ─── Options / Quant Data ────────────────────────────────────────────────────
QUANT_PROVIDER    = os.getenv("QUANT_PROVIDER", "mock")   # mock | unusual_whales | tradier
UNUSUAL_WHALES_KEY = os.getenv("UNUSUAL_WHALES_KEY", "")
TRADIER_KEY        = os.getenv("TRADIER_KEY", "")

# ─── Alerts ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ALERTS_ENABLED     = os.getenv("ALERTS_ENABLED", "false").lower() == "true"

# ─── Discord ─────────────────────────────────────────────────────────────────
DISCORD_WATCHLIST_FILE = os.getenv("DISCORD_WATCHLIST_FILE", "data/discord_paste.txt")

# ─── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///athena.db")

# ─── Server ──────────────────────────────────────────────────────────────────
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# ─── Timeframes ──────────────────────────────────────────────────────────────
TIMEFRAMES = ["1d", "4h", "1h", "15m", "5m", "1m"]

# ─── Risk Management ─────────────────────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT = float(os.getenv("MAX_RISK_PCT", "1.0"))   # % of account
MIN_REWARD_RATIO       = float(os.getenv("MIN_RR", "2.0"))          # min R:R

# ─── Scheduler (market hours, Eastern) ───────────────────────────────────────
SCHEDULE = {
    "premarket_bias":    "0 6 * * 1-5",   # 6:00 AM ET Mon-Fri
    "quant_download":    "0 7 * * 1-5",   # 7:00 AM ET
    "discord_read":      "0 8 * * 1-5",   # 8:00 AM ET
    "premarket_scan":    "15 8 * * 1-5",  # 8:15 AM ET
    "build_watchlist":   "0 9 * * 1-5",   # 9:00 AM ET
    "market_open_loop":  "30 9 * * 1-5",  # 9:30 AM ET
    "eod_store":         "0 17 * * 1-5",  # 5:00 PM ET
}

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE   = os.getenv("LOG_FILE", "athena.log")
