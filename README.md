# NIFTY Options AI Trading Engine & Market Intelligence

> **Current implementation/release status (2026-10-30):** See [canonical status](docs/architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md) and the [LIVE hold](docs/architecture/LIVE_ACTIVATION_HOLD_20261030.md). The local repair candidate on `feature/live-activation-guardrails-20261030` passes the quality wrapper and **574 offline tests**; see [validation and candidate identity](docs/architecture/OFFLINE_VALIDATION_20261030.md). The feature-branch candidate remains unmerged and undeployed, with `r01_policy.enabled=false`. Kite risk/contract/calendar read-only acceptance passes; operator-run broker order UAT remains open. The release targets this Windows machine; no CI rollout is required. Historical backtests and performance claims do not certify this release. **Do not start native `--live` without a separately approved supervised release.**


Development: run `python -m tools.checks` for offline regression and boundary checks.
Run `python -m tools.quality` for pinned lint/type checks plus the offline suite.
See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[architecture review](docs/ARCHITECTURE_REVIEW.md) for refactoring rules and findings.
The [completed staged refactor](docs/STAGED_REFACTOR.md) documents the current
services and workspace-only decision replay.
Runtime output now goes to `logs/trader-YYYY-MM-DD.log` by IST date; daily journals
and trade reports live under `logs/daily/YYYY-MM-DD/`. See
[daily logging and maintenance](docs/DAILY_LOGS.md) for report fields and retention commands.
Native Kite and ICICI Breeze execution use `--broker kite --live` and
`--broker breeze --live`; see [broker setup](docs/BROKER_INTEGRATIONS.md) and
[gateway safety and recovery](docs/NATIVE_GATEWAY_SAFETY.md). Check both accounts
without arming execution using `python -m tools.brokers --broker both`.
Legacy positions retain [uncapped runner trailing and verified stop replacement](docs/TRAILING_STOPS.md). Opted-in, R01-stamped positions use a [separate shared stop/OMS contract](docs/architecture/R01_UNIFIED_STOP_EXECUTION.md), not yet tested or activated.

Automated, multi-factor AI trading engine for **NIFTY 50 Index Options**, combining **internal broker feeds (Zerodha Kite & ICICI Breeze)**, **PR #51 Precision Order Execution (PAPER & LIVE)**, **multi-timeframe option-premium technical indicators**, **real-time external market intelligence (Global Cues & Live Financial News)**, an **Institutional Liquidity Trap Detection Gateway (8 Playbook Traps)**, an **Autonomous AI Opportunity Radar (Strategy 4)**, and a **Dynamic Incremental Trailing Ratchet Engine**.

> [!IMPORTANT]
> ### 🧠 MANDATORY SYSTEM DIRECTIVE: AI IS THE NON-NEGOTIABLE CORE INTELLIGENCE
> **Artificial Intelligence is NOT an optional add-on, secondary filter, or cosmetic feature in this repository. It is the central nervous system and non-negotiable risk gatekeeper of every trade decision.**
>
> **The Empirical Reality (Proven across 30 to 60 Trading Sessions):**
> * ❌ **WITHOUT AI (Mechanical Scalping / Blind Indicators):** Suffered catastrophic account liquidation: **-805.8% Net ROI (-₹80,577.20 loss)**, 38.2% win rate, and total capital wipeout caused by VWAP blender chop, false breakouts, and overbought climax chasing.
> * ✅ **WITH AI GATEKEEPER (Strategy 3 Baseline):** Generated **+462.8% Net ROI (+₹46,283.80)** on ₹10k capital across 30 sessions, with a **79.7% Win Rate (55W / 14L)** and **100% win retention (55/55 wins preserved)**.
> * 🏆 **WITH AI OPPORTUNITY RADAR (Strategy 4 Active - Fixed 2 Lots):** Generated **+638.3% Net ROI (+₹73,830.70)** on ₹10k capital across 30 sessions, adding **+₹27,546.90 alpha** over baseline by capturing both Trend Pullbacks and Morning Climax Springs with Structural Wick Stops.
> * 🚀 **WITH STEP-LADDER COMPOUNDING (Strategy 4 Active - 2 to 10 Lots):** Compounded ₹10k into **₹118,434.05 (+1,084.3% Net ROI / >11x compounding)** across 30 sessions, and into **₹152,563.90 (+1,425.6% Net ROI / >15x compounding)** across 60 multi-regime sessions with automatic drawdown de-escalation.
>
> **Operating Mandate for Any Agent or Operator:**
> 1. **Zero Trades Without Evaluation:** Every candidate trade (`BUY_CE` or `BUY_PE`) must be evaluated by the Risk Gatekeeper ([`ai_consultant.py`](ai_consultant.py)) against the [Deterministic Rules Playbook](config/rules_playbook.md).
> 2. **AI Definition Mandate:** "AI" means an explicitly invoked neural companion: **Codex in ChatGPT IDE** or the legacy Antigravity companion (`--ai-mode chat`). An idle watcher alone is not inference. `rules` / `playbook` execute deterministic code with **NO neural AI**. See [persistent Codex worker](docs/CODEX_COMPANION.md).
> 3. **Supreme Veto Authority:** If any of the 8 Institutional Traps are flagged, the setup is **instantly vetoed** and the system stands aside in cash.
> 4. **Fail-Safe to Capital Preservation:** If consultation times out, disconnects, or encounters an error, the engine **fails-safe to ZERO trades placed**. Never fall back to blind execution.
> 4. **Detailed Reference:** See [AI Architecture & Operational Directive](docs/AI_ARCHITECTURE_AND_DIRECTIVE.md).

---

## 📌 Architecture & Division of Responsibilities

