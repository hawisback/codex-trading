# Working on this engine

Read `AGENTS.md` before changing or running trading code. All work and temporary
state must stay inside this repository. The AI gate, its veto authority, and cash
preservation on uncertainty are mandatory.

Runtime logs, daily trade journals and maintenance commands are described in
[DAILY_LOGS.md](docs/DAILY_LOGS.md). Logs and reports are observational; recovery
and broker mutations must not depend on the background logging worker.

## Development checks

From the repository root, using Python 3.10 or newer:

```powershell
python -m tools.checks
git diff --check
```

The check command requires no third-party Python packages. It parses application
and test sources without executing diagnostic scripts, checks direct import
boundaries, and runs the explicitly selected offline tests with network access
blocked. Unexpected network attempts fail the overall command even when trading
code catches the exception. Test state belongs in temporary directories under
this repository.

For formatting, linting, type checks and the same offline suite, use `python -m tools.quality`.
Pinned development dependencies are in `requirements-dev.txt`; the trading
runtime still needs no third-party Python packages. To install the development
tools entirely under the workspace in PowerShell:

```powershell
New-Item -ItemType Directory -Path .tools/tmp -Force | Out-Null
$env:TEMP = (Resolve-Path .tools/tmp).Path
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pip --isolated --disable-pip-version-check install --no-cache-dir --only-binary=:all: --target .tools/vendor -r requirements-dev.txt
python -m tools.quality
```

The quality command automatically uses `.tools/vendor` when present. An existing
development virtual environment with these dependencies also works. The pinned
tools are separate from live runtime imports.

Avoid broad test discovery from the repository root: several existing
`test_*.py` files are manual diagnostics or historical simulations that perform
work at import time. They are not part of the offline regression suite. Research
scripts can reference a database outside the permitted workspace; the development
checks never open it. Use an authorized local snapshot inside the repository for
any future historical validation, with actual AI consultation enabled.

Add offline regression modules to `tests/test_regression.py`, or add test cases
under `tests/test_architecture.py` for adapter contracts. Do not replace
`self.ai_consultant.evaluate(dossier)` in live or backtest runs. Existing gate
integration tests use the actual consultant; fake broker and news transports keep
these unit tests offline.

## Refactoring rules

- Keep root-level imports and CLI commands compatible while extracting modules.
- Preserve broker routes, payloads, request IDs, retry rules, timeouts, rounding,
  configuration precedence, JSON schema, and exception outcomes.
- Keep strategy/AI/policy decisions outside HTTP and persistence adapters.
- Depend on the small interfaces in `trading/ports.py`; assemble default concrete
  dependencies at the application boundary.
- Keep imports in new modules free of application I/O, environment mutation,
  logging configuration, and background-worker startup.
- Review a behavior change separately from a structural refactor. Configuration
  and documentation disagreements are not permission to change trading rules.
- Use the pre-refactor traces in `tests/fixtures/oms_reference.json` as fixed
  regression evidence. Do not regenerate them simply to make a refactor pass.

The GitHub workflow runs these checks on Windows and Linux with Python 3.10 and
3.14. It has read-only repository permissions, uses pinned action commits, and
requires no broker credentials or paid API services. Its matrix is configured;
local checks do not establish that remote jobs have passed.

See [the architecture review](docs/ARCHITECTURE_REVIEW.md) for the current
boundaries, policy discrepancies, and next refactoring steps.
See [the staged implementation record](docs/STAGED_REFACTOR.md) for the completed
service boundaries, replay usage and validation limits.
