"""Backward-compatible launcher; implementation moved to research/calculators.

Historical simulation only. This script does not describe live sizing rules.
"""

from research.calculators.calc_50k_oct05_week import run_calculation

if __name__ == "__main__":
    run_calculation()