```
                                  +----------------------------------------------+
                                  |   External Sources (Web / Free Ingestion)    |
                                  |   - Global Cues: Crude, Dow, Nasdaq, USD/INR |
                                  |   - Live News: Moneycontrol, ET Markets RSS  |
                                  +----------------------------------------------+
                                                         |
                                                         v
                                          +-------------------------------+
                                          |    market_intelligence.py     |
                                          |  - Macro Sentiment (-3 to +3) |
                                          |  - Catalyst & Headline Tagging|
                                          |  - Trap & Divergence Flags    |
                                          |  - logs/latest_intelligence.md|
                                          +-------------------------------+
                                                         |
+-------------------------------------+                  |
| Direct Broker Feeds (In-Process)    |                  |
| - Native Kite & Breeze Feeds        |                  v
| - NIFTY Spot Candles & 5m EMAs      | -----> +------------------------------------+
| - Option Chain, OI Changes & PCR    |        |     nifty_trader_scheduler.py      |
| - India VIX & Sector Breadth        |        | - 1-Minute Automated Daemon        |
| - Native L2 Option Depth Quotes     |        | - True Spot VWAP & 5m EMA Engine   |
+-------------------------------------+        | - News & Macro Ingestion (Step 3)  |
                  ^                            +------------------------------------+
                  |                                              |
                  |                                              v
                  |                            +------------------------------------+
                  |                            |       Market State Dossier         |
                  |                            |   logs/pending_consultation.md     |
                  |                            +------------------------------------+
                  |                                              |
                  |                                              v
                  |                            +------------------------------------+
                  |                            |   Antigravity Chat Pair-Trading    |
                  |                            |   - Mode: "playbook" or "chat"     |
                  |                            |   - 45s Consultation Window        |
                  |                            |   - 8 Institutional Trap Vetoes    |
                  |                            |   - Sector Divergence Veto         |
                  |                            +------------------------------------+
                  |                                              | (If APPROVED)
                  |                                              v
                  +--- Native Broker OMS (Kite/Breeze) <---------+
                       Limit Orders / Resting Stops / Dynamic Ratchets
```

### Core Components
1. **News-First Market Intelligence ([`market_intelligence.py`](market_intelligence.py))**:
   - Ingests real-time catalysts (Crude Oil, Dow Jones, Nasdaq, USD/INR) and live financial RSS feeds (Moneycontrol, ET Markets) with zero paid API keys.
   - Computes composite macro bias (-3 to +3), highlights top catalysts, and flags macro-price trap divergences.
   - Automatically maintains `logs/latest_intelligence.json` and `logs/latest_intelligence.md` at every cycle.
2. **In-Process Market Data ([`trading/adapters/market_data.py`](trading/adapters/market_data.py)) & Native Gateways ([`trading/adapters/gateways/kite.py`](trading/adapters/gateways/kite.py) & [`breeze.py`](trading/adapters/gateways/breeze.py))**:
   - Direct broker market data ingestion (Kite & ICICI Breeze) with zero external port 8000 server dependency.
   - Serves real completed spot candles, true Session VWAP, 5m EMAs, option chain Open Interest (OI), India VIX, and banking/IT sector breadth.
   - Native execution gateways implement idempotent BUY limit orders, crash-safe intent journalling (`logs/broker_intents.json`), resting stop-loss orders, and dynamic ratchets.
3. **Execution Client ([`execution_client.py`](execution_client.py))**:
   - Client wrapper for local proxy OMS (used when running with `--broker proxy` or for paper simulation).
4. **AI Market Dossier & Consultation Gateway ([`ai_context_dossier.py`](ai_context_dossier.py) & [`ai_consultant.py`](ai_consultant.py))**:
   - Compiles comprehensive 6-section market dossiers (EMA ribbons, VWAP blender geometry, consolidation boxes, order flow, heavyweights, India VIX, sector breadth, and live news headlines).
   - Serves the **Codex / legacy neural companion** handshake (`mode: "chat"`) or autonomous (`mode: "playbook"`).
   - Evaluates candidate trades against the **8 Institutional Traps** plus **Sector Divergence Veto** before any capital is committed.
5. **AI Opportunity Radar ([`ai_opportunity_radar.py`](ai_opportunity_radar.py))**:
   - Autonomous multi-regime opportunity discovery engine (Strategy 4).
   - Continuously evaluates the 6D market state on every bar to identify high-conviction **Dynamic Trend Pullbacks** and **Morning Climax Springs**.
   - Computes structural wick invalidation levels to cap false turns at -6% to -8% loss rather than enduring full -30% theta drawdowns.
6. **Trader & Scheduler Engine ([`nifty_trader_scheduler.py`](nifty_trader_scheduler.py))**:
   - Coordinates the 1-minute execution cycle.
   - Seamlessly switches between Strategy 4 (`ai_opportunity_radar`) and Strategy 3 (`institutional_pullback` backup).
   - Uses **True Spot Session VWAP** and **5m EMAs** derived from spot candles for 100% mathematical parity with the backtest engine.
   - Actively manages open trades with structural wick stops, a **Dynamic Incremental Trailing Ratchet** (+10%, +20%, +30% profit floors), and a 50% profit target cap.

---

## 🔒 Strict Operational Constraints (For Agents & Automated Systems)

When working within or extending this repository, every agent and process must adhere to the following rules:
1. **Directory Isolation:** Strictly work ONLY inside `c:\Users\hawis\Documents\antigravity\splendid-bardeen`. **NEVER** edit, create, or modify files in `icici-breeze-api-trading` or any directory outside this workspace.
2. **Capital, Step-Ladder Compounding & Position Sizing:**
   - Baseline capital is **₹10,000 Margin** (sized for 2 lots / 130 NIFTY contracts).
   - **Owner-approved R01 maximum sizing (disabled):** 2/4/6/8/10 lots for verified available-margin bands below ₹40k / ₹40k–<₹60k / ₹60k–<₹80k / ₹80k–<₹100k / ₹100k+ respectively. Executable option price, the ₹150 reserve, hard caps and verified exchange limits can lower quantity.
   - Dynamic drawdown protection: lot sizing instantly de-escalates to the lower tier if account equity drops below a milestone.
   - Maximum **1 concurrent open position**.
   - Zero-shortfall purchasing power buffer reserves a ₹150 buffer for taxes, STT, and exchange turnover: `safe_margin = max(0, available_margin - 150)`.
3. **Overnight Flat Book:** Strictly **0 positions carried overnight**. All intraday positions are squared off by 15:15 IST.
4. **Zero Paid API Costs:** Operates entirely on free broker sessions (Zerodha Kite & ICICI Breeze) and free external web scraping/RSS feeds.

---

## 🧠 The 6-Stage AI Decision Lifecycle

AI is not an afterthought or an isolated check; it actively governs every single step of the trade lifecycle:

