# 🤖 AGENT OPERATIONAL DIRECTIVE & SYSTEM CHARTER

> **CRITICAL INSTRUCTION FOR ALL AI CODING ASSISTANTS & AUTOMATED AGENTS:**
> This repository contains a production algorithmic options trading engine for NIFTY 50 Index Options.
> Every agent interacting with this codebase must read, acknowledge, and strictly enforce the operational rules and architectural demarcation documented below.

---

## ⚠️ MANDATORY TERMINOLOGY DEFINITION: "AI" vs. "DETERMINISTIC RULES"

> [!IMPORTANT]
> **Whenever the USER asks "Are we using AI?" or asks about AI status, the definition is STRICT and ABSOLUTE:**
> 1. **"AI" = an explicitly invoked neural companion (Codex in ChatGPT IDE, or the legacy Antigravity companion):**
>    - Active ONLY in `--ai-mode chat` when the neural companion actually evaluates the current dossier. A running scheduler or idle watcher alone does not prove AI inference occurred.
>    - The persistent Codex worker supplies structured judgment only. Application helpers validate identity/deadline and publish verdicts atomically; the deterministic OMS owns broker execution.
>    - If the engine is running in `--ai-mode playbook` or `--ai-mode rules`, the answer to *"Are we using AI?"* is **STRICTLY "NO"**.
> 2. **"Deterministic Rules & Risk Guardrails" = Hardcoded Code Heuristics:**
>    - The 8 cataloged institutional traps, EMA ribbon checks, VWAP blender filters, and RSI cutoffs in `ai_consultant.py` and [`config/rules_playbook.md`](config/rules_playbook.md) are **100% deterministic, rule-based algorithmic filters**.
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

* **Permitted Directory:** Strictly work ONLY inside `C:\Users\hridesh.gupta\vscode-repo\trading\chatgpt-ai-trading`.
* **Prohibited Directories:** **NEVER** edit, create, or touch files in `icici-breeze-api-trading` or another project checkout. Installed tooling and its authentication remain environment-managed.

---

## 💰 Rule #3: Account Constraints, Step-Ladder Compounding & Sizing

> **Current policy (owner update, 2026-10-30):** R01 uses up to 2 lots below INR 40k, 4 at 40k, 6 at 60k, 8 at 80k and 10 at 100k, always limited by actual option-premium affordability and the INR 150 reserve. Daily realized + unrealized loss blocks NEW entries at INR 3,000 times each proposed entry's actual lot count; existing stop management continues. Kite is the current release target; Breeze is deferred. R01 is configured on with `auto_trade_enabled=false` for a paused operator acceptance start; actual broker acceptance remains pending. See [canonical status](docs/architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md).


* **Baseline Capital:** **₹10,000 Margin**.
* **Step-Ladder Milestone Compounding Model:**
  The engine scales lot sizing dynamically strictly upon crossing verified broker margin milestones:
  | Verified Broker Available Margin | Active Sizing | Contract Quantity | Risk Rationale |
  |---|:---:|:---:|---|
  | **Positive funds below ₹40,000** | **Up to 2 Lots** | **130 max** | One lot if only one is affordable |
  | **₹40,000 to below ₹60,000** | **Up to 4 Lots** | **260 max** | Broker funding and exchange limit still apply |
  | **₹60,000 to below ₹80,000** | **Up to 6 Lots** | **390 max** | Broker funding and exchange limit still apply |
  | **₹80,000 to below ₹100,000** | **Up to 8 Lots** | **520 max** | Broker funding and exchange limit still apply |
  | **₹100,000 and above** | **Up to 10 Lots** | **650 max** | Hard position cap and exchange limit still apply |
* **Dynamic Drawdown De-escalation:** If account equity pulls back below any milestone threshold during adverse conditions, lot sizing **instantly drops** to the lower bracket to protect accumulated capital.
* **Zero-Shortfall Purchasing Power Buffer:** Sizing is hard-capped by `(available_margin - 150) // (contract_price * 65)`. Orders never exceed verified liquid funds minus a ₹150 buffer for exchange fees and STT.
* **Order Cap:** Maximum **1 concurrent open position** at any time.
* **Current initial protection:** **25%** for MACD and the approved R01 unified policy. The request's `authoritative_risk_policy` and existing position's frozen policy are binding. Legacy post-fill refinement is allowed only inside its frozen band and may never loosen protection; R01 positions retain the unified stop authority.
* **Companion deadlines:** 45-second consultation window, including startup/reasoning/validation/handoff. Entry approval lifetime is at most 15 seconds after application submission and never beyond the consultation deadline. Errors and late/malformed replies preserve cash; stop-consultation failures retain existing protection.
* **Overnight Rule:** Target **zero positions overnight** with a mandatory 15:15 IST square-off request. Broker outages/failed fills can prevent verified flatness; preserve the exposure incident and reconcile.
* **Zero Cost Architecture:** Operates with **zero paid API fees** (uses local broker sessions on Kite/Breeze and free web RSS/market ingestion).

---

## ⚖️ Rule #4: Architectural Demarcation

The repository maintains an institutional division of responsibilities:
```
+---------------------------------------------------------------------------------------------------+
|  DETERMINISTIC CORE (Muscles)      |  DETERMINISTIC RULES (Filters)     |  NEURAL COMPANION (Brain) |
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
> *"Deterministic Math Proposes $\longrightarrow$ Deterministic Rules Filter $\longrightarrow$ Neural Companion Judges (Chat) $\longrightarrow$ Deterministic OMS Executes"*

---

## 📋 Rule #5: The 8 Institutional Traps to Enforce

Every candidate trade must pass the 8 institutional traps defined in [`config/rules_playbook.md`](config/rules_playbook.md):
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

> **Do not use the historical `--live` examples below as authorization to trade.** Broker day-P&L/freeze limits, current instrument master, offline suites, OMS recovery and supervised UAT remain release blockers. `r01_policy.enabled=true` with `auto_trade_enabled=false` prepares a paused start; the branch is not merged/deployed. Read [LIVE hold](docs/architecture/LIVE_ACTIVATION_HOLD_20261030.md) before any separately approved release.


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

### 2. Codex Companion in ChatGPT IDE (Neural AI, chat mode):
The persistent worker invokes the installed Codex CLI with its ChatGPT login, validates structured judgments, and stays armed for entry and stop requests. The older watcher only prints a one-shot notification and does not invoke a model.
1. Check the CLI/session and a nontradable canary, then arm the persistent worker:
   ```powershell
   python -m tools.codex_companion --check
   python -m tools.codex_companion --self-test
   python -m tools.codex_companion
   ```
2. The operator launches the scheduler for controlled acceptance; initial startup uses `auto_trade_enabled=false`. See the local acceptance procedure before enabling new entries:
   ```powershell
   python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode chat --wait-until-market-open
   ```
   See [Codex companion](docs/CODEX_COMPANION.md) and [operator acceptance](docs/operations/KITE_LOCAL_ACCEPTANCE_20261030.md). R01 positions keep unified stops; the worker also handles legacy stop consultations when the engine publishes them.

### 3. Account & Data Verification (Read-Only Pre-Flight):
To run read-only pre-flight account & data verification before market open:
```powershell
python -m tools.brokers --broker both
python -m tools.verify_market_data --broker kite --after-hours
```
