# R01 owner-policy implementation slice — not activated

**Branch:** `feat/r01-owner-policy-implementation-20261029` (based on `refactor/r00-r01-policy-foundations-20261029`).

## What is coded

- `trading/domain/owner_ladder.py`: frozen, deterministic tier and affordability result.
  Inclusive band ends ₹20k/₹40k/₹60k/₹80k, then 10-lot ceiling.
- `trading/domain/sizing.py`: optional `compounding.mode=owner_capital_ladder_v1`.
  All currently configured strategies continue their original sizing path.
- `trading/policy_snapshot.py`: read-only inventory now reports the configured
  compounding mode, so reviewers can see whether the feature is selected.
- `tests/test_owner_ladder.py`: offline characterization for boundaries,
  funding failures, cap enforcement, and unchanged legacy path. Tests were not run.

The entry workflow must still get authenticated funds and a fresh option limit.
The pure helper does not fetch either; **its return must never be used to bypass**
AI consultation, state reconciliation, quote validation, hard cutoff or broker
preflight. The currently configured `macd_momentum` mode is `step_ladder`;
this change does not activate the new policy.

## What is **not** authorized or implemented

- Do **not** choose a daily-loss percentage, max daily entries of 10, or P&L
  denominator without owner-specified loss rules. Active MACD daily limit 2 remains.
- Do **not** select ₹12 vs ₹30 for 0DTE, or redefine initial/trailing stops.
- Do **not** silently change default PAPER/proxy vs explicit native `--live`.
- Do **not** relax the hard 14:15 / 15:15 runtime safety boundaries.
- Do **not** read static `risk.account_equity` as verified broker funds.
- Do **not** normalize holiday/expiry from an unaudited stale calendar.
- Do **not** stamp the read-only inventory SHA into live order intents.

## Next review gate

Owner confirms capital-tier field (available-margin vs total equity), test runs
are separately authorized, and policy ADR gets release approval before changing
`config/strategies.json` to opt in. R01 pending loss, penny option and
stop/trailing definitions remain explicitly unselected. All changes remain
unmerged, no live orders and no test execution.
