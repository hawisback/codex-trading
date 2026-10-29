# ADR-R01-POL01: Opt-in capital-band sizing (implementation only)

- **Status:** PROPOSED — not approved for rollout
- **Date:** 2026-10-29
- **Owner/approver:** owner directions for bracket edges recorded; final production approval pending
- **Change class:** POLICY (isolated, feature gated)
- **Related policy ID:** POL-01, POL-04
- **Scope:** `trading/domain/owner_ladder.py`, `trading/domain/sizing.py`, `config/strategies.json` opt-in field only if authorized later

## Context

Active MACD has `compounding.mode=step_ladder`, milestone floors 0/20k/40k/70k/100k,
a strategy order cap of 650 contracts and max 10 lots. `position_lifecycle._submit_entry`
reads authenticated broker `available_margin`, obtains a fresh validated option
execution limit from `entry_limit`, and independently enforces affordability,
strategy ceiling and `MAX_POSITION_QUANTITY=650`. It requires the consultation
verdict before reaching submission.

The owner specified inclusive upper bands (₹20k=2, ₹40k=4, ₹60k=6, ₹80k=8,
above ₹80k=10) and broker-sourced capital, but did not conclusively choose
between broker available margin and total equity for tier selection.

## Proposed implementation

- Add pure `owner_ladder_decision` and the opt-in
  `compounding.mode=owner_capital_ladder_v1` branch.
- For this **provisional implementation**, use the already established
  authenticated broker `available_margin` for the tier and separately
  reserve ₹150 plus price × 65 × lots for funding. Never use static equity
  or NIFTY index spot in the order affordability check.
- Reject zero, negative, non-finite or missing funds/prices; reject malformed
  lot/order caps; apply 10-lot, strategy, broker-platform and absolute 650-contract
  ceilings without rounding up.
- Leave the active MACD mode `step_ladder`; no live behavior or active
  configuration changes until owner confirms capital basis, regression parity,
  broker limits and release gates.
- No changes to AI veto, pre-submit revalidation, OMS ownership, price selection,
  stop orders, daily entries or automatic LIVE arming.

## Behavior impact matrix

| Scenario | Existing active path | New mode (if later enabled) |
| --- | --- | --- |
| ₹20,000 broker available margin | Current milestones may target 4 lots before affordability | 2-tier ceiling before affordability |
| ₹40,000 | Current milestones may target 6 | 4-tier ceiling |
| ₹60,000 | Current milestones may target 6 | 6-tier ceiling |
| ₹80,000 | Current milestones may target 8 | 8-tier ceiling |
| ₹90,000 | Current milestones may target 8 | 10-tier ceiling |
| Insufficient margin | Existing funding gate | Zero lots, block entry |
| Invalid funds/price | Existing entry validation | Zero lots, fail closed |
| Disabled compounding | Old manual/quantity path | Unchanged |
| AI veto or unknown OMS state | Block entry upstream | Still blocked upstream |

Increasing size from 8 to 10 lots at ₹90k is a **material exposure increase**,
so the new mode is intentionally **not selected** in production configuration.

## Validation and rollout

- Offline boundary, funds and parity tests included, **not executed at owner request**.
- Before selecting the mode: confirm broker capital basis and premium semantics,
  verify the 10-lot venue/broker single-order allowance, run complete offline
  regression/replay and broker UAT, assess buying power and worst-case loss,
  and approve a dedicated deployment ADR.
- Rollback: leave/revert strategy `compounding.mode=step_ladder` before starting
  new trades. Do not hot-swap protection on an open position.

## Sign-off

- [x] Owner stated desired upper-band schedule
- [x] Owner requested staged implementation in a review branch
- [ ] Capital basis explicitly signed off
- [ ] Offline regression and scenario evidence recorded
- [ ] Broker order caps and margin contract verified
- [ ] Production activation/deployment authorized