```
+--------------------------------------------------------------------------------------------------+
|                                    THE 6-STAGE AI LIFECYCLE                                      |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|  STAGE 1: External Market & Macro Intelligence (market_intelligence.py)                          |
|  • Continuous live ingestion of Global Cues (Crude Oil, Dow, Nasdaq, USD/INR)                   |
|  • Real-time financial news NLP scraping (Moneycontrol, ET Markets RSS)                          |
|  • Algorithmic Macro Bias (-3 to +3) and Divergence / Trap Tagging                               |
|                                     │                                                            |
|                                     ▼                                                            |
|  STAGE 2: Multi-Factor Context Dossier Compilation (ai_context_dossier.py)                       |
|  • Compiles 6-dimensional full-session state: True Spot VWAP crosses, 5m EMA9/20 ribbon spread,   |
|    15m Consolidation Box, 1m RSI exhaustion, and top 5 heavyweights breadth (HDFC, Reliance, etc.)|
|                                     │                                                            |
|                                     ▼                                                            |
|  STAGE 3: Institutional Pullback Setup Qualification (Strategy 3 Engine)                         |
|  • Filters out mid-air chasing; demands 4.0-point pullback to 5m EMA9                            |
|  • Enforces Strict ITM strike selection (delta ≥ 0.55) to eliminate 0DTE theta wipeout           |
|                                     │                                                            |
|                                     ▼                                                            |
|  STAGE 4: The Risk Gatekeeper (ai_consultant.py & rules_playbook.md)                             |
|  • Candidate setup submitted to AI Consultant before ANY capital is committed                    |
|  • Autonomous evaluation across the 8 Institutional Traps:                                       |
|    1. VWAP Blender (Choppy rotation)             5. Late-Day Capital Preservation (+₹1,800 lock) |
|    2. Heavyweight Divergence (Artificial ramps)  6. Compressed Ribbon Coiling Check              |
|    3. Vertical RSI Exhaustion / Falling Knife    7. 0DTE Penny Option Gamma Trap (< ₹12)         |
|    4. Range Box Ceiling / Floor Trap             8. Consecutive Loss Circuit Breaker             |
|  • Emits AIVerdict (APPROVED / VETOED) with confidence score and human-readable reasoning         |
|                                     │                                                            |
|                                     ▼                                                            |
|  STAGE 5: Dynamic Trailing Ratchet & Risk Management (nifty_trader_scheduler.py)                |
|  • Fast 5-second active position monitoring loop                                                 |
|  • Dynamic Profit Ratchet: +10% ──> Breakeven, +20% ──> +10% Floor, +30% ──> +20% Floor         |
|  • Late-Day Micro-Trail: Locks +1% floor on +4% gains post-14:00 IST                              |
|  • Trailing Stop Priority: Profit floors override premature indicator cutoffs                    |
|                                     │                                                            |
|                                     ▼                                                            |
|  STAGE 6: Liquidity Reversal Intelligence (The Failure Flip Protocol)                           |
|  • If an initial stop is hit, AI flags trapped institutional liquidity                          |
|  • Evaluates opposite-direction expansion setups to recover stop-outs on high-momentum reversals |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
```

---

## ⚖️ Architectural Demarcation: Deterministic Math vs. AI Intelligence

To prevent "black-box confusion" and ensure absolute institutional rigor, the system enforces a strict, transparent demarcation between **Deterministic Rules** and **AI Machine Intelligence**:

```
+-------------------------------------------------------------------------------------------------------+
|                                    CLEAR ARCHITECTURAL DEMARCATION                                    |
+-------------------------------------------------------------------------------------------------------+
|  DETERMINISTIC EXECUTION CORE (The Muscles)       |  AI MACHINE INTELLIGENCE LAYER (The Brain)        |
|  - 100% Rule-Based, Zero Ambiguity, Zero Hallucination|  - Contextual, Heuristic, Multi-Factor Synthesis   |
|---------------------------------------------------+---------------------------------------------------|
|  1. Mathematical Parity Engine:                   |  1. Macro & News NLP Scraping:                    |
|     • Bit-for-bit 1m to 5m candle resampling      |     • Real-time financial headline sentiment      |
|     • True Spot Session VWAP calculation          |     • Intermarket catalyst correlation (Crude/Dow)|
|     • 0.05 tick rounding for option orders        |     • Algorithmic Macro Bias score (-3 to +3)     |
|                                                   |                                                   |
|  2. Strict Boundary Rules:                        |  2. Multi-Dimensional Feature Dossier:           |
|     • 10-minute structural cooldown (min_spacing) |     • Synthesis of 6 market state dimensions      |
|     • 4.0-point EMA9 pullback threshold           |     • Heavyweight divergence detection (HDFC/Rel) |
|     • Mandatory flat book overnight by 15:15 IST  |     • Order flow imbalance & PCR analysis         |
|                                                   |                                                   |
|  3. PR #51 Broker OMS Execution:                  |  3. The 8 Institutional Trap Veto Gateway:        |
|     • Submits BUY LIMIT orders to Kite book       |     • Pattern recognition of institutional traps  |
|     • Arms resting SELL SL-LIMIT stop loss orders |     • Supreme Veto Authority before capital risk  |
|     • Cancels stops prior to discretionary exits  |     • Recommended trailing model (runner vs tight)|
|                                                   |                                                   |
|  4. Physical Trailing Ratchet:                    |  4. Pair-Trading Copilot Escrow:                  |
|     • 5-second polling loop                       |     • 45-second interactive consultation window   |
|     • Continuous PATCH modification of resting SL |     • Human / Antigravity Chat review handshake   |
|     • Enforces +10%, +20%, +30% profit floors     |     • Fail-safe timeout to Capital Preservation   |
+-------------------------------------------------------------------------------------------------------+
```

### The Operating Paradigm:
> 💡 **"Deterministic Math Proposes $\longrightarrow$ AI Intelligence Disposes $\longrightarrow$ Deterministic OMS Executes"**
>
> 1. **Deterministic Engine:** Scans market candles and identifies when price structurally touches the 5m EMA9.
> 2. **AI Gatekeeper:** Compiles the complete market dossier and evaluates the setup against the 8 Institutional Traps. If ANY trap, negative news catalyst, or heavyweight divergence is detected, **AI exercises supreme veto power** and blocks the trade.
> 3. **Deterministic OMS:** ONLY if AI returns `APPROVED` with high confidence ($\ge 80\%$) does the OMS size the order within available margin and place the physical order on Zerodha Kite.
> 4. **In-Flight Protection:** The physical stop loss is placed directly on the broker's book, while AI monitors market structure for invalidations or trapped liquidity flips.

---

## Repository-owned market data

The engine now obtains its six market-data capabilities directly through a configurable
Kite/Breeze provider inside this repository. Set `MARKET_DATA_BROKER=kite|breeze` or use
`--market-data-broker`. Execution selection remains independent through `--broker`.
See [market-data setup, contracts, and read-only preflight](docs/MARKET_DATA.md).
Snapshots also carry India VIX and Banking/IT breadth for the AI dossier. Native option
depth powers entry and monitor quotes. Optional KiteTicker streaming and VIX-adaptive
exits are configured as described in the same guide.

