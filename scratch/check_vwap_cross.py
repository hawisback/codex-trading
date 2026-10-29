import sys
sys.path.append('.')

with open('logs/trader.log', 'r', encoding='utf-8') as f:
    lines = f.readlines()

today_lines = [l for l in lines if l.startswith('2026-10-13')]

for l in today_lines:
    time_part = l[11:19]
    if "14:18:00" <= time_part <= "14:25:00":
        print(l.rstrip())
