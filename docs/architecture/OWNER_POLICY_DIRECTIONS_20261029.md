# Owner policy directions — 2026-10-29

**Change class:** POLICY SPECIFICATION (documentation only).  
**Repository branch:** `refactor/r00-r01-policy-foundations-20261029`.  
**Status:** user-provided desired behavior captured; implementation remains pending review and precise definitions. No live configuration, strategy code, stop logic, or broker execution was changed in response to these directions. No tests were run.

## POL-01 — Broker capital-based maximum lot ladder

The owner specifies the following **inclusive upper bounds**:

| Broker-derived capital range (INR) | Upper bound in NIFTY lots | Maximum contracts at currently hard-coded 65/lot |
| --- | ---: | ---: |
| positive funds through ₹20,000 inclusive | 2 | 130 |
| above ₹20,000 through ₹40,000 inclusive | 4 | 260 |
| above ₹40,000 through ₹60,000 inclusive | 6 | 390 |
| above ₹60,000 through ₹80,000 inclusive | 8 | 520 |
| above ₹80,000 (including above ₹100,000) | 10 | 650 |

This is the owner's stated ladder interpretation: e.g., ₹20,000 is 2-lot tier, ₹20,001 is 4-lot tier. **Zero/invalid/unavailable broker funds must never create an entry.** Position count, one-position constraint, lot size, broker restrictions and funding checks remain separate.

A tier is a **ceiling, not a minimum**. Candidate selection may use NIFTY **underlying spot** to determine strike and an appropriate option contract; buying power must be checked against the selected option's **fresh executable ask/approved limit premium**, actual broker-verified available margin, and the existing ₹150 fee reserve. No historical LTP or NIFTY spot index level should substitute for executable option premium in funding arithmetic. For positive finite limit price P and broker available margin B, a conceptual *maximum affordable* whole-lot count is floor(max(0, B - ₹150) / (P × current lot size)); actual order quantity is capped by the bracket maximum, available and risk-approved broker funds, broker ceilings, hard limits, and the consultation veto. This is **policy documentation**, not a replacement algorithm authorized by this note.

**Open:** what exactly defines bracket “capital” (verified available margin, total account equity, or net liquidation)? If it differs from available margin used for order funding, document both broker fields and their update/failure semantics. Clarify owner's “spot price” term (underlying spot for strike selection vs option premium for affordability).

**Existing behavior differs:** `config/strategies.json` active MACD milestone floor values 0/20k/40k/70k/100k with 2/4/6/8/10 lots. The owner wants upper-bound bands ending at 20k/40k/60k/80k. Do not edit the active milestone list without approved boundary cases and a full simulation of possible exposure increases/decreases.

## POL-02 — Session cutoffs

Owner agrees to **14:15 IST hard new-entry cutoff** and **15:15 IST mandatory square-off trigger**. Preserve all existing earlier gates (e.g. strategy entry start), pre-send recheck and broker reconciliation. If a broker is unreachable, an initiated square-off is not a verified flat position; retain incident and exposure management. Configuration and documentation should eventually converge on these rules after parity review.

## POL-03 — No penny-option veto or price-band bias (owner clarification)

**Owner decision confirmed 2026-10-29:** Trades must **not** be selected or rejected solely because of the underlying NIFTY spot level, or because an option is labeled a "penny option" at a fixed ₹12/₹30 threshold. **No new penny-option rule** and no replacement fixed minimum premium should be added. Spot remains market/context data where the strategy needs it; this decision is not a ban on reading the index or validating contract identity. The actual option execution premium and authenticated broker funds still determine **affordability**; quote age, spread, liquidity, expiry validity, independent risk, and the mandatory AI consultation/veto remain required.

**Source conflict requiring a separate change:** `ai_consultant.py` implements a sub-₹12 0DTE Trap 2 veto, while `config/rules_playbook.md` describes it. `config/trading.json` has `option_selection.min_option_premium=15` and `max_option_premium=135`; `entry_policy.py` uses both for entry bounds, and `trading/application/selection.py` uses the maximum during candidate selection. The premium cap may also constrain trade selection independently of affordability. None of these existing LIVE checks has been removed in this documentation-only clarification. Inventory and safety review must distinguish unwanted fixed price bias from valid broker affordability and market-integrity controls. `use_current_expiry_on_0dte=false` remains unchanged.

