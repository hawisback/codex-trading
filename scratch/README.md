# Research scripts and historical implementation helpers

This directory includes exploratory analyses, dated market-data fetchers, and
one-off source/configuration patch scripts retained with the Path A work.
These files are not production entry points or the offline regression suite.

Some older analyses use illustrative pricing, counterfactual policy overrides,
or names that describe deterministic rules as AI. Such results are not evidence
of Antigravity AI Companion performance. Never use those overrides to bypass a
consultant veto in a live or backtest run. True AI evaluation requires the
Antigravity companion in chat mode.

The `update_*`, `register_*`, `remove_*`, and `fix_*` scripts are historical
implementation helpers. Reapplying them can overwrite the reviewed engine and
its safety fixes. Fetch scripts may contact broker endpoints and write data.
The remaining scratch scripts were syntax-checked for archival purposes; they
were not executed or included in the production test-pass claim.

The corrected comparison entry point is `compare_paradigms.py`, using
`grid_search_macd_rsi_volume.py` and the verified history helpers. It requires
exact contract metadata and timestamps and reports insufficient verified data
when those inputs are missing. Its OHLC estimates are deterministic research,
not verified broker fills or live-equivalent returns.

Run `python -m tools.checks` from the repository root for the maintained offline
tests. Follow `docs/AI_COMPANION_PAIR_TRADING.md` for the production workflow.
Never launch the engine or apply patch scripts merely to test an analysis.
