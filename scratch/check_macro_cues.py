import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, ".")
from market_intelligence import MarketIntelligence

with MarketIntelligence(start_worker=True) as mi:
    print("Fetching live global intermarket cues & RSS headlines...")
    mi.wait_until_ready(timeout=10.0)
    data = mi.get_market_intelligence()

print("=" * 80)
print(" 🌐 LIVE GLOBAL CUES & MACRO REPORT (OCTOBER 26, 2026)")
print("=" * 80)

cues = data.get("global_cues", {})
for k, v in cues.items():
    if not isinstance(v, dict):
        continue
    p = v.get("price")
    ch = v.get("change_pct")
    s = v.get("sentiment")
    ch_str = f"{ch:+.2f}%" if ch is not None else "N/A"
    p_str = f"{p:.2f}" if p is not None else "N/A"
    print(f"  • {k:<18} | Price: {p_str:<10} | Change: {ch_str:<8} | Sentiment: {s}")

print("-" * 80)
print(f"Global Macro Bias:   {data.get('global_bias')} (Score: {data.get('global_bias_score')})")
print(f"News Sentiment Bias: {data.get('news_bias')} (Score: {data.get('news_sentiment_score')})")
print("-" * 80)

print("\n📰 TOP LIVE FINANCIAL HEADLINES & CATALYSTS:")
catalysts = data.get("catalysts", [])
if catalysts:
    for c in catalysts[:10]:
        print(f"  • [{c.get('sentiment')}] {c.get('title')} ({c.get('source')})")
else:
    print("  (No extreme sentiment anomalies detected in headlines)")
print("=" * 80)
