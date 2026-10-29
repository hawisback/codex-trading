import io

with open('config/rules_playbook.md', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    if lines[i].startswith("### Trap 7: The Counter-Trend VWAP Slope Trap"):
        # Replace Trap 7 and Trap 8
        replacement_block = """### Trap 7: The Counter-Trend VWAP Slope Trap & Reversal Inflection Exception
* **Discovered:** Forensic Audit of June 2026 (15 Sessions), Refined October 2026 Audit (31 Candidates).
* **Pattern:** Technical signal generates `BUY_PE` while Session VWAP is sloping upward, or `BUY_CE` while Session VWAP is sloping downward.
* **Failure Mode:** 17 out of 31 raw counter-slope trades failed, losing $-₹10,514.27$ when fighting runaway freight trains ($|\\text{Slope}| > 0.85\\text{ pts/min}$) or extreme dislocations ($> 140\\text{ pts}$). However, 14 counter-slope trades were explosive institutional V-reversals ($+₹14,532.00$ missed alpha, up to $+50.9\\%$ gain).
* **Refined Guardrail Action (Precision Inflection Filter):**
  1. **Unconditional Veto:** Veto counter-slope entries if $|\\text{Slope}| > 0.85\\text{ pts/min}$ (freight train avalanche), spot distance from VWAP $> 140\\text{ pts}$ (deep unhinged dislocation), or the 2m trigger candle closes against the trade direction.
  2. **Reversal Inflection Approval:** Approve counter-slope trades as high-probability Mean-Reversion Inflections when $|\\text{Slope}| \\le 0.85\\text{ pts/min}$, spot distance $\\le 140\\text{ pts}$, and the 2m trigger candle closes in the direction of the trade (green for CE, red for PE).

### Trap 8: The Climax Overextension Trap (Parabolic Rubber Band)
* **Discovered:** Forensic Audit of June & July 2026.
* **Pattern:** Entering fresh option purchases when spot is already $\\ge 75\\text{ pts}$ away from Session VWAP in the direction of the move.
* **Failure Mode:** Extreme distance represents a stretched rubber band. Even in strong trends, mean-reversion pullbacks back towards EMA20/VWAP cause severe initial option drawdown, triggering stops.
* **Guardrail Action:** **VETO CHASING ENTRIES** when spot distance from Session VWAP exceeds $75\\text{ pts}$ in the direction away from VWAP (e.g. buying CE when spot is $>75$ pts above VWAP, or PE when spot is $>75$ pts below VWAP). Validated Reversal Inflections moving *back towards* VWAP are governed by Trap 7's 140 pt runway limit.
"""
        new_lines.append(replacement_block + "\n")
        # Skip until Trap 9
        while i < len(lines) and not lines[i].startswith("### Trap 9:"):
            i += 1
        continue
    new_lines.append(lines[i])
    i += 1

with open('config/rules_playbook.md', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("SUCCESSFULLY REPLACED TRAP 7 & 8 IN RULES_PLAYBOOK.MD")
