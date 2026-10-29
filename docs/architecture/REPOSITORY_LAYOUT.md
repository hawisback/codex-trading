# Repository layout — incremental consolidation

**Date:** 2026-10-29  
**Status:** first cleanup increment is committed on an unmerged branch; **no tests have run**. The repository is not yet fully consolidated.

## Canonical locations

| Directory | Responsibility | Stability |
| --- | --- | --- |
| `trading/domain/` | Pure risk/lot policy, technical math, state and value objects | Production |
| `trading/application/` | Session workflows, entry, selection, monitoring and stop orchestration | Production |
| `trading/adapters/` | Execution brokers, market sources, gateways, repositories | Production |
| `trading/strategies/` | Pure signals and strategy registry | Production |
| `trading/ports.py` | Stable dependency interfaces | Production |
| `config/` | Runtime JSON, example secrets and deterministic rule text | Production config |
| `tools/` | Explicit operational tooling and source-only inspection | Operator tools |
| `tests/` and `tests/fixtures/` | Offline tests and frozen examples | Regression suite |
| `research/calculators/` | Historical capital and fee simulations, not live sizing | Historical |
| `research/audits/` | Historical dossier and rule-variant experiments | Historical |
| `research/backtests/` | Reserved for independently audited backtest scripts | Future migration |
| `docs/architecture/` and `docs/adr/` | Baselines, migration plans, policy evidence and decisions | Engineering |

## Root modules deliberately retained

- `nifty_trader_scheduler.py` — documented supported CLI and compatibility façade. Do not move until all user/automation launch paths are catalogued.
- `position_lifecycle.py` — stateful OMS, pending extraction; moving it prematurely risks breaking recovery, imports and state paths.
- `execution_client.py` — current proxy gateway compatibility contract.
- `ai_consultant.py` — mandatory consultation/veto gate (deterministic rules vs interactive chat).
- `market_clock.py`, `market_intelligence.py`, `entry_policy.py`, `backtest_engine.py`, `ai_context_dossier.py` — mixed historical/public contracts; migrate only behind explicit adapters and compatibility checks.
- `start_scheduler.ps1` — documented operator entrypoint.
- Root `test_*.py` manual scripts are **not** all safe unit tests. Do not move into the automatically discovered suite until side effects are characterized.

## Migration batch 1 (done, no tests executed)

| Original root path | Canonical implementation |
| --- | --- |
| `calc_10k_compound.py` | `research/calculators/calc_10k_compound.py` |
| `calc_50k_oct05_week.py` | `research/calculators/calc_50k_oct05_week.py` |
| `audit_trade_dossier.py` | `research/audits/audit_trade_dossier.py` |
| `inspect_oct05.py` | `research/audits/inspect_oct05.py` |

The old root paths remain thin compatibility wrappers, supporting existing direct script execution and re-exporting historical import names. Therefore the number of root file *names* has not dropped yet; their implementation bodies have moved. This is intentional until runbook references, user shortcuts and importer compatibility can be verified. New research code should go only in the research package.

## Proposed cleanup sequence

1. Audit which root scripts import other root scripts or rely on `__file__` relative paths, historical credentials, network access, or local databases.
2. Move individual scripts to `research/backtests/`, `research/audits/` and `research/calculators/` **with compatibility launchers** and document commands.
3. Use offline import/CLI validations, source-map checks and owner-run tests. Never broad-discover root diagnostic scripts.
4. Only **delete legacy compatibility wrappers** once the owner confirms old commands and external schedulers are migrated. Removing wrappers before validation is unnecessary breakage.
5. Keep runtime state `logs/`, account journals, `.env`, broker tokens and raw market archives outside version control; never “clean up” state with live positions.
6. Consolidate production root modules after OMS state transitions and broker boundaries are verified, preferably without changing public CLI names.

## Policy migration implications

- `trading/domain/lot_policy.py` now owns broker-margin tier sizing. Research scripts with old historical capital assumptions do **not** define live limits.
- The previous per-strategy `compounding` arrays remain in `config/strategies.json` for historical research consumers, but the live quantity calculator no longer uses them. Remove these only after a compatibility audit.
- POL-05 daily loss stop and POL-06 universal initial stop/trailing values are **not yet defined**, so they are deliberately excluded from this layout-only work.
- A LIVE production process still requires broker-specific arming, account reconciliation, real consultation and protective OMS. No clean-up work should disable these safeguards.

**No production release should be made from the unverified branch.**