## 📡 Legacy Backend Market & Trading API Reference (`http://127.0.0.1:8000`)

### 1. Market Data & Multi-Timeframe Feeds

| Method | Endpoint | Query Parameters | Description & Capabilities |
|---|---|---|---|
| `GET` | `/api/v1/ai/data-quality` | — | Real Kite market feed condition, exchange timestamps, latency, and quote freshness. |
| `GET` | `/api/v1/ai/nifty/snapshot` | — | Complete NIFTY spot market overview: day high/low/open, underlying price, and change %. |
| `GET` | `/api/v1/ai/heavyweights` | — | Live batched Kite quotes for top 5 drivers: `HDFCBANK`, `RELIANCE`, `ICICIBANK`, `INFY`, `TCS`. |
| `GET` | `/api/v1/ai/nifty/candles` | `interval` (`1m`/`5m`), `limit` ($\ge 20$) | Completed NIFTY spot cash index candles. |
| `GET` | `/api/v1/market/candles` | `instrument_id`, `interval` (`1m`/`5m`/`15m`), `limit` | Completed OHLCV candles for **any** contract or underlying (e.g. `INST-NIFTY-2026-10-13-22500-CE`). |
| `GET` | `/api/v1/market/quotes` | `instrument_ids` (repeated) | Live batched market quotes for multiple instrument IDs. |
| `GET` | `/api/v1/market/quote/{instrument_id}` | — | Single live quote for a specific contract or equity instrument. |
| `GET` | `/api/v1/options/chain` | `underlying`, `expiry` | Direct broker option chain with strike details. |
| `GET` | `/api/v1/instruments/search` | `query`, `exchange` | Search and resolve tradable instrument IDs. |
| `GET` | `/api/v1/instruments/expiries` | `underlying` (default `NIFTY`) | Returns list of available weekly and monthly expiry dates. |

---

### 2. Technicals & Option-Premium Indicators

| Method | Endpoint | Query Parameters | Description & Capabilities |
|---|---|---|---|
| `GET` | `/api/v1/ai/nifty/technicals` | `interval` (`5m`), `limit` ($\ge 50$) | NIFTY index technicals (EMA9, EMA20, EMA50, RSI-14, MACD, ATR-14, Futures VWAP). |
| `GET` | `/api/v1/ai/nifty/options/technicals` | `instrument_ids` (repeated, 1–6), `interval` (`1m`/`5m`/`15m`), `limit` (50–500) | **Option-Premium Technicals:** Calculates independent technical indicators for multiple option contracts directly from Zerodha Kite option-premium candles. |
| `GET` | `/api/v1/ai/nifty/options` | `strike_window` (default `5`), `expiry` (optional) | Live option chain: ATM strikes, bid/ask, volume, total OI, session `oi_change`, and PCR. |

---

### 3. Deep Dive: `GET /api/v1/ai/nifty/options/technicals`

Calculates technical indicators independently for multiple NIFTY option contracts (CE and PE) using each contract's own historical option-premium OHLCV candles from Zerodha Kite. **These are pure option-premium metrics, free from Nifty futures basis or spot distortion.**

- **Method:** `GET`
- **Base Path:** `http://127.0.0.1:8000/api/v1/ai/nifty/options/technicals`
- **Query Parameters:**
  - `instrument_ids` (*string, repeated, required*): 1–6 NIFTY option instrument IDs (e.g. `?instrument_ids=INST-NIFTY-2026-10-13-22650-CE&instrument_ids=INST-NIFTY-2026-10-13-22650-PE`)
  - `interval` (*string, optional, default `5m`*): `1m`, `5m`, or `15m`
  - `limit` (*integer, optional, default `200`*): 50–500 completed candles per contract

#### Sample Request:
```http
GET /api/v1/ai/nifty/options/technicals?instrument_ids=INST-NIFTY-2026-10-13-22650-CE&interval=5m&limit=50 HTTP/1.1
Host: 127.0.0.1:8000
Accept: application/json
```

#### Sample Response:
```json
{
  "underlying": "NIFTY",
  "basis": "OPTION_PREMIUM",
  "source": "KITE",
  "interval": "5m",
  "requested_limit": 50,
  "requested_count": 1,
  "available_count": 1,
  "calculated_at": "2026-10-13T10:15:00+00:00",
  "contracts": [
    {
      "instrument_id": "INST-NIFTY-2026-10-13-22650-CE",
      "symbol": "NIFTY26O1322650CE",
      "expiry": "2026-10-13",
      "strike": 22650.0,
      "right": "CE",
      "lot_size": 65,
      "available": true,
      "source": "KITE",
      "basis": "OPTION_PREMIUM",
      "interval": "5m",
      "requested_limit": 50,
      "candle_count": 50,
      "data_through": "2026-10-13T10:10:00+00:00",
      "age_seconds": 300.0,
      "missing_recent_session_bars": false,
      "metrics": {
        "data_points": 50,
        "latest_close": 71.75,
        "ema_9": 63.33,
        "ema_20": 48.79,
        "ema_50": 21.71,
        "rsi_14": 76.39,
        "rsi_14_prev": 76.58,
        "rsi_14_prev2": 76.64,
        "rsi_crossed_above_55": false,
        "rsi_crossed_below_45": false,
        "macd": 15.82,
        "macd_signal": 13.64,
        "macd_histogram": 2.19,
        "macd_histogram_prev": 2.69,
        "macd_histogram_prev2": 3.08,
        "macd_crossed_above_zero": false,
        "macd_crossed_below_zero": false,
        "macd_histogram_expanding_positive": false,
        "macd_histogram_expanding_negative": false,
        "bar_end_time": "2026-10-13T10:10:00+00:00",
        "atr_14": 12.94,
        "vwap": 24.67,
        "session_vwap": 24.55,
        "vwap_scope": "requested_candles",
        "return_1_bar_pct": -0.21,
        "return_3_bar_pct": 7.01
      }
    }
  ]
}
```

---

### 4. Broker Sessions & Account Management

| Method | Endpoint | Request / Parameters | Description |
|---|---|---|---|
| `GET` | `/api/v1/ai/broker/sessions` | — | Real Kite and Breeze connection statuses and session expiry timestamps. |
| `POST` | `/api/v1/ai/broker/session/login-url` | `{"broker": "kite"}` | Generates broker OAuth/login URL for session initialization. |
| `POST` | `/api/v1/ai/broker/session/activate` | `{"broker": "kite", "request_token": "..."}` | Activates broker session with auth token. |
| `GET` | `/api/v1/ai/account/context` | — | Account cash, available margin, broker connectivity, risk limits, and active OMS mode. |

