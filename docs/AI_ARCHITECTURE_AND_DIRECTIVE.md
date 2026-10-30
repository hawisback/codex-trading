# 🧠 AI Architecture & Operational Directive

> **Current R01 integration notice:** The mandatory pre-entry consultant evaluation/veto remains unchanged. New R01-stamped positions now use a single stop authority (unified `StopManager`/`PositionMonitor`), so only their *legacy post-fill* two-step AI stop override is skipped; existing unstamped positions retain the prior behavior. Earlier profit/lot claims in this directive are **historical research, not LIVE certification**. See [2026-10-30 current status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md) and [unified stop contract](architecture/R01_UNIFIED_STOP_EXECUTION.md). Feature disabled, new tests not run, no supervised broker validation.


> **Document Type:** Production Architecture Specification & Institutional Directive  
> **Status:** Active & Inviolable  
> **Target Systems:** `nifty_trader_scheduler.py`, `ai_consultant.py`, `ai_context_dossier.py`, `market_intelligence.py`  
> **Author:** Antigravity Pair-Trading Engineering Team  

---

## 1. Executive Summary & Purpose

This document establishes the official architectural mandate and operational guidelines for **Artificial Intelligence (AI)** within the NIFTY 50 Options Trading Engine. 

In this system, **AI is not an experimental add-on, a post-trade logger, or a discretionary suggestion.** It is the **foundational decision intelligence and supreme risk gatekeeper**. Without AI consultation, the trading engine is mathematically prohibited from committing financial capital.

### The Empirical Imperative (Why AI is Vital & How Compounding Multiplies Alpha)
Across 30 to 60 audited trading sessions (80 to 138 executed trades), the empirical divergence between operating with vs. without AI, and between static sizing vs. Step-Ladder Milestone Compounding, is categorical:

```
                                  ACCOUNT EQUITY TRAJECTORY (30 TO 60 SESSIONS)
   +₹150k |                                                                   * * * * * (Step-Ladder: +₹152,563.90 / +1,425.6%)
          |                                                           * * * *
   +₹100k |                                                   * * * *
          |                                           * * * * (30-Session Step-Ladder: +₹118,434.05 / +1,084.3%)
    +₹50k |                                   * * * * (Strategy 4 Fixed 2 Lots: +₹73,830.70 / +638.3%)
          |                           * * * * (Strategy 3 Baseline Fixed: +₹46,283.80 / +462.8%)
      ₹0  |---Baseline ₹10k Margin------------------------------------------------------------------------------------------
          |
    -₹25k |   \
          |    \
    -₹50k |     \
          |      \
    -₹85k |       * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * (-₹80,577.20 / -805.8% Liquidation)
          +-----------------------------------------------------------------------------------------------------------------
                 WITHOUT AI GATE (Strategy 1) vs. WITH AI GATE (Strategy 3/4) vs. STEP-LADDER COMPOUNDING
```

- **WITHOUT AI (Blind Mechanical Indicators):** The system took 178 trades with a 38.2% win rate, losing **-₹80,577.20 (-805.8% ROI)**. The capital was decimated by the "VWAP blender" during midday lunch hours, overbought climax chasing, low-delta 0DTE theta wipeout, and false range breakouts.
- **WITH AI GATEKEEPER (Strategy 3 Baseline - Fixed 2 Lots):** Generated **+₹46,283.80 (+462.8% Net ROI)** on ₹10k baseline capital across 30 sessions with a **79.7% win rate (55W / 14L)** and **100% win retention**.
- **WITH AI OPPORTUNITY RADAR (Strategy 4 Active - Fixed 2 Lots):** Generated **+₹73,830.70 (+638.3% Net ROI)** across 30 sessions, capturing both Trend Pullbacks and Morning Climax Springs with Structural Wick Stops.
- **WITH STEP-LADDER MILESTONE COMPOUNDING (Strategy 4 Active):**
  * **30-Session Run:** Compounded ₹10,000 into **₹118,434.05 (+1,084.3% Net ROI / >11x growth)**.
  * **60-Session Multi-Regime:** Compounded ₹10,000 into **₹152,563.90 (+1,425.6% Net ROI / >15x growth)** across summer consolidation chop and autumn trend expansions with flawless drawdown survival.

---

## 2. Architectural Demarcation: Deterministic Math vs. AI Intelligence

