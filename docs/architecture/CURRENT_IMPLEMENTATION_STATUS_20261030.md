# Current implementation and LIVE release status — 2026-10-30

> **Canonical current-state guide for this feature branch.** This supersedes dated status claims in the 2026-10-19/20 staged-refactor review, the R00 2026-10-29 source inventories, and the prior R01/R02–R10 implementation snapshots. Those documents remain valuable as **historical baselines**, not present-tense activation instructions.

- **Repository:** `hawisback/codex-trading`
- **Working branch:** `feature/live-activation-guardrails-20261030`, branched from `refactor/r02-r10-safety-foundations-20261029` (which descends from `feature/r01-approved-policy-contracts-20261029`).
- **Rollout state:** **CODE COMMITTED, OWNER CODE-REVIEWED; NOT MERGED TO `main`, NOT TESTED IN THIS INCREMENT, NOT BROKER-UAT VERIFIED, NOT DEPLOYED OR ACTIVATED.** User inspection of code is not broker or safety validation.
- **Feature state:** `config/trading.json:r01_policy.enabled=false`. The JSON fields `mode=LIVE`, `system_armed=true` and `auto_trade_enabled=true` are **not evidence of a live authenticated execution session**. Native Kite/Breeze also require explicit `--live`, verified account identity and their gateway's LIVE lease/authorization. Do not start the native scheduler from a README example without separate supervised release approval.
- **Verification instruction:** New regression files are authored/registered; **no tests were executed** in the current R01/R02–R10/LIVE-guardrail/unified-stop increments, per the owner's standing direction. Static syntax inspection is not a regression, integration or broker test.

## What the current branch actually contains

| Area | Current code | Limitations / remaining acceptance |
| --- | --- | --- |
| R01 approved sizing and entry policies | 2/4/6/8/10 **maximum** NIFTY lots for verified available-margin bands through ₹20k/₹40k/₹60k/₹80k/above ₹80k; additional ₹150 reserve, executable ask/approved limit, current hard caps and authenticated broker quantity limit. Price-only penny veto removed only for opted-in R01; actual consultant stays mandatory. 10 daily filled-entry ceiling and 14:15 IST entry cutoff. | `r01_policy.enabled=false`. Account-day P&L and broker/instrument-specific freeze quantity are not supplied by the current native funds adapters; NEW R01 buys fail closed. Other runtime and historical profiles may still use legacy rules. |
| LIVE gateway safety | Kite/Breeze native funds reads include authenticated `account_id`, locally observed `funds_asof` and `source`; pre-entry and submission preflight validate the strict funds contract; native `set_mode("LIVE")` acquires per-account host OS lease with checks at mutation transport. | Receipt time is **not** a broker P&L ledger. The lease fences only cooperating local adapters sharing the lock namespace, not external applications/distributed deployments or the proxy path. No broker UAT. |
| Unified protective stop (R01 only) | `trading/domain/unified_stop_policy.py` and `unified_stop_workflow.py` calculate an upward tick-rounded monotonic floor. `StopManager` creates and ratchets the broker stop; `PositionMonitor` uses the same strategy-independent policy for **new positions stamped `r01-owner-20261029-v1`**. Legacy strategy timers, targets, EMA/VWAP runners and morning microtrails are bypassed **only for those R01 positions**. | No executed end-to-end stop parity, crash, partial-fill or real-broker tests. Existing unstamped legacy positions retain original management. Independently verified technical invalidation, pending-risk exits and mandatory 15:15 square-off remain. |
| OMS and R02–R10 refactor | Position store/journal hardening, owner lease abstraction, typed contract/policy/replay/incident primitives, audit redaction, read-only readiness report and an operator runbook exist. | Not all typed R03–R10 primitives are wired into LIVE. Proxy account ownership, authoritative market calendar/instrument-master ingestion, broker daily P&L and operations drills remain incomplete. |

## Unified stop schedule for stamped R01 positions

