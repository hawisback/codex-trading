# Research workspace

This package contains historical analysis and backtesting tools, **not the live trading runtime**. Do not use historical simulation sizing as a source of live available margin or order quantity.

## First migrated scripts

| Original compatibility command | Canonical module command |
| --- | --- |
| `python calc_10k_compound.py` | `python -m research.calculators.calc_10k_compound` |
| `python calc_50k_oct05_week.py` | `python -m research.calculators.calc_50k_oct05_week` |

Execute from the repository root, with explicit historical data dependencies installed. The original root script names remain **thin compatibility wrappers**. The actual implementations now live in `research/calculators`. No scripts were run as part of this migration.

## Proposed layout

- `research/calculators/` – historical capital and fee models.
- `research/audits/` – reviewed historical trade audits (not yet migrated).
- `research/backtests/` – standalone backtest experiments (not yet migrated).
- `research/data/` – only metadata and nonsecret fixture schemas; raw data stays gitignored.
- `tests/` – offline deterministic regression tests and fixture references.
- `tools/` – supported operational diagnostics, preflight commands and read-only inspection.
- `trading/` – production domain, applications, adapters, ports and configuration.

We deliberately **do not bulk-move** root scripts that may have external references, import-time side effects, file-relative data dependencies, or broker access. Migrations require an entrypoint inventory, compatibility wrapper, offline validation and a separate review. Never delete active broker journal or position-state artifacts in the name of cleanup.
