# 🤖 AGENT OPERATIONAL DIRECTIVE & SYSTEM CHARTER

> **CRITICAL INSTRUCTION FOR ALL AI CODING ASSISTANTS & AUTOMATED AGENTS:**
> This repository contains a production algorithmic options trading engine for NIFTY 50 Index Options.
> Every agent interacting with this codebase must read, acknowledge, and strictly enforce the operational rules and architectural demarcation documented below.

---

## ⚠️ MANDATORY TERMINOLOGY DEFINITION: "AI" vs. "DETERMINISTIC RULES"

> [!IMPORTANT]
> **Whenever the USER asks "Are we using AI?" or asks about AI status, the definition is STRICT and ABSOLUTE:**
> 1. **"AI" = ONLY AND STRICTLY the Antigravity AI Code Companion (Neural LLM):**
>    - Active ONLY in `--ai-mode chat` (interactive pair-trading where the Antigravity AI assistant evaluates candidate dossiers in real time).
>    - If the engine is running in `--ai-mode playbook` or `--ai-mode rules`, the answer to *"Are we using AI?"* is **STRICTLY "NO"**.
> 2. **"Deterministic Rules & Risk Guardrails" = Hardcoded Code Heuristics:**
>    - The 8 cataloged institutional traps, EMA ribbon checks, VWAP blender filters, and RSI cutoffs in `ai_consultant.py` and [`config/rules_playbook.md`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/config/rules_playbook.md) are **100% deterministic, rule-based algorithmic filters**.
>    - They contain **ZERO machine learning, ZERO neural networks, and ZERO artificial intelligence**.
>    - Confusing deterministic rules with AI previously caused severe financial loss (₹40,000 drawdown). Any agent that conflates deterministic rules with AI violates this charter.

---

## 🏛️ Rule #1: Risk Guardrails & Gatekeeper are Core, Vital, and Non-Negotiable

**Trade evaluation is NOT an optional plugin, secondary filter, or cosmetic enhancement. It is the non-negotiable risk gatekeeper of every trade decision.**

### The Empirical Contrast (Audited across 30 to 60 Trading Sessions / 80–138 Trades):
| Engine Configuration | Sizing Model | Total Trades | Win Rate % | Net PnL (₹10k Start Capital) | Net ROI % | Regime Survival |
|---|---|:---:|:---:|:---:|:---:|---|
| **Without Guardrails (Mechanical Scalper)** | Fixed 2 Lots | 178 | 38.2% | **-₹80,577.20** | **-805.8%** | ❌ **Account Liquidation** (Churn, VWAP chop, climax traps) |
| **Strategy 3 Baseline (Institutional Pullback + Rules)** | Fixed 2 Lots | 69 | 79.7% | **+₹46,283.80** | **+462.8%** | ✅ **Flawless Compounding** (100% win retention, 55W / 14L) |
| **Strategy 4 Active (Radar + Rules Playbook)** | Fixed 2 Lots | 80 | 75.0% | **+₹73,830.70** | **+638.3%** | 🏆 **Alpha Discovery** (Climax Springs + Trend Pullbacks) |
| **Strategy 4 Active (30-Day Step-Ladder + Rules)** | **Step-Ladder (2-10 Lots)** | **80** | **75.0%** | **+₹118,434.05** | **+1,084.3%** | 🚀 **Milestone Compounding** (>11x capital growth) |
| **Strategy 4 Active (60-Day Multi-Regime + Rules)** | **Step-Ladder (2-10 Lots)** | **138** | **71.7%** | **+₹152,563.90** | **+1,425.6%** | 🛡️ **All-Weather Master** (Summer chop + Autumn trend) |
| **Strategy 4 Active (Antigravity AI Companion - Chat Mode)** | **Step-Ladder (2-10 Lots)** | **6 Trades** | **83.3%** | **+₹25,346.60 (3 Days)** | **+253.5%** | 🧠 **Deep Alpha** (Vetoes dead zones, catches runners) |

### Non-Negotiable Directives:
1. **Never Bypass the Risk Gatekeeper:** Under no circumstances may an agent disable, mock, or bypass `self.ai_consultant.evaluate(dossier)` in live or backtest runs.
2. **Supreme Veto Power:** If the consultant returns `VETOED` or detects any institutional trap, **the order MUST NOT BE PLACED**. The engine stands aside in cash.
3. **Fail-Safe to Capital Preservation:** If evaluation times out (45s), loses connectivity, or produces an error, the engine defaults unconditionally to **CASH PRESERVATION (0 trades placed)**.

---

## 🔒 Rule #2: Strict Workspace Isolation

* **Permitted Directory:** Strictly work ONLY inside `c:\Users\hawis\Documents\antigravity\splendid-bardeen`.
* **Prohibited Directories:** **NEVER** edit, create, or touch files in `icici-breeze-api-trading` or any directory outside `splendid-bardeen`.

---

## 💰 Rule #3: Account Constraints, Step-Ladder Compounding & Sizing

* **Live Capital Authority:** Authenticated broker-verified **available margin**, not an assumed starting equity; ₹10,000 may appear only in explicitly historical/research examples.
* **Step-Ladder Milestone Compounding Model:**
  The engine scales lot sizing dynamically strictly upon crossing verified broker margin milestones:
  | Verified Broker Available Margin | Active Sizing | Contract Quantity | Risk Rationale |
  |---|:---:|:---:|---|
  | **0 < available margin <= ₹20,000** | **2 Lots MAX** | **130 contracts** | Strict inclusive first upper bound |
  | **₹20,000 < margin <= ₹40,000** | **4 Lots MAX** | **260 contracts** | Global capital tier |
  | **₹40,000 < margin <= ₹60,000** | **6 Lots MAX** | **390 contracts** | Global capital tier |
  | **₹60,000 < margin <= ₹80,000** | **8 Lots MAX** | **520 contracts** | Global capital tier |
  | **> ₹80,000** | **10 Lots MAX** | **650 contracts** | Absolute global ceiling, including above ₹100,000 |
