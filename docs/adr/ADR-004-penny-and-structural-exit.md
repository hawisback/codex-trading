# POL-03 and POL-06 policy impact — approved 2026-10-29

**Changes on unmerged branch. No tests or broker transactions run.**

## POL-03 — Remove cheap-premium-only veto

- Removed the deterministic 0DTE *less than ₹12* auto-veto from the actual consultation logic.
- Set `option_selection.min_option_premium=0` (disabled); `EntryPolicy` now permits zero as a configured lower bound while still requiring an actual **strictly positive** executable premium and viable bid/ask spread.
- Retained the independent configured **₹135 upper premium selection cap**. This is not a policy to automatically prefer expensive or cheap strikes.
- The mandatory real `AIConsultant.evaluate` call and all unrelated expiry/liquidity/confluence/macro/trap vetoes remain intact. Removing one veto **does not automatically approve** a trade.
- Existing exchange 0DTE eligibility (`use_current_expiry_on_0dte=false`) remains in place; no expiry filter is bypassed.

## POL-06 — Protection B (existing structural invalidation, uniform priority)

- For **all newly executed strategies**, require a supplied positive, quote-validated `invalidation_level`. If absent, do not BUY; do not infer an invalidation from spot/EMA or guess a level.
- Whenever an OPEN position has an existing `invalidation_level`, an adverse verified spot breach triggers the current managed exit path regardless of strategy `enable_structural_wick_stop` flags.
- Structural-level discovery (VWAP, swing or EMA hierarchy) and whether to wait for a candle close or act on a wick remain **separate future POL-06 decisions**. This increments only the already-existing immediate spot breach semantics with a universal strategy gate.
- Retain existing protective broker stop orders, AI stop, pre-existing tighter stop floors, partial-fill and cancel/replace management. Do **not** remove the premium safety stop or weaken already-open exposure management. Initial broker protective stops and option-premium monitor fallback are now capped at 20% for newly managed positions; any previously tighter initial setting or existing tighter stop floor remains authoritative. Time-dependent trailing and initial structure selection remain unchanged.
- If structural spot context is unavailable, the monitor cannot claim an early structural exit; broker-side stop protection stays mandatory.

- The configuration's **existing initial stop percentages above 20%** were tightened to 20% across strategies. The legacy scalper's existing 6% remains tighter; relaxing it to 20% is **not** part of this policy increment. Time-dependent trailing remains strategy-local temporarily, as explicitly deferred.

## Risk and rollout

The new structure requirement may **reduce** entries from strategies that do not currently emit an invalidation level; this is intentional fail-closed behavior. This is a policy change, not a mechanically equivalent refactor. Review the resulting signal/entry parity and recoverability before release. It remains untested/unmerged.
