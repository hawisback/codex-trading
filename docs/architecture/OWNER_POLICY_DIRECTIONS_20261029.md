# Owner policy directions — 2026-10-29

**Change class:** POLICY SPECIFICATION (documentation only).  
**Repository branch:** `refactor/r00-r01-policy-foundations-20261029`.  
**Status:** POL-01/POL-04 lot sizing and POL-02 configuration alignment implemented on unmerged refactoring branch; NOT TESTED, merged, deployed or broker validated. Other policy thresholds remain unresolved. No tests/live broker operations were run.

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

**Confirmed:** bracket capital is authenticated broker available margin; NIFTY spot is for strike selection, while the executable option price determines affordability.

**Existing behavior differs:** `config/strategies.json` active MACD milestone floor values 0/20k/40k/70k/100k with 2/4/6/8/10 lots. The owner wants upper-bound bands ending at 20k/40k/60k/80k. The owner approved the new global available-margin ladder; see ADR-001. Legacy strategy-local milestone lists remain for historical compatibility only; live calculator no longer uses them.

## POL-02 — Session cutoffs

Owner agrees to **14:15 IST hard new-entry cutoff** and **15:15 IST mandatory square-off trigger**. Preserve all existing earlier gates (e.g. strategy entry start), pre-send recheck and broker reconciliation. If a broker is unreachable, an initiated square-off is not a verified flat position; retain incident and exposure management. Configuration and documentation should eventually converge on these rules after parity review.

## POL-03 — 0DTE penny-option thresholds

Owner is open to **₹12 or ₹30**; no final threshold was selected. Decide whether this is a minimum executable option price, option LTP, strike/expiry filter or a conditional rule by time/liquidity. Current `option_selection.max_option_premium=135` governs a **different upper-bound selection rule** and should not be changed under the guise of choosing a penny-option veto. Note `use_current_expiry_on_0dte=false` in current trading JSON. Preserve the existing gate until the decision is explicit.

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

1. **POL-01:** Resolved: authenticated broker available margin for tier, option executable premium for affordability; NIFTY spot for strike selection.
2. **POL-05:** Which loss threshold triggers a ban on new entries: ₹ amount, percentage of broker-reported start-of-day equity, R multiples, consecutive losses, or the first of several? Include unrealized P&L?
3. **POL-03:** Precisely which instrument price and 0DTE conditions should use ₹12 vs ₹30? Or should the current filter remain until a broker/market-data study?
4. **POL-06:** Confirm initial stop and trailing time windows/thresholds across strategies; this requires a behavior-impact analysis, not a mechanical extract.
5. **POL-07:** Should a production CLI missing explicit `--live` refuse startup rather than permit a proxy PAPER session? Preserve current behavior until an operator ADR.

**Next step:** review this document and raise individual policy ADRs (using `docs/adr/ADR_TEMPLATE.md`) for changes that alter trading exposure, lot counts, entry frequency or stop execution; tests and broker UAT later, per user request.
