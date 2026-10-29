"""Compatibility entrypoint. Canonical implementation: research.calculators.calc_10k_compound."""

if __name__ == "__main__":
    import runpy
    runpy.run_module("research.calculators.calc_10k_compound", run_name="__main__")
else:
    from research.calculators.calc_10k_compound import *  # noqa: F401,F403 - Preserve historical import names
