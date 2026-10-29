"""Compatibility entrypoint. Canonical implementation: research.audits.audit_trade_dossier."""

if __name__ == "__main__":
    import runpy
    runpy.run_module("research.audits.audit_trade_dossier", run_name="__main__")
else:
    from research.audits.audit_trade_dossier import *  # noqa: F401,F403 - Preserve historical import names