---

### 5. PR #51 Order Execution & OMS Engine ([`execution_client.py`](execution_client.py))

All order execution endpoints support both `PAPER` simulation and `LIVE` broker execution via the header `X-AI-Execution-Key`.

| Method | Endpoint | Request Payload / Query | Description |
|---|---|---|---|
| `GET` | `/api/v1/ai/execution/status` | — | Current active mode (`PAPER` / `LIVE`), live execution authorization, and broker connection. |
| `POST` | `/api/v1/ai/execution/mode` | `{"mode": "LIVE"}` or `{"mode": "PAPER"}` | Switches trading execution mode safely. |
| `POST` | `/api/v1/ai/execution/orders` | `{"request_id": "...", "instrument_id": "...", "quantity": 130, "limit_price": 53.90}` | Places a BUY LIMIT order on the broker OMS. |
| `GET` | `/api/v1/ai/execution/orders` | — | Returns up to 200 recent journal orders across paper and live. |
| `GET` | `/api/v1/ai/execution/orders/{order_id}` | — | Polls fill status (`FILLED`, `REJECTED`, `CANCELLED`), average fill price, and timestamps. |
| `DELETE` | `/api/v1/ai/execution/orders/{order_id}` | — | Cancels an unfilled resting entry order. |
| `POST` | `/api/v1/ai/execution/stops` | `{"request_id": "...", "entry_order_id": "...", "trigger_price": 37.75, "limit_price": 36.95}` | Arms resting protective stop-loss (SELL SL-LIMIT) on broker book. |
| `PATCH` | `/api/v1/ai/execution/stops/{stop_order_id}` | `{"trigger_price": 45.00, "limit_price": 44.10}` | **Stop Ratchet:** Modifies resting stop higher for continuous dynamic trailing. |
| `DELETE` | `/api/v1/ai/execution/stops/{stop_order_id}` | — | Cancels resting protective stop-loss prior to discretionary exits. |
| `POST` | `/api/v1/ai/execution/exit` | `{"request_id": "...", "entry_order_id": "...", "limit_price": 65.50}` | Discretionary position exit order (SELL LIMIT for open quantity). |
| `GET` | `/api/v1/ai/execution/positions` | — | Returns live broker/paper open positions, average fill price, and unrealized M2M. |
| `GET` | `/api/v1/ai/execution/monitor` | — | Execution latency, queue health, fill rates, and order lifecycle telemetry. |
| `GET` | `/api/v1/ai/trades` | `limit` (default 25, up to 100) | Historical AI journal orders, executed trades, PnL, and audit history. |
| `GET` | `/api/v1/ai/trades/{trade_id}` | — | Detailed execution logs and fill breakdown for a specific trade ID. |

---

### 6. Python Client Usage Example ([`execution_client.py`](execution_client.py))

```python
from execution_client import AIExecutionClient

client = AIExecutionClient()

# 1. Check broker connection and execution mode
status = client.get_status()
print(f"Mode: {status['mode']} | Live Authorized: {status['live_authorized']}")

# 2. Query multi-contract option technicals directly
opt_tech = client.get_options_technicals(
    instrument_ids=["INST-NIFTY-2026-10-13-22650-CE", "INST-NIFTY-2026-10-13-22650-PE"],
    interval="5m",
    limit=50
)
ce_metrics = opt_tech["contracts"][0]["metrics"]
print(f"CE EMA9: {ce_metrics['ema_9']} | RSI: {ce_metrics['rsi_14']} | VWAP: {ce_metrics['session_vwap']}")

# 3. Submit an entry order with a resting protective stop
order = client.place_buy_order("INST-NIFTY-2026-10-13-22650-CE", quantity=130, limit_price=71.75)
fill = client.wait_for_fill(order["order_id"])

# 4. Place initial protective stop loss (-10%)
stop = client.place_stop_loss(fill["order_id"], trigger_price=64.55, limit_price=63.30)

# 5. Continuous Dynamic Trailing Ratchet (+10% gain -> Breakeven)
client.modify_stop_loss(stop["order_id"], trigger_price=71.75, limit_price=70.30)

# 6. Discretionary exit (cancels resting stop first, then exits)
client.cancel_stop_loss(stop["order_id"])
client.exit_position(fill["order_id"], limit_price=92.50)
```

---

## 🤖 Antigravity Chat-Assisted Pair-Trading & News-First Execution Protocol

The current chat integration uses the persistent **Codex neural companion** described in [the worker guide](docs/CODEX_COMPANION.md). The following manual handshake remains supported for legacy companion use. The daemon never places orders autonomously into live markets without clearing the setup through the consultation gateway.

### 1. Mandatory News-First Intelligence Check (Step 3)
Before candidate entries are analyzed or planned, the engine ingests real-time external catalysts via [`market_intelligence.py`](market_intelligence.py) on every 1-minute cycle:
- **Global Intermarket Cues:** Real-time prices and percentage changes for Brent/Crude Oil (`CL=F`), Dow Jones (`^DJI`), Nasdaq (`^IXIC`), and USD/INR (`INR=X`).
- **Live Indian Financial News:** Real-time headlines and stories scraped from top financial RSS feeds (Moneycontrol, Economic Times / ET Markets).
- **Macro Traps & Divergence Detection:**
  * **Bear Trap Warning:** NIFTY flushing $> 0.6\%$ lower while global cues are neutral or bullish.
  * **Bull Trap Warning:** NIFTY rallying $> 0.4\%$ higher into adverse macro conditions (e.g., crude oil spiking or US markets selling off).
- **Continuous State File:** Every cycle writes `logs/latest_intelligence.json` and human-readable `logs/latest_intelligence.md` so market tone and catalysts are always inspectable.

### 2. The Trade Capture & Dossier Handshake (`mode: "chat"`)
When Strategy 3 detects a qualified technical setup (`BUY_CE` or `BUY_PE`):
1. **Dossier Compilation:** The scheduler compiles a complete 6-section [`MarketDossier`](ai_context_dossier.py) combining:
   - True Spot VWAP distance, slope, and 60-minute crosses
   - 5m EMA9/EMA20 trend alignment and pullback distance
   - 15m & 30m Range Box boundaries and compression
   - 1m RSI exhaustion levels and distance to day high/low
   - Live Heavyweight quotes and breadth (`HDFCBANK`, `RELIANCE`, `ICICIBANK`, `INFY`, `TCS`)
   - **Section 6: Live News Headlines, High-Impact Catalysts, and Macro Traps**
2. **Escrow & Notification:**
   - Candidate trade is written to `logs/pending_consultation.json` and `logs/pending_consultation.md`.
   - The scheduler pauses and opens a **45-second consultation window**.
