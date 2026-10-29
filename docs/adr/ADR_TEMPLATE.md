# ADR-NNN: <Decision title>

- **Status:** PROPOSED | APPROVED | REJECTED | SUPERSEDED
- **Date:** YYYY-MM-DD
- **Owner/approver:** unassigned
- **Change class:** STRUCTURAL | POLICY | BROKER_CONTRACT | OPERATIONS
- **Related policy ID:** POL-0N (if applicable)
- **Scope:** affected strategies, brokers, environments, JSON keys and runtime modules

## Context and evidence

What is currently implemented? Cite code paths and exact current behavior. Separate **configured**, **documented** and **verified effective** behavior. Include existing tests and field observations; never include credentials or unredacted broker/account data.

## Decision

What changes? Document selected alternative and rejected alternatives.

## Risk, migration and rollback

List potential exposure increases, order payload changes, journal/schema compatibility, account and broker implications, kill switches and owner actions. If none, explain.

## Behavior impact matrix

| Scenario | Before | After | Approved intended difference? |
| --- | --- | --- | --- |
| Normal order | | | |
| Failure/restart | | | |
| Risk veto / account unknown | | | |

## Validation / rollout

- Owner-approved acceptance criteria:
- Tests / broker UAT to run later:
- Migration/backward compatibility:
- Rollback/forward-recovery limitations:

## Sign-off

- [ ] Owner approved values and exceptions
- [ ] Implementation change is explicitly authorized
- [ ] Regression evidence recorded (not just asserted)
- [ ] Operations notified where applicable