* **Dynamic Tier Recalculation:** Each new entry re-evaluates broker available margin against the global ladder. A reduced broker margin reduces the permitted tier; this does not imply existing positions are resized automatically.
* **Zero-Shortfall Purchasing Power Buffer:** The lot ceiling is further constrained by whole lots affordable from `(broker_available_margin - 150) / (approved_option_limit_price * current_lot_size)`. Underlying NIFTY spot selects strikes, not option cost. Invalid/missing funds or option price blocks new entries; broker account, AI veto and OMS gates still apply.
* **Order Cap:** Maximum **1 concurrent open position** at any time.
* **Overnight Rule:** **STRICTLY ZERO POSITIONS OVERNIGHT**. All intraday positions must be squared off by 15:15 IST.
* **Zero Cost Architecture:** Operates with **zero paid API fees** (uses local broker sessions on Kite/Breeze and free web RSS/market ingestion).

---

## ⚖️ Rule #4: Architectural Demarcation

The repository maintains an institutional division of responsibilities:
```
+---------------------------------------------------------------------------------------------------+
|  DETERMINISTIC CORE (Muscles)      |  DETERMINISTIC RULES (Filters)     |  ANTIGRAVITY AI (Brain) |
|  - 100% Rule-Based Math & OMS      |  - 8 Hardcoded Institutional Traps |  - True Neural LLM      |
|------------------------------------+------------------------------------+-------------------------|
|  1. 1m to 5m Candle Resampling     |  1. VWAP Blender / Dead Zone Veto  |  1. Live Macro NLP      |
|  2. True Spot Session VWAP         |  2. 0DTE Penny Option Filter       |  2. Global Cues Syn     |
|  3. 0.05 Tick Rounding on Orders   |  3. V-Reversal RSI Cutoffs         |  3. 6D Dossier Syn      |
|  4. Broker OMS Limit & Stop Orders |  4. Range Box Resistance Veto      |  4. Dynamic Judgement   |
|  5. 5-Second Dynamic Trailing      |  5. Climax Distance Cap (75 pts)   |  5. Interactive Chat    |
+---------------------------------------------------------------------------------------------------+
```

> **The Operating Principle:**
> *"Deterministic Math Proposes $\longrightarrow$ Deterministic Rules Filter $\longrightarrow$ Antigravity AI Disposes (Chat) $\longrightarrow$ Deterministic OMS Executes"*

---

## 📋 Rule #5: The 8 Institutional Traps to Enforce

Every candidate trade must pass the 8 institutional traps defined in [`config/rules_playbook.md`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/config/rules_playbook.md):
1. **Trap 1: The VWAP Blender & Midday Dead Zone** [REMOVED - Deprecated per user directive & audit to unlock midday alpha].
2. **Trap 2: The 0DTE Penny Option Gamma Trap** (Veto 0DTE options $< ₹12.0$).
3. **Trap 3: The V-Reversal Counter-Trend Trap** (Veto Puts if RSI $> 55$ or rapid bounce above EMA9).
4. **Trap 4: The 15-Minute Consolidation Ceiling Trap** (Veto Calls within 4 pts of box resistance).
5. **Trap 5: The Late-Day Profit Degradation Trap** (Veto new directional entries post-14:15 IST).
6. **Trap 6: The Compressed Ribbon Drift Trap** (Veto if $|EMA9 - EMA20| < 4.0$ pts without breakout).
7. **Trap 7: Counter-Trend VWAP Slope Trap** (Veto entries fighting dominant session flow).
8. **Trap 8: Climax Overextension Trap** (Veto entries extended $\ge 75$ pts from VWAP).

---

## 🚀 Morning Pre-Flight Command

### 1. Deterministic Rules Mode (Algorithmic Heuristics, Zero AI):
To launch the live engine on **Zerodha Kite** with in-process market data (Strategy 5: Path A 2m MACD Momentum):
```powershell
python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode rules --wait-until-market-open
```
*(Note: `--ai-mode playbook` remains supported as an alias for `--ai-mode rules`)*.

To launch on **ICICI Breeze**:
```powershell
python nifty_trader_scheduler.py --broker breeze --market-data-broker breeze --live --strategy macd_momentum --ai-mode rules --wait-until-market-open
```

### 2. Antigravity AI Companion Mode (True Neural AI Pair-Trading - Path A Recommended):
To launch with interactive Antigravity AI Chat Pair-Trading directly in the IDE:
1. Arm the AI Watcher daemon:
   ```powershell
   python tools/watch_consultation.py
   ```
2. Launch the live scheduler:
   ```powershell
   python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode chat --wait-until-market-open
   ```
   *(For full architecture, purchasing power math, and reactive wakeup protocol, see [`docs/AI_COMPANION_PAIR_TRADING.md`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/docs/AI_COMPANION_PAIR_TRADING.md))*.

### 3. Account & Data Verification (Read-Only Pre-Flight):
To run read-only pre-flight account & data verification before market open:
```powershell
python -m tools.brokers --broker both
python -m tools.verify_market_data --broker kite --after-hours
```