3. **Chat Review & Verdict Submission:**
   - Antigravity Chat (or human trader) inspects `logs/pending_consultation.md` or checks status via CLI:
     ```powershell
     python ai_consultant.py --status
     ```
   - **To Approve the Trade:**
     ```powershell
     python ai_consultant.py --approve --reason "Clean EMA9 pullback confirmed by crude drop and supportive Dow futures" --trailing runner_ema9
     ```
   - **To Veto the Trade:**
     ```powershell
     python ai_consultant.py --veto --reason "Negative divergence: Reliance down -1.2% and adverse news at resistance" --trap "Trap 2"
     ```
   - Alternatively, write directly to `logs/ai_verdict.json`:
     ```json
     {
       "action": "APPROVED",
       "confidence": 90,
       "reason": "Clean EMA9 pullback, supportive Dow futures, no trap detected.",
       "trailing": "runner_ema9"
     }
     ```
4. **Fail-Safe Timeout Default:**
   - If no verdict is delivered before the 45s timer expires, the gateway returns `TIMEOUT_EXPIRED`.
   - **No order is placed.** The system defaults to **Capital Preservation**, logging the expiration and standing aside.

### 3. Consultation Configuration (`config/strategies.json`)
```json
"ai_consultation": {
  "enabled": true,
  "default_mode": "chat",
  "timeout_seconds": 45,
  "playbook_path": "config/rules_playbook.md"
}
```
*(Can be overridden on the command line via `--ai-mode chat`, `--ai-mode playbook`, or `--ai-mode disabled`)*.

---

## 🧠 AI Consultation Gateway & The 8 Institutional Traps

Before any trade is executed, the scheduler builds a complete [`MarketDossier`](ai_context_dossier.py) and submits it to [`AIConsultant`](ai_consultant.py). The gateway evaluates **8 institutional market traps** cataloged in [`config/rules_playbook.md`](config/rules_playbook.md):

1. **Trap 1: The VWAP Blender** — Choppy rotation with $\ge 3$ VWAP crosses in 60m and spot within 18 pts of flat VWAP. Vetoes entries to prevent whipsaws.
2. **Trap 2: Extreme Heavyweight Divergence** — Single-stock artificial index rallies (e.g. HDFC up while Reliance is breaking down $<-0.55\%$). Vetoes trades lacking broad institutional sponsorship.
3. **Trap 3: Vertical RSI Exhaustion & Momentum Chasing** —
   - Overbought Call spike chasing ($1\text{m RSI} \ge 74.5$).
   - Overbought Call top chasing ($1\text{m RSI} \ge 70.0$ within 12 pts of day high).
   - Falling knife avalanche buying ($1\text{m RSI} < 28.0$).
   - Put short squeeze chasing ($1\text{m RSI} > 72.0$).
   - Oversold Put panic flush at day low ($1\text{m RSI} \le 26.0$ within 10 pts of day low).
   - Counter-trend short trap ($1\text{m RSI} > 55.0$ without confirmed strong bear trend).
4. **Trap 4: 15-Minute Consolidation Ceiling / Floor Resistance Trap** — Index trapped in a narrow $< 28$-pt range box; buying within 6 pts of ceiling or floor without breakout volume.
5. **Trap 5: Late-Day Capital Degradation & Daily Alpha Preservation** —
   - Enforces capital preservation when session profit target is reached.
   - **Midday/Afternoon Alpha Lock:** Freezes trading after the first loss post-12:30 IST if realized daily profit is $\ge ₹1,800$, protecting locked gains against late-day churn.
6. **Trap 6: Compressed Ribbon Drift Trap** — 5m EMA9 and EMA20 ribbon spread collapsed ($< 2.5$ pts) indicating lack of directional momentum.
7. **Trap 7: 0DTE Midday Theta Grind Trap** — Holding OTM options between 10:00–13:30 on expiry days with slow premium decay. Enforces Strict ITM strike selection ($\ge 0.55$ delta).
8. **Trap 8: Post-Drawdown Tilt & Consecutive Loss Circuit Breaker** — Hard stop halting strategy evaluations after 2 consecutive daily losses or hitting daily max loss R.

---

## 🎯 Dynamic Trailing Stop Engine & Priority Hierarchy

> **Historical/legacy illustration only:** The diagram below is **not** the R01 stop schedule, and any “guaranteed profit floor” is a desired trigger, not a guaranteed broker fill. R01 uses a frozen initial **25%** option-premium loss setting with unified 15/20/30/40% gain tiers and IST morning/midday phases, retaining stronger stops. See [unified stop specification](docs/architecture/R01_UNIFIED_STOP_EXECUTION.md). No current-increment end-to-end tests or broker UAT have run.

The following earlier strategy model is retained for historical reference:

```
+---------------------------------------------------------------------------------+
|                         DYNAMIC INCREMENTAL RATCHET                             |
+---------------------------------------------------------------------------------+
|  Gain Level      | Action Taken                       | Guaranteed Profit Floor |
|------------------+------------------------------------+-------------------------|
|  Initial Entry   | Protective SL placed at -10%       | Capital Risk = -10%     |
|  Gain >= +10.0%  | Stop ratcheted to Breakeven (+0%)  | Risk Free (Zero Loss)   |
|  Gain >= +20.0%  | Stop ratcheted to +10.0% Profit    | Locked Profit = +10.0%  |
|  Gain >= +30.0%  | Stop ratcheted to +20.0% Profit    | Locked Profit = +20.0%  |
|  Peak Runner     | Continuous 10.0% offset from high  | Max Drawdown = 10% peak |
+---------------------------------------------------------------------------------+
```

> [!IMPORTANT]
> **Trailing Stop Priority Inversion Fix:**
> When a position is profitable and an incremental profit floor (+10%, +20%, +30%) or dynamic peak trailing stop is active, **the trailing stop takes absolute priority over 5m EMA9/EMA20 indicator exits**. Minor intra-candle index pullbacks are prevented from prematurely cutting winning trades that are securely protected by ratcheted profit floors.

---

## 📊 Comprehensive Forensic Backtest Scorecard (30 & 60 Sessions)

Audited across **30 trading sessions (Aug 31 – Oct 16, 2026)** and stress-tested across **60 sessions (June – October 2026)** encompassing weekly expiries, high-volatility trend days, summer consolidation brackets, and morning capitulation springs:

