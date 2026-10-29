# Historical audit modules

This directory contains historical replay/audit experiments, **not live trading or reusable gatekeeper implementations**.

- `audit_trade_dossier.py` – historical date/trade dossier inspector; run with `python -m research.audits.audit_trade_dossier --date YYYY-MM-DD --trade N`.
- `inspect_oct05.py` – historical October 2026 comparison; run with `python -m research.audits.inspect_oct05`.

Original root names remain compatibility launchers. Other root audit scripts require case-by-case dependency and data-path review before moving. These historical consultant variants must never replace the actual live `AIConsultant.evaluate` gate.

No audit, test or broker command was executed during this migration.