- **Initial option floor:** entry premium × (1 − `r01_initial_stop_pct/100`), currently frozen from `risk.option_hard_stop_pct=25` at entry. Never loosen a stronger recorded/confirmed broker stop or AI floor.
- **Peak gain tiers:** +15% → at least entry; +20% → +10% protected; +30% → +20% protected; +40% → +30% protected.
- **Morning 09:15–11:30 IST:** +5% peak → −8% floor, +10% → +1%, +15% → +10%, combined by max with common tiers.
- **Midday 11:30–13:15 IST:** +5% peak → +3% floor, combined by max with common tiers.
- **Afternoon until 15:15 IST:** common tiers remain. The session close triggers an exit request; broker fills are **not guaranteed** during an outage.
- Profit-driven actions require `quote_verified=True`, a timestamped fresh executable positive bid (2-second default) and persisted peak evidence. Stale/invalid evidence does **not** cause a new price-driven order. The existing OMS owns all stop/exit mutations and reconciliation; the floor is not a promise of fill price or absence of gaps.
- R01 version and initial loss parameter persist with the trade: disabling the new-entry switch mid-session does **not** convert existing stamped R01 positions to legacy stops. New R01 entries are rejected if unified-stop opt-in is inconsistent. Post-fill legacy strategy-specific two-step AI stop override is skipped **only for stamped R01**; mandatory **pre-entry** consultation and veto are never bypassed.

Full contract: [R01_UNIFIED_STOP_EXECUTION.md](R01_UNIFIED_STOP_EXECUTION.md). Legacy behavior: [TRAILING_STOPS.md](../TRAILING_STOPS.md).

## Release blockers — do not enable merely to make a status pass

1. **Verified broker day P&L:** `pnl_account_id`, `pnl_session_date`, `pnl_asof`, positive `start_of_day_equity`, `realized_pnl_today` and `unrealized_pnl_today` for the authenticated account/session. No synthetic zeroes, config-derived balance or stale aggregation.
2. **Verified broker contract limits:** `max_single_order_quantity` from the current account and actual NIFTY instrument/broker freeze rule, with same-contract identity and provenance. No guessed 65/650 freeze limit or automatic order splitting.
3. **Authoritative market sources:** verified exchange trading/expiry calendar plus refreshed Kite/Breeze instrument master integrated with R05; no inferred or stale expiry for new orders.
4. **Ownership/recovery:** prove one permitted OMS owner at each LIVE entrypoint, account/credential drift fencing, broker/book completeness, unknown ACK, cancellation/replacement, stop trigger, partial fill, gap and restart recovery.
5. **Offline evidence:** with separate permission to change the standing no-tests restriction, run `python -m tools.checks`, `python -m tools.quality` and the registered `tests/test_regression.py` suite, plus replay/fault-injection and R01-vs-legacy stop parity. No such pass is claimed.
6. **Broker UAT and operations:** supervised broker sandbox/low-risk conformance, order/stop/exit lifecycle, kill switch, account and instrument identity, alerting, 15:15 flatness checks and rollback drill. Operator must approve the **exact commit**, account and approved position/risk limits.

The read-only `python -m tools.refactor_readiness` deliberately reports **BLOCKED** until evidence is externally supplied and reviewed. A status flag or syntax check cannot certify a real-money release.

## Documentation map and precedence

1. This file is the **current branch implementation/verification status**.
2. [LIVE_ACTIVATION_HOLD_20261030.md](LIVE_ACTIVATION_HOLD_20261030.md) is the concrete activation blocker list.
3. [R01_ACTIVATION_RUNBOOK.md](R01_ACTIVATION_RUNBOOK.md) defines required funds/schema and opt-in workflow.
4. [R01_UNIFIED_STOP_EXECUTION.md](R01_UNIFIED_STOP_EXECUTION.md) is the integrated stop/OMS contract.
5. [REFACTOR_OPERATOR_RUNBOOK.md](../operations/REFACTOR_OPERATOR_RUNBOOK.md) is the unvalidated operator and incident recovery procedure.
6. [R01_POLICY_IMPLEMENTATION_STATUS.md](R01_POLICY_IMPLEMENTATION_STATUS.md), [REFACTOR_DELIVERY_STATUS_20261029.md](REFACTOR_DELIVERY_STATUS_20261029.md), [TRADING_ENGINE_REFACTOR_MASTER_PLAN.md](../TRADING_ENGINE_REFACTOR_MASTER_PLAN.md), [POLICY_USAGE_MAP.md](POLICY_USAGE_MAP.md), [STAGED_REFACTOR.md](../STAGED_REFACTOR.md) and source-specific snapshots describe **earlier points in time**. Do not use their previous tense/status to infer current feature activation.

**Do not delete journal/state to clear a broker uncertainty, start a second writer, bypass an AI veto, or assume a stop/exit was filled from an HTTP acknowledgement.**
