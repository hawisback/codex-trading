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

- [ ] Baseline fixture mapping documented and expected effects reviewed.
- [ ] Offline suite executed by owner before merge (`python -m tools.checks`, `python -m tools.quality`); record actual results.
- [ ] For broker/state changes, simulated failure and supervised broker UAT evidence gathered separately.
- [ ] Secrets and account IDs redacted from artifacts.
- [ ] Rollback and forward-recovery implications documented.
- [ ] No “production ready” claim without supervised operational acceptance.
