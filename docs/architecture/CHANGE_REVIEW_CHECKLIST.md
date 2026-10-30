# Trading engine change review checklist

## Scope and authority

- [ ] Change class specified: STRUCTURAL / POLICY / BROKER_CONTRACT / OPERATIONS.
- [ ] Branch/PR identifies baseline commit and dependencies; no direct `main` edits.
- [ ] If POLICY, the corresponding ADR was explicitly approved before behavior changes.
- [ ] Includes account/position/session/AI-gate impact analysis and modules touched.
- [ ] Existing OMS boundary hardening status described accurately (unmerged/untested if applicable).

## Behavior preservation

- [ ] No bypass of the real consultation evaluation or weaker veto precedence.
- [ ] No silent changes to quantity, margin, premium, session cutoff, stops, broker route, retry or price rounding.
- [ ] No change to JSON schema or durable order intent identity without a migration and safe rollback.
- [ ] Unknown broker outcomes do not become no-orders/flatness.
- [ ] Active exposure is managed even when new entries are denied.

## Validation and deployment

- [ ] The exact current branch and reviewed commit are recorded; the owner has inspected the code but **review is not execution evidence**.
- [ ] R01-stamped unified stop parity is checked against all five strategy names, previous stronger stops, 2-second quote freshness, IST boundaries and config-switch continuity.
- [ ] Broker P&L (session/account/opening equity/realized/unrealized) and exact instrument freeze limit have authenticated source provenance; missing fields block **new R01 entries**.
- [ ] Verified single OMS owner at **every** LIVE entrypoint, independent of JSON arming; proxy and third-party brokers cannot be assumed fenced by native host locks.
- [ ] Broker stop replacement, partial fill, unknown ACK, restart recovery and 15:15 square-off scenarios are tested before enabling R01 or deploying.


- [ ] Baseline fixture mapping documented and expected effects reviewed.
- [ ] Offline suite executed by owner before merge (`python -m tools.checks`, `python -m tools.quality`); record actual results.
- [ ] For broker/state changes, simulated failure and supervised broker UAT evidence gathered separately.
- [ ] Secrets and account IDs redacted from artifacts.
- [ ] Rollback and forward-recovery implications documented.
- [ ] No “production ready” claim without supervised operational acceptance.
