# ATHENA AI Trading Assistant — Quick Start

## 1. Install dependencies

```bash
cd athena
pip install -r requirements.txt
```

## 2. Configure

```bash
cp .env.example .env
# Edit .env — at minimum nothing is required to run in mock mode
```

## 3. Run

```bash
python main.py
# or
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser → full dashboard

---

## What ATHENA does automatically

| Time (ET) | Phase |
|-----------|-------|
| 06:00 | Premarket bias — SPY/QQQ/VIX/Futures/Calendar |
| 07:00 | Quant download — Options flow, dark pools, OI |
| 08:00 | Discord parse — reads `data/discord_paste.txt` |
| 08:15 | Scanner — ranks all tickers |
| 09:00 | Watchlist — top 10 opportunities built |
| 09:30–16:00 | Live cycle every 2 min — evaluates, fires alerts |
| 17:00 | EOD — stores stats, updates evidence |

---

## API Endpoints

| Endpoint | What |
|----------|------|
| `GET /api/market/bias` | Current SPY/QQQ/VIX/bias |
| `GET /api/watchlist` | Today's watchlist |
| `GET /api/analyze/{TICKER}?direction=BULLISH` | Full on-demand analysis |
| `GET /api/trades/active` | Open trades |
| `POST /api/trades/open` | Open a trade |
| `POST /api/trades/{id}/close` | Close a trade |
| `GET /api/journal` | Trade journal |
| `GET /api/evidence` | Win rate, avg R, stats |
| `GET /api/quant/{TICKER}` | Options flow data |
| `POST /api/discord/parse` | Parse Discord watchlist |
| `POST /api/run/live-cycle` | Trigger live evaluation |
| `POST /api/run/premarket` | Run premarket workflow |

---

## Connect real data

### Market data (yfinance — free, already works)
No setup needed. yfinance is the default.

### Options flow (Unusual Whales)
```env
QUANT_PROVIDER=unusual_whales
UNUSUAL_WHALES_KEY=your_key_here
```

### Telegram alerts
```env
ALERTS_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Discord watchlists
Create `data/discord_paste.txt` and paste your watchlist.
ATHENA reads it at 8am and validates each idea against its own rules.

---

## Confidence Model

| Component | Weight |
|-----------|--------|
| Price Action | 50% |
| Multi-Timeframe | 20% |
| Market Context | 10% |
| Quant Confirmation | 10% |
| Evidence Adjustment | 10% |

**Price Action failure = NO TRADE** regardless of other scores.
Default threshold: **80/100** (configurable via `CONFIDENCE_THRESHOLD`).

---

## Project Structure

```
athena/
├── main.py                    FastAPI app + entry point
├── config.py                  All settings
├── requirements.txt
├── .env.example
├── engines/
│   ├── market_engine.py       SPY/QQQ/VIX/Futures/Sectors
│   ├── price_action_engine.py Trend/Structure/BOS/CHoCH/S&R/VWAP/EMAs
│   ├── multi_timeframe_engine.py  1D/4H/1H/15M/5M/1M alignment
│   ├── quant_engine.py        Flow/DP/GEX/Sweeps/Blocks
│   ├── spx_engine.py          VIX confirmation/Gamma/0DTE/Breadth/Time
│   ├── discord_engine.py      Watchlist parser + validator
│   ├── confidence_engine.py   Weighted score aggregator
│   └── evidence_engine.py     Statistical learning engine
├── workflow/
│   ├── athena_workflow.py     All 7 daily phases
│   └── scheduler.py           APScheduler jobs
├── alerts/
│   └── telegram.py            Telegram bot alerts
├── database/
│   ├── db.py                  SQLAlchemy session
│   └── models.py              All 9 core tables
└── dashboard/
    └── index.html             Full web dashboard
```