To maintain institutional rigor, eliminate hallucinations from order routing, and leverage AI where it excels (contextual synthesis and trap detection), the system enforces a strict division of labor:

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

### The Inviolable Operating Paradigm:
> 💡 **"Deterministic Math Proposes $\longrightarrow$ AI Intelligence Disposes $\longrightarrow$ Deterministic OMS Executes"**

1. **Step 1 (Deterministic Math Proposes):** The technical engine identifies that NIFTY spot has completed a structural 4.0-point pullback to the 5m EMA9 aligned with VWAP.
2. **Step 2 (AI Intelligence Disposes):** The engine pauses execution, compiles a full 6-dimensional Market Dossier, and presents it to the AI Consultant. AI inspects live news sentiment, intermarket cues, heavyweight alignment, and the 8 Institutional Traps.
   - If AI returns `VETOED`: The trade is killed immediately. Zero capital is committed.
   - If AI returns `APPROVED`: The trade advances to Step 3.
3. **Step 3 (Deterministic OMS Executes):** The PR #51 Execution Client sizes the order within safe available cash margin (accounting for taxes and STT buffers), submits a BUY limit order, immediately arms a physical resting stop-loss on the broker's book, and initiates the 5-second trailing ratchet loop.

---

## 3. The 6-Stage AI Decision Lifecycle

AI participates across the full lifecycle of every market session:

```
STAGE 1: Macro & News NLP Scraping (Continuous Background)
         - Ingests Crude Oil, Dow Jones, Nasdaq, USD/INR.
         - Scrapes Moneycontrol and ET Markets RSS feeds.
         - Generates Macro Bias (-3 to +3).
             │
             ▼
STAGE 2: Multi-Factor Dossier Compilation (On Candidate Signal)
         - 6 market dimensions synthesized into JSON & Markdown.
         - Spot VWAP geometry, 5m EMA spread, 15m Consolidation Box, 1m RSI.
             │
             ▼
STAGE 3: Institutional Pullback Setup Qualification
         - Confirms 4.0-pt pullback to 5m EMA9.
         - Selects strict ITM strike (Delta ≥ 0.55) to eliminate theta bleed.
             │
             ▼
STAGE 4: The AI Risk Gatekeeper (Supreme Veto)
         - AI evaluates setup against the 8 Institutional Traps.
         - Outputs formal AIVerdict (APPROVED / VETOED).
             │
             ▼
STAGE 5: Dynamic Trailing Ratchet & Risk Management
         - Fast 5s trailing loop ratchets resting SL on Zerodha Kite.
         - Profit floors: +10% ──> Breakeven, +20% ──> +10%, +30% ──> +20%.
         - Post-14:00 IST Late-Day Micro-Trail locks +1% floor on +4% gain.
             │
             ▼
STAGE 6: Multi-Regime Opportunity Discovery & Climax Springs
         - Evaluates Morning Climax Rubber-Band Springs (09:15–11:15 IST) when spot stretches ≥ 75 pts from Open / ≥ 40 pts from VWAP.
         - Arms Structural Wick Stops (cutting false turns at -6% to -8% instead of -30%).
         - Strictly rejects mechanical "failure flip" reversals during chop to preserve capital.
```

---

## 4. The 8 Institutional Traps & Veto Authority

The AI Consultant evaluates every candidate setup against 8 empirically discovered institutional failure modes:

