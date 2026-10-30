# Current implementation and LIVE release status — 2026-10-30

> **Canonical current-state guide for this feature branch.** This supersedes dated status claims in the 2026-10-19/20 staged-refactor review, the R00 2026-10-29 source inventories, and the prior R01/R02–R10 implementation snapshots. Those documents remain valuable as **historical baselines**, not present-tense activation instructions.

- **Repository:** `hawisback/codex-trading`
- **Current release target:** **Kite only**. The owner deferred Breeze; its authentication issue is outside this release's gates. Kite account and live read-only market checks pass, while Kite R01 source integration and read-only acceptance pass; actual broker order acceptance remains open.
- **Working branch:** `feature/live-activation-guardrails-20261030`, branched from `refactor/r02-r10-safety-foundations-20261029` (which descends from `feature/r01-approved-policy-contracts-20261029`).
- **Rollout state:** Prior integration was committed and owner code-reviewed. **LOCAL OFFLINE REPAIRS PASS; NOT BROKER-UAT VERIFIED, NOT MERGED TO `main`, NOT DEPLOYED OR ACTIVATED.** The feature-branch repair candidate is based on `097eeec`; see [validation and candidate identity](OFFLINE_VALIDATION_20261030.md).
- **Feature state:** `config/trading.json:r01_policy.enabled=false`. The JSON fields `mode=LIVE`, `system_armed=true` and `auto_trade_enabled=true` are **not evidence of a live authenticated execution session**. Native Kite/Breeze also require explicit `--live`, verified account identity and their gateway's LIVE lease/authorization. Do not start the native scheduler from a README example without separate supervised release approval.
- **Verification:** The owner explicitly authorized testing and repairs. The full quality wrapper passes locally on Windows/Python 3.14.6, including **574 registered offline tests** with network blocked. New fixtures cover R01 native OMS workflow and independent-process ownership/crash release. This is offline evidence; actual broker acceptance remains pending; the tested working-tree fingerprint identifies this local candidate.

## What the current branch actually contains

| Area | Current code | Limitations / remaining acceptance |
| --- | --- | --- |
| R01 approved sizing and entry policies | Revised 2026-10-30 milestones: up to 2 lots below INR 40k, 4 at 40k, 6 at 60k, 8 at 80k and 10 at 100k. Affordability uses actual option limit and INR 150 reserve. Account-day cash loss cap is INR 3,000 per actual proposed entry lot, recalculated each entry; a breach blocks only new entries. Real consultation, 10 daily filled-entry ceiling and 14:15 cutoff remain. | `r01_policy.enabled=false`. Local and read-only acceptance pass; actual broker order UAT remains. Legacy paths retain their original policy. |
| Codex neural companion | Persistent worker explicitly invokes the local CLI using ChatGPT login; independent entry/stop slots, strict structured output, original 45-second deadline and application-owned atomic handoff. The 15-second approval TTL and 25% active initial protection remain. | CLI canary passes in 8.272s; no active broker consultation or order acceptance was performed. See [worker guide](../CODEX_COMPANION.md). |
| Live operator pause | Fresh local `kill_switch`, `auto_trade_enabled` and `system_armed` values gate candidate work and BUY preparation/pretransmit. Tests cover hot pause/resume and pacing races. | Pause blocks new exposure and continues existing stop/exit management; it cannot recall an already transmitted BUY. |
| LIVE gateway safety | Kite/Breeze native funds reads include authenticated `account_id`, locally observed `funds_asof` and `source`; pre-entry and submission preflight validate the strict funds contract; native `set_mode("LIVE")` acquires per-account host OS lease with checks at mutation transport. | Receipt time is **not** a broker P&L ledger. The lease fences only cooperating local adapters sharing the lock namespace, not external applications/distributed deployments or the proxy path. No broker UAT. |
| Unified protective stop (R01 only) | `trading/domain/unified_stop_policy.py` and `unified_stop_workflow.py` calculate an upward tick-rounded monotonic floor. `StopManager` creates and ratchets the broker stop; `PositionMonitor` uses the same strategy-independent policy for **new positions stamped `r01-owner-20261029-v1`**. Legacy strategy timers, targets, EMA/VWAP runners and morning microtrails are bypassed **only for those R01 positions**. | Offline stop, native OMS, restart and partial-fill fixtures pass; real-broker stop/fill behavior remains unverified. Existing unstamped legacy positions retain original management. Independently verified technical invalidation, pending-risk exits and mandatory 15:15 square-off remain. |
| OMS and R02–R10 refactor | Position store/journal hardening, owner lease abstraction, typed contract/policy/replay/incident primitives, audit redaction, read-only readiness report and an operator runbook exist. | Not all typed R03–R10 primitives are wired into LIVE. Kite daily P&L and current-session master/freeze/calendar evidence are wired into new R01 entries. Proxy/distributed ownership and unrelated primitives are outside this single-machine Kite release; real broker recovery drills remain pending. |

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

1. **Actual broker acceptance remains open:** The operator must run the controlled order/protection/ratchet/exit and restart/rollback checks in the [local acceptance procedure](../operations/KITE_LOCAL_ACCEPTANCE_20261030.md). Offline fixtures and read-only sources cannot establish real stop coverage or fill/cancel behavior. The assistant has not executed real orders.
2. **Current session evidence must remain valid:** Kite margins and P&L must be fresh, account-matched and complete; the exact option must match the current master, NSE freeze feed and regular-session calendar. Read-only acceptance passed; any subsequent source failure blocks new exposure.
3. **Local release only:** This Windows machine is the owner's deployment target. No CI, Linux validation, distributed rollout or additional security project is required. Preserve authenticated account identity, the existing single-writer lease and risk/OMS checks. The source fingerprint identifies the tested candidate. The owner requested feature-branch check-in; broker acceptance and activation remain separate operator steps.

The read-only `python -m tools.refactor_readiness` deliberately reports **BLOCKED** until evidence is externally supplied and reviewed. A status flag or syntax check cannot certify a real-money release.

## Documentation map and precedence

1. This file is the **current branch implementation/verification status**.
2. [LIVE_ACTIVATION_HOLD_20261030.md](LIVE_ACTIVATION_HOLD_20261030.md) is the concrete activation blocker list.
3. [R01_ACTIVATION_RUNBOOK.md](R01_ACTIVATION_RUNBOOK.md) defines required funds/schema and opt-in workflow.
4. [R01_UNIFIED_STOP_EXECUTION.md](R01_UNIFIED_STOP_EXECUTION.md) is the integrated stop/OMS contract.
5. [REFACTOR_OPERATOR_RUNBOOK.md](../operations/REFACTOR_OPERATOR_RUNBOOK.md) is the unvalidated operator and incident recovery procedure.
6. [R01_POLICY_IMPLEMENTATION_STATUS.md](R01_POLICY_IMPLEMENTATION_STATUS.md), [REFACTOR_DELIVERY_STATUS_20261029.md](REFACTOR_DELIVERY_STATUS_20261029.md), [TRADING_ENGINE_REFACTOR_MASTER_PLAN.md](../TRADING_ENGINE_REFACTOR_MASTER_PLAN.md), [POLICY_USAGE_MAP.md](POLICY_USAGE_MAP.md), [STAGED_REFACTOR.md](../STAGED_REFACTOR.md) and source-specific snapshots describe **earlier points in time**. Do not use their previous tense/status to infer current feature activation.

**Do not delete journal/state to clear a broker uncertainty, start a second writer, bypass an AI veto, or assume a stop/exit was filled from an HTTP acknowledgement.**
