"""Compatibility entrypoint. Canonical implementation: research.audits.inspect_oct05."""

if __name__ == "__main__":
    import runpy
    runpy.run_module("research.audits.inspect_oct05", run_name="__main__")
else:
    from research.audits.inspect_oct05 import *  # noqa: F401,F403 - Preserve historical import names
