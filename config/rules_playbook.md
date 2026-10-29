# 📋 NIFTY Options Deterministic Rules & Risk Guardrails Playbook

> [!IMPORTANT]
> ### ⚖️ DETERMINISTIC RULES & RISK GUARDRAILS (NOT ARTIFICIAL INTELLIGENCE)
> **This document defines deterministic, hardcoded algorithmic heuristics, boundary filters, and trap-avoidance rules enforced in code (`ai_consultant.py`).**
> * **It is NOT Artificial Intelligence or a Machine Learning model.**
> * In this codebase, **"AI" refers STRICTLY and EXCLUSIVELY to the Antigravity AI Code Companion (neural LLM)** operating interactively in `--ai-mode chat`.
> * When the scheduler runs in `--ai-mode playbook` (or `--ai-mode rules`), it is running **100% deterministic code-based rule checks** with zero neural/AI inference.
> * Whenever the user/operator asks *"Are we using AI?"*, the answer is:
>   - **YES** only if running with the **Antigravity AI Code Companion** (`--ai-mode chat`).
>   - **NO** if running with these deterministic code rules (`--ai-mode playbook` / `--ai-mode rules`).

---

## 🚨 Binding Operational Directive: Risk Guardrails Enforcement

This playbook catalogs the deterministic risk filters and institutional traps enforced by the trading engine before committing capital:
* **Empirical Value:** Enforcing these deterministic trap guardrails prevents blind indicator churn and account liquidation (-805.8% drawdown without filters vs. profitable disciplined execution with guardrails).
* **Deterministic Gate:** The 8 cataloged traps below are evaluated as deterministic code conditions inside `ai_consultant.py`.
* **Supreme Veto Power:** If any trap condition is met, candidate trades are blocked immediately and the engine stands aside in cash.
* **Fail-Safe Rule:** If consultation times out (45s), loses connectivity, or produces an error, the engine defaults unconditionally to **CASH PRESERVATION (0 trades placed)**.

---

## 🏛️ Core Principles (Institutional Market Truths)

1. **Friction is the #1 Enemy in Options Trading:**
   - Overtrading destroys profitability. Indian options incur ~₹40 to ₹50 per round-trip trade in brokerage, STT, turnover, and GST charges.
   - 100+ low-conviction scalps generate ₹7,000+ in fees, wiping out 100% of gross profits.
   - **Rule:** Stand aside on marginal setups. Focus strictly on high-conviction, asymmetric risk-reward trades.

2. **Never Buy Options in Mid-Air:**
   - Never chase green candles floating high above value.
   - A valid long entry must show a **retest / pullback** within 4.0 points of the 5-minute EMA9 before expanding.

3. **Intrinsic Value Over Cheap Theta on Expiry Days (0DTE):**
   - Out-of-the-Money (OTM) options on expiry days lose 50% to 80% of value in minutes due to rapid theta decay.
   - On expiry days, trade **In-The-Money (ITM)** or deep ATM contracts to ensure high Delta (~0.65 to 0.75) and intrinsic protection.

---

## 🚫 Catalog of Identified Market Traps (Learned from Historical Audits)

### Trap 1: [REMOVED] The VWAP Blender & Midday Chop Trap
* **Status:** **REMOVED / DEPRECATED** per empirical bottleneck audit & user directive.
* **Audit Finding:** In the October 2026 6-day audit across 75 candidates, Trap 1 blocked 15 trades: 7 were winners (+₹7,258.68 missed profit) and 8 were minor losses (-₹1,061.45 saved), creating a net drag of -₹6,197.23. Removing Trap 1 increased net sequential portfolio profit from +₹18,299.64 to +₹21,927.42 (+₹3,627.78 gain, 68.0% win rate).
* **Current Action:** **STAND-DOWN / NO VETO**. 2-minute MACD momentum signals with volume expansion are permitted during midday and around VWAP crossings.

### Trap 2: The 0DTE Cheap Option & Gamma Whipsaw Trap
* **Discovered:** Tuesday September 29 & July–August Expiry Days (Tuesdays).
* **Pattern:** On 0DTE expiry days, selecting options with low premiums ($< ₹12.0$) or entering positions during afternoon gamma compression.
* **Failure Mode:** At sub-₹12 premium, a mere 2-point adverse spot flutter causes an instant 30% drop in option value within 2–3 minutes.
* **Guardrail Action:** **VETO CANDIDATE ENTRIES** on 0DTE whenever option premium is $< ₹12.0$. Only trade deep ITM options with sufficient intrinsic cushion.