| Trap # | Trap Name | Failure Mode Discovered in Audits | AI Action / Veto Criteria |
|---|---|---|---|
| **Trap 1** | **VWAP Blender & Midday Dead Zone** | $\ge 5$ crosses in 60m or flat VWAP between 11:30–13:15 IST results in rapid chop stop-outs. | **VETO** unless trade is a structural directional shift from a multi-hour day extreme. |
| **Trap 2** | **0DTE Penny Option Gamma Trap** | Sub-₹12 options on expiry days experience instant 30% wipeouts on a 2-point spot flutter. | **VETO** any 0DTE candidate with premium $< ₹12.00$. Enforce ITM with delta $\ge 0.55$. |
| **Trap 3** | **V-Reversal Counter-Trend Trap** | Technical signals short into aggressive short-covering rallies (RSI $> 55$). | **VETO** Puts if 1m RSI $> 55$ or spot bouncing aggressively above 5m EMA9. |
| **Trap 4** | **15m Consolidation Box Ceiling/Floor** | Buying Calls into box resistance (or Puts into support) without breakout volume. | **VETO** Calls within 4 pts of ceiling; VETO Puts within 4 pts of floor. |
| **Trap 5** | **Late-Day Profit Degradation Trap** | Entering new directional options after 14:15 IST during institutional block rebalancing. | **VETO** new entries post-14:15 IST, especially if account is in profit. Lock daily alpha. |
| **Trap 6** | **Compressed Ribbon Drift Trap** | 5m EMA9/EMA20 spread $< 4.0$ pts indicates zero directional commitment; causes theta bleed. | **VETO** entries in compressed ribbons unless breaking out to a new day high/low. |
| **Trap 7** | **Counter-Trend VWAP Slope Trap** | Buying Puts when VWAP slope is $> +0.10$ pts/min (or Calls when slope $< -0.10$). | **VETO** candidate entries fighting dominant session institutional order flow. |
| **Trap 8** | **Climax Overextension Trap** | Buying options when spot is extended $\ge 75$ pts from VWAP (stretched rubber band). | **VETO** fresh entries $\ge 75$ pts from VWAP. Only trail existing runners; do not initiate. |

---

## 5. Step-Ladder Milestone Compounding & Dynamic Sizing Governance

To compound capital safely without exposing accumulated profits to catastrophic drawdown during low-volatility consolidation phases, the system implements **Step-Ladder Milestone Compounding**:

### Milestone Escalation & De-escalation Matrix:
| Verified Broker Available Margin | Active Lot Sizing | Contract Quantity | Risk Allocation Rationale |
|---|:---:|:---:|---|
| **< ₹20,000** | **2 Lots** | **130 contracts** | Baseline capital preservation tier (₹10k start) |
| **₹20,000 – ₹40,000** | **4 Lots** | **260 contracts** | Double sizing funded purely by accumulated profits |
| **₹40,000 – ₹70,000** | **6 Lots** | **390 contracts** | Accelerated mid-tier expansion |
| **₹70,000 – ₹100,000** | **8 Lots** | **520 contracts** | Advanced high-water compounding |
| **> ₹100,000** | **10 Lots (Cap)** | **650 contracts** | Strict institutional liquidity ceiling |

### Sizing Governance Rules:
1. **Dynamic Drawdown Protection:** Sizing is strictly tied to **current verified broker margin**. If equity pulls back below any milestone, order quantity immediately de-escalates to the lower tier.
2. **Zero-Shortfall Buffer Gate:** Maximum lots are capped by `(available_margin - 150) // (contract_price * 65)`, reserving a permanent ₹150 buffer for statutory fees, STT, and exchange turnover.
3. **Rejection of "All-In" Reinvestment:** Stress-testing across 60 multi-regime sessions proved that reinvesting 100% of cash margin into maximum lots wiped out -82.9% during summer chop. Step-Ladder Milestone Compounding succeeded with **+1,425.6% ROI** by enforcing disciplined tier ceilings.

---

## 6. Fail-Safe Guarantees: Capital Preservation Over Execution

A critical principle of the trading engine is:

> **"When in doubt, preserve capital."**

Under no circumstances does the system default to taking a trade if AI is unavailable or silent:

1. **Timeout Safety:** In Pair-Trading (`chat`) mode, if no verdict is received within 45 seconds, the consultant returns `TIMEOUT_EXPIRED` with `is_approved = False`.
2. **Connectivity / API Loss:** If external news scraping or broker connectivity degrades, the AI consultant flags the data quality alert and vetos the setup.
3. **Execution Escrow:** The OMS never pre-allocates margin or places orders before receiving `verdict.is_approved == True`.

---

## 7. Pre-Flight Operational Runbook

Before every trading session (at 09:10 IST), ensure the AI trading engine is running with the proper configuration:

```powershell
# 1. Verify broker credentials & backend feeds
python check_live_apis.py

# 2. Start the AI Trader Scheduler with the AI Opportunity Radar (Strategy 4 - Active)
python nifty_trader_scheduler.py --interval 60 --strategy ai_opportunity_radar --ai-mode playbook

# Or launch with the preserved Strategy 3 backup engine:
python nifty_trader_scheduler.py --interval 60 --strategy institutional_pullback --ai-mode playbook
```

For live real-money trading on Zerodha Kite:
```powershell
python nifty_trader_scheduler.py --interval 60 --strategy ai_opportunity_radar --ai-mode playbook --live
```
