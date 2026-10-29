# Implementation checkpoint — 2026-10-29

**Current work branch:** `refactor/pol01-sizing-and-layout-20261029`.  
**Parent:** `refactor/r00-r01-policy-foundations-20261029`.  
**Earlier independent OMS patch:** `refactor/trading-engine-architecture-20261029` remains separate/unmerged.  
**Verification:** static source review and syntax-only parsing only. **No unit tests, integration tests, broker UAT or live orders have been run.**

## Completed on current branch

- POL-01: account-wide inclusive margin-to-lot tiers 2/4/6/8/10, maximum 10 lots, no strategy-specific override. A missing or invalid tier configuration causes no new entry.
- POL-04 sizing: uses authenticated broker `available_margin` and fresh approved option limit premium; no static account-equity authorization.
- POL-02: trading session JSON aligned to 14:15/15:15; existing hard runtime gates retained.
- Compatibility: original `calculate_compounding_quantity` call signature kept for strategies and OMS. Original root calculator/audit CLI names retained as thin wrappers.
- Source records: ADR-001 and ADR-002; policy report inventory, charter and owner decision register updated.
- Folder layout: `research/calculators` and `research/audits` for four historical implementations, with documented migration steps.
- Unrun offline tests: tier boundaries, affordability, missing/malformed broker data and configuration, strategy invariance.

## Not implemented yet

- POL-05: stop at 10 daily entries *conditional on a defined daily loss limit*. The daily loss formula and counted unit are not yet approved; current gates were **not** increased to 10.
- POL-03: choosing ₹12 versus ₹30 for the 0DTE penny trap; not changed.
- POL-06: truly unified time-dependent stop/trailing behavior; formula/time windows not approved; not changed.
- POL-07: maintain explicit live arming, authorization and safe operator controls; do not silently force noninteractive real-money orders.
- POL-08: exchange calendar provider and expiry integration; remains to design.
- Historical profile `compounding` and research script cleanup; remain for compatibility.
- Earlier OMS patch; not merged into this branch.
- Testing, broker quantity/order-limit verification, backtest parity and live readiness sign-off.

## Before merge or any deployment

1. Run `python -m tools.checks` and `python -m tools.quality` with recorded logs and inspect failures; also execute dedicated sizing boundary tests and integration/golden traces.
2. Verify the broker's actual accepted per-order quantity at NIFTY lot size, and whether >65 quantity requires splitting. **Do not introduce automatic splits or live retries without OMS idempotency review.**
3. Test that the 10-lot ceiling is not interpreted as a target, and that actual cost including reserve is covered by current verified broker funds.
4. Verify both active and legacy strategy decision paths, especially changed nominal exposure due to removal of strategy-local 1-lot caps.
5. Validate broker account ownership, fail-closed on stale/missing margin, partial fills, orphan orders, preflight vetoes and stop protection.
6. Confirm daily loss protection requirements *before* approving higher live execution frequency or exposure.
7. Approve a supervised rollout/rollback plan with a fully reconciled broker book. A previously open position must never be assumed flat.

This checkpoint is a record of code on a review branch, **not** production readiness.
