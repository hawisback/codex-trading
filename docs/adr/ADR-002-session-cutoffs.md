# ADR-002 — 14:15 entry cutoff and 15:15 square-off trigger

- **Date:** 2026-10-29
- **Owner intent:** confirmed in chat
- **Status:** implemented in configuration on unmerged branch, NOT verified by tests
- **Change class:** POLICY

The user accepted an absolute **14:15 IST** cutoff for new entries and a **15:15 IST** mandatory square-off trigger. Runtime constants already specify these values. This branch aligns `config/trading.json:session.no_new_trade_after` and `force_exit_time` accordingly.

The hard submission preflight remains in `position_lifecycle.py` and schedule/clock enforcement remains in `trading/domain/limits.py` and `market_clock.py`. Existing earlier strategy-specific activation gates still apply. A square-off **trigger** does not guarantee the position is filled flat in a market/broker outage: preserve order reconciliation, protective exits and incident escalation.

Other older research-tunable cutoff fields are not silently removed; track separately before changing their historical behavior. Verify IST boundaries, unknown order outcomes and all strategy modes before merging.

**No tests or live orders run.**
