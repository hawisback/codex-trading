with open('AGENTS.md', 'r', encoding='utf-8') as f:
    content = f.read()

target = '1. **Trap 1: The VWAP Blender & Midday Dead Zone** (Veto if $\ge 5$ crosses in 60m or flat VWAP 11:30–13:15 IST).'
replacement = '1. **Trap 1: The VWAP Blender & Midday Dead Zone** [REMOVED - Deprecated per user directive & audit to unlock midday alpha].'

assert target in content, "Target Trap 1 text not found in AGENTS.md"
new_content = content.replace(target, replacement, 1)

with open('AGENTS.md', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("SUCCESSFULLY UPDATED AGENTS.md")
