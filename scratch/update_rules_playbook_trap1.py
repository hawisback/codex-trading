with open('config/rules_playbook.md', 'r', encoding='utf-8') as f:
    content = f.read()

target = """### Trap 1: The VWAP Blender & Midday Chop Trap
* **Discovered:** September 9–10 & July–August 2026 audits.
* **Pattern:** Two distinct variants:
  1. *Midday Flat VWAP (Dead Zone):* Between 11:30 AM and 01:15 PM IST (06:00 – 07:45 UTC), institutions pause for lunch. VWAP turns completely flat ($\\Delta\\text{VWAP} \\approx 0$).
  2. *Chronic VWAP Meat Grinder:* Price repeatedly crosses session VWAP ($\\ge 5\\text{ crosses in last 60 mins}$), whipping back and forth regardless of momentary spot distance.
* **Failure Mode:** In July & August, 15 out of 16 VWAP stops suffered from chronic VWAP crosses (6 to 13 crosses/hour). Alternating CE $\\to$ PE signals stop out repeatedly.
* **Guardrail Action:** **VETO ANY TRADE** if $\\ge 5\\text{ VWAP crosses in 60m}$ or flat VWAP midday dead zone, unless the setup is an institutional directional reversal expansion."""

replacement = """### Trap 1: [REMOVED] The VWAP Blender & Midday Chop Trap
* **Status:** **REMOVED / DEPRECATED** per empirical bottleneck audit & user directive.
* **Audit Finding:** In the October 2026 6-day audit across 75 candidates, Trap 1 blocked 15 trades: 7 were winners (+₹7,258.68 missed profit) and 8 were minor losses (-₹1,061.45 saved), creating a net drag of -₹6,197.23. Removing Trap 1 increased net sequential portfolio profit from +₹18,299.64 to +₹21,927.42 (+₹3,627.78 gain, 68.0% win rate).
* **Current Action:** **STAND-DOWN / NO VETO**. 2-minute MACD momentum signals with volume expansion are permitted during midday and around VWAP crossings."""

assert target in content, "Target Trap 1 text not found in rules_playbook.md"
new_content = content.replace(target, replacement, 1)

with open('config/rules_playbook.md', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("SUCCESSFULLY UPDATED rules_playbook.md")
