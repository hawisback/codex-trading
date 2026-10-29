with open("AGENTS.md", "r", encoding="utf-8") as f:
    content = f.read()

target = """### 1. Deterministic Rules Mode (Algorithmic Heuristics, Zero AI):
To launch the live engine on **Zerodha Kite** with in-process market data:
```powershell
python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy ai_opportunity_radar --ai-mode rules --wait-until-market-open
```
*(Note: `--ai-mode playbook` remains supported as an alias for `--ai-mode rules`)*.

To launch on **ICICI Breeze**:
```powershell
python nifty_trader_scheduler.py --broker breeze --market-data-broker breeze --live --strategy ai_opportunity_radar --ai-mode rules --wait-until-market-open
```

### 2. Antigravity AI Companion Mode (True Neural AI Pair-Trading):
To launch with interactive Antigravity AI Chat Pair-Trading directly in the IDE:
1. Arm the AI Watcher daemon:
   ```powershell
   python tools/watch_consultation.py
   ```
2. Launch the live scheduler:
   ```powershell
   python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy ai_opportunity_radar --ai-mode chat --wait-until-market-open
   ```"""

replacement = """### 1. Deterministic Rules Mode (Algorithmic Heuristics, Zero AI):
To launch the live engine on **Zerodha Kite** with in-process market data (Strategy 5: Path A 2m MACD Momentum):
```powershell
python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode rules --wait-until-market-open
```
*(Note: `--ai-mode playbook` remains supported as an alias for `--ai-mode rules`)*.

To launch on **ICICI Breeze**:
```powershell
python nifty_trader_scheduler.py --broker breeze --market-data-broker breeze --live --strategy macd_momentum --ai-mode rules --wait-until-market-open
```

### 2. Antigravity AI Companion Mode (True Neural AI Pair-Trading - Path A Recommended):
To launch with interactive Antigravity AI Chat Pair-Trading directly in the IDE:
1. Arm the AI Watcher daemon:
   ```powershell
   python tools/watch_consultation.py
   ```
2. Launch the live scheduler:
   ```powershell
   python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode chat --wait-until-market-open
   ```"""

assert target in content, "Target not found in AGENTS.md"
new_content = content.replace(target, replacement, 1)

with open("AGENTS.md", "w", encoding="utf-8") as f:
    f.write(new_content)

print("SUCCESSFULLY UPDATED AGENTS.md")