### Trap 3: The V-Reversal Counter-Trend Short Trap
* **Discovered:** Monday, October 5, 2026 at 12:30 PM IST.
* **Pattern:** Market sells off in the morning, creating a downward-sloping VWAP. Spot hits strong support and rebounds aggressively with massive green candles and RSI rising $> 50$.
* **Failure Mode:** Pure trend indicators signal `BUY_PE` because spot is still technically below the lagging VWAP, stepping directly in front of a short-covering freight train.
* **Guardrail Action:** **VETO PUT ENTRIES** if RSI $> 55$ or price is bouncing violently above 5m EMA9, even if technically below session VWAP.

### Trap 4: The 15-Minute Consolidation Ceiling Trap
* **Discovered:** October 5–9 & September 24, 2026.
* **Pattern:** Spot rallies into the upper boundary of a consolidation box without volume expansion (e.g. 23,244 resistance on Sep 24).
* **Failure Mode:** Buying Calls directly at resistance; market promptly reverses to the range floor.
* **Guardrail Action:** **VETO CALL ENTRIES** within 4 points of the 15m box ceiling. Wait for a decisive breakout or a pullback to the floor.

### Trap 5: The Late-Day Profit Degradation Trap (Post-02:15 PM IST / 08:45 UTC)
* **Discovered:** September 21 & September 24, 2026.
* **Pattern:** Entering new directional option positions after 02:15 PM IST (08:45 UTC).
* **Failure Mode:** Institutions begin rebalancing and squaring off intraday blocks between 02:30 PM and 03:15 PM, inducing non-directional volatility and rapid theta decay.
* **Guardrail Action:** **VETO NEW POSITIONS** after 02:15 PM IST, especially if the account is already sitting on significant intraday gains (> ₹1,800). Lock in daily alpha and close terminal cleanly.

### Trap 6: The Compressed 5m Ribbon Drift Trap (Theta Bleed)
* **Discovered:** Forensic Audit of July & August 2026 (Summer Consolidation Regime).
* **Pattern:** The 5-minute EMA9 and EMA20 moving averages become intertwined with a narrow spread ($|\text{EMA9} - \text{EMA20}| < 4.0\text{ pts}$). Spot is drifting horizontally with no directional institutional commitment.
* **Failure Mode:** In July & August, 32 trades stopped out at the 5m EMA20 with an average duration of 39.8 minutes and an average peak gain of only 3.2%. The trade languishes for over an hour, bleeding theta.
* **Guardrail Action:** **VETO CANDIDATE ENTRIES** whenever the 5m EMA spread is compressed ($< 4.0\text{ pts}$), unless the setup is a fresh directional reversal breaking out to a new day extreme.

### Trap 7: The Counter-Trend VWAP Slope Trap & Reversal Inflection Exception
* **Discovered:** Forensic Audit of June 2026 (15 Sessions), Refined October 2026 Audit (31 Candidates).
* **Pattern:** Technical signal generates `BUY_PE` while Session VWAP is sloping upward, or `BUY_CE` while Session VWAP is sloping downward.
* **Failure Mode:** 17 out of 31 raw counter-slope trades failed, losing $-₹10,514.27$ when fighting runaway freight trains ($|\text{Slope}| > 0.85\text{ pts/min}$) or extreme dislocations ($> 140\text{ pts}$). However, 14 counter-slope trades were explosive institutional V-reversals ($+₹14,532.00$ missed alpha, up to $+50.9\%$ gain).
* **Refined Guardrail Action (Precision Inflection Filter):**
  1. **Unconditional Veto:** Veto counter-slope entries if $|\text{Slope}| > 0.85\text{ pts/min}$ (freight train avalanche), spot distance from VWAP $> 140\text{ pts}$ (deep unhinged dislocation), or the 2m trigger candle closes against the trade direction.
  2. **Reversal Inflection Approval:** Approve counter-slope trades as high-probability Mean-Reversion Inflections when $|\text{Slope}| \le 0.85\text{ pts/min}$, spot distance $\le 140\text{ pts}$, and the 2m trigger candle closes in the direction of the trade (green for CE, red for PE).

### Trap 8: The Climax Overextension Trap (Parabolic Rubber Band)
* **Discovered:** Forensic Audit of June & July 2026.
* **Pattern:** Entering fresh option purchases when spot is already $\ge 75\text{ pts}$ away from Session VWAP in the direction of the move.
* **Failure Mode:** Extreme distance represents a stretched rubber band. Even in strong trends, mean-reversion pullbacks back towards EMA20/VWAP cause severe initial option drawdown, triggering stops.
* **Guardrail Action:** **VETO CHASING ENTRIES** when spot distance from Session VWAP exceeds $75\text{ pts}$ in the direction away from VWAP (e.g. buying CE when spot is $>75$ pts above VWAP, or PE when spot is $>75$ pts below VWAP). Validated Reversal Inflections moving *back towards* VWAP are governed by Trap 7's 140 pt runway limit.

