# R01 owner policy decision register

**Updated:** 2026-10-29, from owner's stated policy directions in ChatGPT.  
**Status:** POL-01/02/04 were implemented on earlier unmerged branches. POL-03/05/06 are now implemented on `refactor/r05-pol03-pol05-pol06-safety-20261029` as approved policy directions, still **UNTESTED and NOT DEPLOYED**. POL-06 structural-level selection and time-based trailing remain deferred. Refer to `OWNER_POLICY_DIRECTIONS_20261029.md` for definitions, safety safeguards and open questions.

| ID | Owner direction (2026-10-29) | Status and remaining specification |
| --- | --- | --- |
| POL-01 | Broker-derived capital determines maximum lots: <=₹20k: 2; >₹20k–₹40k: 4; >₹40k–₹60k: 6; >₹60k–₹80k: 8; >₹80k: 10, 10 hard maximum. Actual lot count must still be affordable based on option execution price. | **Implemented on branch, not tested.** Authenticated broker available margin determines the tier; executable option limit price determines affordability. See ADR-001. |
| POL-02 | Retain current effective 14:15 IST new-entry cutoff and 15:15 IST square-off trigger. | **Session JSON aligned on branch; untested.** Existing hard execution guards remain. See ADR-002. |
| POL-03 | Remove blanket penny-price veto: cheap premium alone never disqualifies a trade; use signal validity, liquidity, broker capital and consultation. | **Implemented on review branch:** deterministic <₹12 veto removed, minimum option premium disabled. ₹135 maximum remains a separate setting. Not tested. |
| POL-04 | Never use static assumed capital for live decisions; obtain live available funds/equity from the authenticated broker. | **Implemented for live sizing on branch, untested.** Other research-only static examples remain; no broker calls performed. |
| POL-05 | Up to 10 trades per IST day with ₹5,000 daily loss gate; recommend ₹2,000 planned maximum per entry. | **Implemented on review branch:** broker-filled flat-book day P&L, estimated ₹150 fee cushion per entry, fail-closed on unverifiable books, and 20%-premium-based position budget; live cap 10. Not tested. |
| POL-06 | Implement Protection B: supplied spot invalidation triggers managed early exit for all strategies; no wider than 20% planned initial premium stop. Level selection and trailing schedule remain separate. | **Implemented on review branch:** new BUY needs valid supplied structure, strategy-independent adverse spot breach, 20% cap on initial broker stop while preserving tighter legacy stops. Not tested. |
| POL-07 | Production trading is intended to use LIVE execution. | **Direction accepted.** Preserve explicit authorization, verified broker account, emergency controls and non-executing offline tests. Never equate “always live” with automatically submitting real-money orders at startup. |
| POL-08 | Exchange holiday/expiry data should be updated when needed using the most reliable process. | **Direction accepted; implementation design open.** Proposed: authoritative published exchange calendar plus validated current broker instrument master; fail closed on ambiguous expiry. |

**Meaning of “accepted”:** owner has stated an intended business policy. It does **not** mean implemented, tested, deployed, or authorized to relax existing checks. Each behavior-changing implementation needs a scoped policy ADR and review.

## Existing code discrepancies still to reconcile

- `AGENTS.md` formerly describes different ladder thresholds; `config/strategies.json` active MACD compounding uses milestone floors 0/20k/40k/70k/100k for 2/4/6/8/10 lots, whereas the owner has now specified inclusive upper brackets 20k/40k/60k/80k and 10 maximum.
- Global `risk.max_order_quantity=650` and `max_lots_per_trade=10` now follow the approved available-margin ladder. Old strategy-local compounding data is retained for historical compatibility but no longer controls live sizing.
- Session JSON now aligns with the hard 14:15 entry cutoff and 15:15 square-off trigger. Old research tunables may still contain historical values.
- `config/trading.json` risk.max_trades_per_day=5 vs runtime constant 10 and MACD entry.max_daily_entries=2.
- Strategy exit configs differ materially; centralizing them is a **behavior-changing** policy migration and must be separate from a structural refactor.
- Legacy configured static `account_equity` and `baseline_capital` must not authorize live purchases; retain research snapshots only where clearly labeled.
- The deterministic consultation gate and its veto are mandatory and independent of strategies. LIVE mode does not waive any preflight.

## Current source selection/precedence

- Strategy: CLI `--strategy` → `STRATEGY_MODE` → `config/strategies.json.active_strategy` → runtime fallback.
- AI consultation: CLI `--ai-mode` → `AI_CONSULTATION_MODE` → configured default. Disabled is rejected.
- Execution broker: CLI `--broker` → `EXECUTION_BROKER` → proxy. Native Kite/Breeze require explicit `--live` and verified account authorization.
- Market data: CLI `--market-data-broker` → `MARKET_DATA_BROKER` → kite; independent of execution broker.
- Current order quantity: active strategy `compounding.max_order_quantity` truthy → trading `risk.max_order_quantity` truthy → fallback; broker affordability and absolute position cap also apply.
- Trading JSON parse errors: current loader logs and substitutes an empty dict; making this fatal is a separate behavioral choice.

See `docs/architecture/POLICY_USAGE_MAP.md` for the static trace and `docs/adr/ADR_TEMPLATE.md` for the required policy ADR format.