## POL-04 — Real broker capital exclusively

Capital for live policy must come from an authenticated, freshness-checked broker view. **No static ₹10k or ₹500k may authorize real-money orders**; hardcoded examples remain permissible only as clearly marked tests/documentation or explicitly segregated research scenarios. Fail closed for new entries on funds API failure, invalid figures, wrong account or exhausted margin. Do not suppress protective action on existing positions merely because a funds query failed.

## POL-05 — Ten daily trades subject to a loss gate

Owner allows **up to 10 completed entry decisions/trades per IST session** provided loss is not excessive, but the exact loss rule is **not yet approved**. Proposal for review only: a broker-reconciled daily P&L guard combining realized and mark-to-market P&L, explicit account-day baseline, maximum drawdown threshold, and fail-safe new-entry halt if broker/P&L data is missing. Existing JSON fields `max_daily_loss_pct=1.5` and `max_daily_loss_r=2.0` are possible candidates, **not owner-approved enforcement rules**. Clarify whether “trade” counts submissions, filled entry positions, round trips or per-strategy entries; design against split order fills inflating counts. Existing MACD profile `max_daily_entries=2` remains operative until approved.

## POL-06 — Unified stops and trailing independent of strategy

One shared OMS-owned policy should govern **initial stop placement, stop adjustments, monotonic stop floors, trailing profit tiers, time-of-day windows, end-of-day exit and failure recovery** across all strategy profiles. Strategy may supply factual entry/structural context but must not select a weaker protection rule by name. Time-of-day adjustments use exchange/session clock and must not lower an already confirmed protective floor. Existing positions need policy-version continuity/migration so a config change cannot loosen an active stop. The owner has not approved exact initial loss percentages, time windows, gain thresholds or pullbacks, so do not unify through a risky wholesale change.

## POL-07 — Production executes LIVE

“Always live” describes the owner's intended **production deployment mode**; it does not remove the need for `--live` (or equivalent future explicit arming), account verification, broker-connection preflight, mandatory consultation and vetoes, broker-side limits, kill-switch behavior or manual operator recovery. Offline tests, replay and research must remain non-order-writing; PAPER mode may be retained for controlled development or retired only under a separately authorized operational ADR. A stopped process must not automatically enter LIVE or repeat unknown orders after restart.

## POL-08 — Calendar and expiry robustness

Proposed architecture: use a current authoritative exchange holiday/session schedule, validated against a current broker instrument master for actual tradable symbol/strike/expiry; do not infer symbol names from calendar arithmetic. Refresh data at controlled times; capture source date/provenance; reject missing, stale, conflicting or unavailable expiry for **new entries**. Continue protecting existing positions even if calendar updates fail. Owner requested maintainability rather than a fixed manually maintained holiday list.

## Invariants to retain through future implementation

- No new BUY without real consultation gate and unexpired contract-specific approval; veto/trap/error means no entry.
- No orders on stale quotes or non-finite, negative or unknown broker funding data.
- No unprotected verified partial fill; no duplicate SELL from timeout/UNKNOWN recovery.
- No relaxation of the one-open-position guard, mandatory exit management, durable order ID or broker account identity.
- No changes in this note are presumed merged, tested or deployed.

## Open owner clarifications, in priority order

1. **POL-01:** Does “capital” in tier selection mean broker **available margin** (purchasing power), or broker **total equity/net liquidation**, with separate available-margin affordability? Does “spot price” mean underlying NIFTY spot for strike selection?
2. **POL-05:** Which loss threshold triggers a ban on new entries: ₹ amount, percentage of broker-reported start-of-day equity, R multiples, consecutive losses, or the first of several? Include unrealized P&L?
3. **POL-06:** Confirm initial stop and trailing time windows/thresholds across strategies; this requires a behavior-impact analysis, not a mechanical extract.
4. **POL-07 (operational preference):** Should a production CLI missing explicit `--live` refuse startup rather than permit a proxy PAPER session? Preserve current behavior until an operator ADR.

**POL-03 is no longer an open ₹12/₹30 approval question.** Owner rejects penny-option price thresholds; removal of old checks must be reviewed as a separate LIVE behavior change.

**Next step:** review this document and raise individual policy ADRs (using `docs/adr/ADR_TEMPLATE.md`) for changes that alter trading exposure, lot counts, entry frequency or stop execution; tests and broker UAT later, per user request.
