# Engineering risk register — R00 baseline

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

Priority indicates engineering risk, not verified exploitability or probability.

| Risk ID | Priority | Risk and evidence | Mitigation package | Validation needed |
| --- | --- | --- | --- | --- |
| RSK-01 | P0 | Unclear effective exposure caps: strategy compounding may take precedence over global JSON max | R01 policy ADR, R06 risk | Per-strategy quantity fixtures with verified margin |
| RSK-02 | P0 | Runtime and configuration differ on entry and square-off times | R01 + R06 | IST boundary cases; broker outage |
| RSK-03 | P0 | Unresolved mutation outcome can resemble absence of local position | R02 + R03 | Crash/restart and lost acknowledgment |
| RSK-04 | P0 | Broker state/book incomplete or foreign to account | R03 + R04 | Truncated order pages, account switch |
| RSK-05 | P1 | Gateway journal `RLock` does not coordinate independent processes | R02 single writer | Multi-process ownership checks |
| RSK-06 | P1 | Ambiguous position-state data and failed atomic writes | Existing OMS branch + R02 | Corrupt, missing, readonly and disk-full cases |
| RSK-07 | P1 | Market data quote age/depth/OI/session inconsistencies | R04 + R05 | Redacted broker fixtures and feed validation |
| RSK-08 | P1 | AI chat handoff could be stale/unbound under clock skew | R07 | Identity/time budget scenarios |
| RSK-09 | P1 | Many root research/manual scripts have unknown import-time effects | R00 + R09 | Read-only audit; no broad test discovery |
| RSK-10 | P1 | Operational ability to detect orphan orders and protective-stop failure | R10 | Runbook drills, alerts and UAT |
| RSK-11 | P2 | Documentation contains Windows-specific absolute paths and legacy business claims | R00 docs inventory + R09 | Clean documented root |
| RSK-12 | P2 | Mixed deterministic rules vs neural AI terminology | R07 + docs | Mode-specific consultation assertions |

Risk owner assignments and severity likelihood remain **unapproved**; no live deployment certification is implied.
