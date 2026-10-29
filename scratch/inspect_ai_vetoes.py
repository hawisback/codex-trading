import sys
sys.path.insert(0, ".")
import json
import scratch.run_full_ai_backtest_with_analysis as a

trading_cfg = json.load(open("config/trading.json"))
trading_cfg["option_selection"]["max_option_premium"] = 220.0
strats_cfg = json.load(open("config/strategies.json"))
strat_cfg = strats_cfg["strategies"]["macd_momentum"]
strategy = a.MacdMomentumStrategy(strat_cfg)
consultant = a.AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)

res = a.run_simulation(enable_ai_companion=True)
consultations = res["consultations"]

vetoed = [c for c in consultations if c["verdict"] == "VETOED"]
print(f"Total Vetoed Candidates: {len(vetoed)}")

from collections import Counter
c_reasons = Counter()
for v in vetoed:
    c_reasons[v["reviewer"] + ": " + v["reason"][:45]] += 1

print("\nTop Veto Categories:")
for k, cnt in c_reasons.most_common(15):
    print(f"  {cnt:2d} : {k}")

print("\nAudited Sample of Vetoed Candidates:")
for idx, v in enumerate(vetoed[:20], 1):
    print(f"  {idx:2d}. {v['date']} {v['time']} | {v['signal']} {v['strike']} | By: {v['reviewer']} | Reason: {v['reason']}")
