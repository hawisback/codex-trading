# R01 owner policy decision register

**Updated:** 2026-10-29, from owner's stated policy directions in ChatGPT.  
**Status:** OWNER DIRECTIONS RECORDED; POL-01 inclusive lot ladder implemented as an **offline preview only** on `feature/r01-approved-policy-contracts-20261029`. No live strategy/risk/configuration changes authorized or applied. Refer to `OWNER_POLICY_DIRECTIONS_20261029.md`, `R01_POLICY_IMPLEMENTATION_STATUS.md` and `docs/adr/ADR-0001-OWNER-LOT-LADDER.md`.

| ID | Owner direction (2026-10-29) | Status and remaining specification |
| --- | --- | --- |
| POL-01 | Broker-derived capital determines maximum lots: <=₹20k: 2; >₹20k–₹40k: 4; >₹40k–₹60k: 6; >₹60k–₹80k: 8; >₹80k: 10, 10 hard maximum. Actual lot count must still be affordable based on option execution price. | **Offline implementation committed; LIVE not integrated.** Capital basis (available margin vs equity), broker identity/freshness and order cap still require approval; the instrument spot is never the executable option premium for funding. |
| POL-02 | Retain current effective 14:15 IST new-entry cutoff and 15:15 IST square-off trigger. | **Direction accepted.** Unify documentation/config without weakening runtime guards; fills cannot be guaranteed during outages. |
| POL-03 | ₹12 and ₹30 are candidate thresholds for the 0DTE penny-option trap. | **Threshold open.** Decide exact applicability and price/time rules; no silent selection. Current option premium selection cap ₹135 is a separate parameter with no authorized change. |
| POL-04 | Never use static assumed capital for live decisions; obtain live available funds/equity from the authenticated broker. | **Direction accepted.** Distinguish bracket basis from per-order purchasing power; no static ₹10k/₹500k assumptions for live sizing. |
| POL-05 | Up to 10 trades per day, conditional on not reaching an unacceptable daily loss. | **Direction accepted; loss rule open.** Specify monetary/%/R threshold, realized plus unrealized treatment, daily baseline, time reset, stop-on-loss behavior and trade counting. Existing active strategy limit of 2 remains until separately changed. |
| POL-06 | One unified stop-loss and trailing policy across all strategies; adjustments may depend on IST time of day, **not** strategy identity. | **Direction accepted; formulas/time windows open.** Define initial stop protection, ratchet floors, time windows, breakeven, profit tiers, consultation, and safe migration of already-open positions. |
| POL-07 | Production trading is intended to use LIVE execution. | **Direction accepted.** Preserve explicit authorization, verified broker account, emergency controls and non-executing offline tests. Never equate “always live” with automatically submitting real-money orders at startup. |
| POL-08 | Exchange holiday/expiry data should be updated when needed using the most reliable process. | **Direction accepted; implementation design open.** Proposed: authoritative published exchange calendar plus validated current broker instrument master; fail closed on ambiguous expiry. |

**Meaning of “accepted”:** owner has stated an intended business policy. It does **not** mean implemented, tested, deployed, or authorized to relax existing checks. Each behavior-changing implementation needs a scoped policy ADR and review.

## Existing code discrepancies still to reconcile

- `AGENTS.md` formerly describes different ladder thresholds; `config/strategies.json` active MACD compounding uses milestone floors 0/20k/40k/70k/100k for 2/4/6/8/10 lots, whereas the owner has now specified inclusive upper brackets 20k/40k/60k/80k and 10 maximum.
- `config/trading.json` risk max_order_quantity=65 vs active MACD strategy cap=650 and strategy precedence in `trading/domain/sizing.py` / `position_lifecycle.py`. A single reviewed source of truth is required.
- `config/trading.json` entry cutoff 14:45 and exit 15:20 differ from runtime 14:15 / 15:15.
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