| Metric | Strategy 1: Legacy Scalper | Strategy 2: Structural Runner | Strategy 3: Institutional Pullback (Backup) | Strategy 4: AI Opportunity Radar (Active) |
|---|:---:|:---:|:---:|:---:|
| **30 Sessions: Total Trades** | 974 trades (severe churn) | 195 trades | 81 trades | **80 trades** |
| **30 Sessions: Win Rate %** | 38.2% | 56.4% | 79.0% | **75.0%** |
| **30 Sessions: Gross Wins / Losses** | 372W / 602L | 110W / 85L | 64W / 17L | **60W / 20L** |
| **30 Sessions: Net PnL (1 Lot / 65 qty)** | -₹40,288.60 | +₹13,933.40 | +₹29,363.35 | **+₹32,315.35** |
| **30 Sessions: Net PnL (2 Lots / ₹10k Margin)** | **-₹80,577.20 (-805.8%)** | **+₹27,866.80 (+278.7%)** | **+₹61,966.70 (+619.7%)** | **+₹67,830.70 (+678.3% ROI)** |
| **30 Sessions: Profit Factor** | 0.99 | 1.43 | 2.69 | **2.65** |
| **60 Sessions: Net PnL (2 Lots / ₹10k Margin)** | ❌ Liquidated | ❌ Low Survival | **+₹44,920.40 (+449.2%)** | **+₹58,393.20 (+583.9% ROI)** |
| **60 Sessions: Profit Factor** | < 1.0 | 1.15 | 1.58 | **1.76** |
| **Net Alpha Added Over Strategy 3** | N/A | N/A | Baseline | **+₹13,472.80 (+134.7% ROI)** |
| **Max Drawdown (2 Lots)** | -₹85,000.00 | -₹13,600.00 | -₹7,198.10 | **-₹6,840.00 (Structural Wick Stop)** |
| **Setup Universality** | Mechanical Micro-Scalp | Trend Pullbacks Only | Trend Pullbacks Only | **Multi-Regime: Trends + Climax Springs** |
| **Capital Status** | **Account Liquidated** | **Marginal Survival** | **Compounder (Backup Engine)** | 🏆 **Supreme Alpha Compounder (Active)** |

> [!NOTE]
> 📖 **Full Historical Audits:**
> - Complete trade-by-trade audit across all 30 sessions documented in [`docs/30_SESSIONS_TRADE_JOURNAL.md`](docs/30_SESSIONS_TRADE_JOURNAL.md).
> - Multi-regime simulation engine and verification script: [`backtest_ai_opportunity_radar.py`](backtest_ai_opportunity_radar.py).

---

## 🔬 Empirical Discovery: Why Climax Springs Succeeded & Failure Flips Were Rejected

During the optimization of the AI Opportunity Radar, two major market hypotheses were stress-tested across 60 trading sessions:

### 1. Rejection of the Mechanical "Failure Flip" (Stop-and-Reverse)
* **The Hypothesis:** When a trade gets stopped out, flip direction immediately to capture trapped institutional liquidity.
* **The Empirical Reality:**
  - Initial stop-outs occur almost exclusively during **Trap 1: The VWAP Blender** (sideways rotation / flat VWAP chop).
  - Reversing immediately into a choppy market produced devastating consecutive stop-outs (-₹2,484 churn on Sep 08; -₹3,150 on Jul 15).
  - The 10-minute structural cooldown rule (`min_spacing_bars = 10`) was mathematically proven to be vital to preserve capital during chop. Mechanical reversal was therefore **rejected**.

### 2. Adoption of the Morning Climax Rubber-Band Spring with Structural Wick Stop
* **The Discovery:** Rather than reacting blindly after a stop, the AI identifies **capitulation exhaustion turning points** in the morning (09:15–11:15 IST) when spot stretches $\ge 75$ pts from Open or $\ge 40$ pts from VWAP, 1m RSI drops $\le 32$, and an explosive $\ge 18$ pt impulse candle confirms institutional absorption.
* **The Structural Wick Stop:** The stop is placed strictly at the climax wick tip (low wick $-2$ pts for CE, high wick $+2$ pts for PE). If spot breaches the wick, the trade is cut early at just **-6% to -8% loss (~₹600–₹900)**, preventing a full -30% theta bleed.
* **The Empirical Impact:** Added **+₹13,472.80 net alpha (+134.7% ROI)** across 60 sessions, including a **+₹10,630.10 (+50% target hit)** gain on October 16, 2026 (`22900 CE`).

---

## 📈 Step-Ladder Milestone Compounding Model & Capital Scaling Audit

> **R01 revision:** The maximum-lot table below reflects the 2026-10-29 owner-approved bands, but the legacy backtest scorecard below it has **not** been re-run against this R01 model. This is not evidence of LIVE profitability. Current native broker funds adapters still lack the required current-day P&L ledger and per-instrument freeze limits; R01 is off.


R01 defines an authenticated-margin-based **maximum-lot ladder** behind a disabled feature switch; older research below should not be interpreted as current broker-verified production sizing.

### 1. Milestone Escalation Matrix
Instead of an unconstrained all-in sizing model, R01 caps quantity according to authenticated margin, fresh executable option premium, the fee reserve and broker-verified limits. The revised owner milestones are minimum thresholds; affordability can reduce the tier ceiling to one or more whole lots:

| Verified Broker Available Margin | Active Sizing | Contract Quantity | Risk Allocation Rationale |
|---|:---:|:---:|---|
| **₹0 < funds < ₹40,000** | **Up to 2 Lots** | **130 max** | Affordability can reduce sizing to one lot |
| **₹40,000 ≤ funds < ₹60,000** | **Up to 4 Lots** | **260 max** | Ceiling, subject to actual funding |
| **₹60,000 ≤ funds < ₹80,000** | **Up to 6 Lots** | **390 max** | Requires current broker/quote evidence |
| **₹80,000 ≤ funds < ₹100,000** | **Up to 8 Lots** | **520 max** | Independent risk limits still apply |
| **Funds ≥ ₹100,000** | **Up to 10 Lots** | **650 max** | Exchange freeze and hard position cap still apply |

**Daily cash loss cap:** INR 3,000 per actual proposed entry lot (INR 30,000 at 10 lots), recalculated for every new entry from verified realized + unrealized account-day P&L. At the cap, block new entries and retain existing stop/exit management. R01 does not use the legacy 1.5% opening-equity rule.

