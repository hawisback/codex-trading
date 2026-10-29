"""Compatibility entrypoint. Canonical implementation: research.calculators.calc_50k_oct05_week."""

if __name__ == "__main__":
    import runpy
    runpy.run_module("research.calculators.calc_50k_oct05_week", run_name="__main__")
else:
    from research.calculators.calc_50k_oct05_week import *  # noqa: F401,F403 - Preserve historical import names
