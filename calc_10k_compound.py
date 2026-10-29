"""Backward-compatible launcher; implementation moved to research/calculators.

Historical simulation only. This script does not describe live sizing rules.
"""

from research.calculators.calc_10k_compound import run_10k_compound

if __name__ == "__main__":
    run_10k_compound()