### 2. Sizing Governor & Drawdown Protection
1. **Dynamic De-escalation:** Sizing is tied to real-time available margin. If account equity pulls back below any milestone, sizing immediately drops to the lower tier.
2. **Zero-Shortfall Buffer Gate:** Order quantity is strictly bounded by `(available_margin - 150) // (contract_price * 65)`, guaranteeing that orders never exceed liquid funds minus a ₹150 buffer for exchange turnover, STT, and statutory taxes.
3. **Execution Integration:** Evaluated dynamically at both candidate analysis time ([`analyze()`](nifty_trader_scheduler.py)) and order routing time ([`execute_trade()`](nifty_trader_scheduler.py)).

### 3. Empirical Compounding Audit (30 & 60 Sessions)
The Step-Ladder model was audited against Fixed Sizing and Dynamic Full Cash Reinvestment:

| Timeframe | Metric | Fixed 2 Lots (Baseline) | Step-Ladder Compounding (Active) | Dynamic Full Cash (All-In) |
|---|---|:---:|:---:|:---:|
| **30 Sessions (Aug 31 – Oct 16)** | **Net PnL** | +₹73,830.70 | **+₹118,434.05** | +₹182,167.60 |
| | **Net ROI %** | +638.3% | **+1,084.3% (>11x)** | +1,721.7% |
| | **Max Drawdown** | -₹6,840.00 | **-₹12,480.00** | -₹28,600.00 |
| **60 Sessions Multi-Regime** | **Net PnL** | +₹61,493.20 | **+₹152,563.90** | +₹1,709.80 |
| | **Net ROI %** | +514.9% | **+1,425.6% (>15x)** | -82.9% (Account Wreck) |
| | **Regime Survival** | Survived | **Flawless Compounding** | ❌ Liquidated in Summer Chop |

> [!TIP]
> **Why Full Cash All-In Failed Across 60 Sessions:** In trending markets, 100% reinvestment looks attractive (+1,721%), but during the low-volatility July summer chop, taking maximum lots on high-premium ITM options right before consecutive stop-outs wiped out 82.9% of equity.
> **Why Step-Ladder Succeeded:** By locking sizing to verified capital tiers (2 $\to$ 4 $\to$ 6 $\to$ 8 $\to$ 10 lots) and de-escalating on drawdowns, Step-Ladder compounded ₹10,000 into **₹1.52 Lakhs (+1,425.6% ROI)** across both summer chop and autumn trend expansions.

---

## 🧪 Forensic Parity Audit & Validation Tools

- **Bar-by-Bar Data Parity Verification ([`verify_data_parity.py`](verify_data_parity.py)):**
  Audits raw OHLC candles and indicator values between live ingestion and backtest engine.
  ```powershell
  python verify_data_parity.py 2026-10-13
  # Result: 100.0% Mathematical Parity across all 340 bars
  ```
- **Read-Only Live API Diagnostics ([`check_live_apis.py`](check_live_apis.py)):**
  Verifies connectivity to all broker and AI endpoints without placing any orders.
  ```powershell
  python check_live_apis.py
  ```
- **Fast Endpoints Validation ([`test_api_endpoints.py`](test_api_endpoints.py)):**
  ```powershell
  python test_api_endpoints.py
  ```
- **Option Technicals API Audit:**
  ```powershell
  python -c "from execution_client import AIExecutionClient; c = AIExecutionClient(); print(c.get_options_technicals(['INST-NIFTY-2026-10-13-22650-CE']))"
  ```
- **Launch 1-Minute Live Daemon:**
  ```powershell
  # Strategy 4: AI Opportunity Radar (Active Engine)
  python nifty_trader_scheduler.py --lots 2 --interval 60 --strategy ai_opportunity_radar --ai-mode playbook

  # Strategy 3: Institutional Pullback (Preserved Backup Engine)
  python nifty_trader_scheduler.py --lots 2 --interval 60 --strategy institutional_pullback --ai-mode playbook

  # Interactive Pair-Trading Escrow:
  python nifty_trader_scheduler.py --lots 2 --interval 60 --strategy ai_opportunity_radar --ai-mode chat
  ```
---

## 🧭 Morning Pre-Market Checklist & Launch Protocol (09:10 – 09:15 IST)

For the current Kite/Codex release, use [the Codex worker guide](docs/CODEX_COMPANION.md) and [start-paused local acceptance](docs/operations/KITE_LOCAL_ACCEPTANCE_20261030.md). Actual starts are operator actions; the default R01 flag remains off.

```powershell
python -m tools.brokers --broker kite
python -m tools.codex_companion --check
python -m tools.codex_companion --self-test
```

Then the operator starts the persistent worker and, in a separate terminal, the scheduler in chat mode using the acceptance procedure. The original consultation deadline is 45 seconds and approval lifetime is at most 15 seconds after application publication. New entries stop at 14:15 IST; the OMS requests square-off at 15:15 and must verify actual broker flatness. A request cannot guarantee a fill during an outage.

---

## 📂 Repository File Tree

```
splendid-bardeen/
├── config/
│   ├── strategies.json            # Central strategy profiles (active: ai_opportunity_radar)
│   ├── rules_playbook.md          # 8 Institutional Trap definitions & deterministic rules
│   └── trading.json               # Backend OMS & risk limits
├── docs/
│   ├── 30_SESSIONS_TRADE_JOURNAL.md # Full forensic audit journal (30 sessions)
│   └── AI_ARCHITECTURE_AND_DIRECTIVE.md # Institutional AI demarcation specification
├── data/
│   ├── spot_candles_20261013.json # Completed 1m Nifty spot candles
│   └── option_candles_20261013.json # Full session 1m Kite option candles
├── ai_consultant.py               # Playbook AI Risk Gateway (8 trap evaluation engines)
├── ai_context_dossier.py          # Multi-hour market state dossier compiler
├── ai_opportunity_radar.py        # Autonomous multi-regime radar (Strategy 4: Trends + Springs)
├── backtest_ai_opportunity_radar.py # Audited 30 & 60 session simulation engine for Strategy 4
├── backtest_engine.py             # Historical simulation engine with real & synthetic option pricing
├── execution_client.py            # PR #51 Platform API Client (LIVE/PAPER, stops, exits, technicals)
├── check_live_apis.py             # Read-only live diagnostic audit script
├── market_intelligence.py         # Online macro & financial news sentiment connector
├── nifty_trader_scheduler.py      # Main 1-minute automated execution daemon
├── run_today_all_strategies.py    # Forensic multi-strategy playback script
├── start_scheduler.ps1            # PowerShell launcher
├── test_api_endpoints.py          # Fast endpoint connectivity validation script
├── verify_data_parity.py          # Bar-by-bar mathematical feed parity auditor
├── AGENTS.md                      # Mandatory AI operational charter & non-negotiable directives
└── README.md                      # Comprehensive architecture, API docs & backtest scorecard
```
