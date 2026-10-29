# ADR-0001: Owner lot ladder and broker-funded sizing contract

- **Status:** PROPOSED FOR LIVE INTEGRATION — offline implementation committed
- **Date:** 2026-10-29
- **Owner direction:** approved 2/4/6/8/10 tier boundaries; selection of tier-capital broker field **not yet specified**
- **Change class:** POLICY (future live wiring); current commit is an isolated diagnostic only
- **Related policy IDs:** POL-01, POL-04
- **Implementation branch:** `feature/r01-approved-policy-contracts-20261029`

## Context

Existing `trading/domain/sizing.py` uses a strategy-provided milestone ladder
and gives active strategy `compounding.max_order_quantity=650` precedence over
`config/trading.json:risk.max_order_quantity=65`. Real entry submission
checks broker available margin and additional guards in
`position_lifecycle.py`. This was not changed.

The owner's desired tier ceilings are:

| Broker capital (upper limit inclusive) | Tier ceiling |
| --- | ---: |
| Positive through ₹20,000 | 2 lots |
| Above ₹20,000 through ₹40,000 | 4 lots |
| Above ₹40,000 through ₹60,000 | 6 lots |
| Above ₹60,000 through ₹80,000 | 8 lots |
| Above ₹80,000 | 10 lots |

A tier ceiling is **not** an order size, authorization, guaranteed fill,
or minimum lot count. Position exposure, stop protection, hard ceilings,
and broker permissions still matter.

## Implemented now (no live behavior change)

`trading/domain/owner_lot_policy.py` exposes:

- `owner_ladder_max_lots(bracket_capital)` — exact inclusive tiers;
  returns zero for nonfinite, zero, negative or missing input.
- `preview_owner_lot_ceiling(...)` — immutable diagnostic with explicit
  `capital_basis`, `bracket_capital`, `available_margin`,
  `executable_option_ask`, contract `lot_size`, and
  `broker_single_order_quantity_limit`. It calculates the minimum of
  the tier, whole-lot affordability, per-order broker limit and existing
  hard position limit. It never splits broker orders.
- `tools/owner_policy_preview.py` — manual read-only CLI; no broker API,
  account login, OMS or AI call, files, persisted state, or live authorization.
- `tests/test_owner_lot_policy.py` — authored boundary and rejection tests,
  **not executed**, registered in `tests/test_regression.py`.

The default ₹150 reserve comes from `trading/domain/limits.py`.
Positive executable-option ask is explicitly different from the underlying
NIFTY index spot and a historical option LTP. Caller authentication, quote
freshness, live broker identity and available-funds provenance are **not**
validated in the pure function. Passing self-reported values is only a
mathematical preview.

## Open decisions before integration

1. **POL-01 broker field:** Is the capital bracket based on authenticated
   **available margin** or **account equity/net liquidation**? Code supports
   explicit comparison of either; it does not select one.
2. **Instrument and broker limits:** Confirm lot size from current broker
   instrument master and per-order/aggregate broker quantity ceilings. A
   650-contract hard OMS limit is not proof the gateway accepts 650 per order.
3. **Price provenance:** Confirm a freshly broker-verifiable executable ask
   or approved order limit price, associated symbol, expiry and timestamp.
4. **Risk coordination:** The existing one-position gate, strict funds freshness,
   mandatory AI consultation/veto, stop protection, daily loss gate, and
   policy-versioned OMS intents must all remain prerequisites.
5. **Rollout:** Review position-sizing differences at every boundary and
   during broker partial-fill/rejection/timeouts, run offline regression and
   supervised non-production acceptance, then explicitly authorize live wiring.

## Behavior impact matrix

| Scenario | Current production path | This increment | Future live proposal |
| --- | --- | --- | --- |
| New BUY | Existing strategy milestones and existing OMS checks | **Unchanged** | Only after signed-off policy and comparison evidence |
| Invalid/unknown margin | Existing broker/risk checks | Preview returns zero | Fail closed for new entries |
| Broker quantity limit below 10 lots | Existing gateway rules | Preview never exceeds specified single-order limit | No implicit order splitting |
| Partial fill/open stop/UNKNOWN | Existing OMS | **Unchanged** | Keep reconciled protection and no duplicate order |
| AI veto / disabled consultation | Existing mandatory consultation | **Unchanged** | Never bypass |
| Existing position / restart | Existing state recovery | **Unchanged** | Version and protect active positions |

## Validation and rollback

No tests were executed in this implementation turn per owner instruction.
No production config or runtime order path was modified. Reverting the
offline files has no impact on current trading logic. Future live integration
must have a separate behavior-changing commit/ADR with rollback instructions
that do not abandon open positions.

## Sign-off

- [x] Tier boundary values recorded from owner
- [x] Offline diagnostic implementation, without live activation
- [ ] Capital field / broker provenance selected
- [ ] Owner signs off on actual LIVE sizing migration
- [ ] Regression evidence and supervised broker UAT collected