### Trap 9: The Margin Shortfall & Oversized Allocation Trap (Zero Over-Ordering)
* **Discovered:** Wednesday, October 14, 2026 live session audit.
* **Pattern:** Submitting orders where contract premium $\times$ quantity exceeds available cash margin.
* **Failure Mode:** Rejected by broker with HTTP 422 or `Insufficient funds`. Disrupts trade execution sequence.
* **Guardrail Action:** **STRICT VETO & AUTO-BUDGETING:**
  1. Quantity is strictly capped according to verified available margin milestones.
  2. If the preferred ITM strike exceeds safe available margin ($\text{Available Margin} - ₹150$) or the premium cap, step down to ATM, then search OTM strikes nearest first up to `option_selection.max_otm_strikes` (currently 4). Calls scan upward and puts downward in 50-point steps. Select the first valid contract whose one-lot cost fits the safe budget and whose LTP meets the premium cap; recalculate sizing and recheck the full order cost. Every selected candidate still requires the mandatory gatekeeper verdict.
  - **Strategy 5 strict-ITM exception:** `macd_momentum` configured with `strike_selection: STRICT_ITM` must preserve cash if the selected ITM contract is missing or outside budget/premium policy. It must not step down to ATM or OTM. See [session rules](../docs/MACD_SESSION_RULES.md).
  3. If NO tradeable strike fits within safe margin, **VETO THE SETUP ENTIRELY** (`INSUFFICIENT_FUNDS_VETO`). Never submit an order that exceeds broker cash.

---

## 🏆 Proven Winning Setups (Cataloged Patterns)

### Setup 1: The Institutional Trend Runner
* **Pattern:** Clear morning range expansion, Session VWAP trending with slope $> 0.20$ pts/min.
* **Execution:**
  1. Spot retests 5m EMA9 on low volume.
  2. Enter closest ITM strike.
  3. **Risk Management:**
     - Initial Stop: 30% or VWAP invalidation ($\pm 15$ pts).
     - Once in profit ($+15\%$), **lock breakeven floor at $+2\%$**.
     - Trail dynamically using **5m EMA9**: stay in the position as long as spot holds above 5m EMA9.
     - Exit on 10% pullback from peak or target hit ($+50\%$).

### Setup 2: The Morning Climax Rubber-Band Spring (Capitulation Reversal)
* **Pattern:** Spot experiences a severe morning flush (extended $\ge 75$ pts from Open or $\ge 40$ pts from Session VWAP) within the opening 2 hours (09:15–11:15 IST / bars 0–120), with 1m RSI hitting extreme oversold ($\le 32$) or overbought ($\ge 68$), followed by a violent $\ge 18$ pt absorption spring candle.
* **Execution:**
  1. Spot confirms rejection/absorption at extreme deviation.
  2. Enter closest ITM strike.
  3. **Risk Management:**
     - **Structural Wick Invalidation:** Hard spot stop placed immediately below the climax candle low wick (or above high wick) $-2.0$ pts. Loss capped at -6% to -8%.
     - **Profit Target Cap:** $+50\%$ hard target take-profit order.
     - **Dynamic Runner Ratchet:** Once gain reaches $+20\%$, arm trailing ratchet (+10% floor at +20%, +20% floor at +30%, +30% floor at +40%).

---

## 📋 Trade Consultation Checklist

When evaluating candidate trades against these deterministic rules or presenting to the Antigravity AI Companion:

1. **Market Regime:** Is the market trending with conviction, or oscillating inside a flat-VWAP chop box?
2. **Trap Detection:** Does this setup trigger Trap 1 (Midday dead zone), Trap 2 (0DTE gamma whipsaw), Trap 3 (V-reversal), Trap 4 (Ceiling resistance), Trap 7 (VWAP slope mismatch), or Trap 8 (Climax overextension)?
3. **Value Proximity:** Did price retest 5m EMA9, or are we buying in mid-air?
4. **Order Flow & Runway:** Are overhead call writers unwinding, or is there a massive OI wall right above current spot?
5. **Verdict:**
   - `APPROVED` $\to$ Enter trade with specified trailing parameters.
   - `VETOED` $\to$ Stand aside and preserve capital.
