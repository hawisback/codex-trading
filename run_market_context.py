import json
import sys
from datetime import datetime
from market_clock import MarketClock
from market_intelligence import MarketIntelligence
from trading.adapters.market_data import create_market_data

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def fetch_full_market_context():
    with MarketIntelligence() as intelligence:
        return _fetch_full_market_context(intelligence)


def _fetch_full_market_context(mi):
    print("=" * 65)
    print("DAILY MARKET & NEWS CONTEXT BRIEFING")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("=" * 65)

    # 1. Market Intelligence (Global Cues & Indian Financial News)
    client = create_market_data()
    try:
        snap = client.get_snapshot()
    finally:
        client.close()
    und = snap.get("underlying", {})
    spot_chg = float(und.get("change_pct", 0.0) or 0.0)

    if not mi.wait_until_ready(timeout=30):
        print("Market intelligence unavailable: required sources did not become fresh within 30 seconds.")
        print(mi.format_markdown(mi.get_market_intelligence(spot_change_pct=spot_chg)))
        return 1
    intel = mi.get_market_intelligence(spot_change_pct=spot_chg)

    global_cues = intel.get("global_cues", {})
    news = intel.get("news", {})

    print("\n[1] GLOBAL INTERMARKET CUES:")
    print(f"  - Overall Global Bias: {global_cues.get('global_bias')}")
    print(f"  - Macro Impact Score:  {global_cues.get('score')}")
    items = global_cues.get("items", {})
    for name, data in items.items():
        if isinstance(data, dict):
            chg = data.get("change_pct", 0.0)
            price = data.get("price")
            sign = "+" if chg > 0 else ""
            print(f"  * {name:<12}: {price} ({sign}{chg}%)")

    print("\n[2] LIVE FINANCIAL NEWS & SENTIMENT:")
    print(f"  - News Bias:       {news.get('news_bias')}")
    print(f"  - Sentiment Score: {news.get('sentiment_score')}")
    print(f"  - Total Headlines: {news.get('total_headlines')}")

    print("\n[3] KEY CATALYSTS & HEAVYWEIGHT IMPACT:")
    catalysts = news.get("catalysts", [])
    if catalysts:
        for c in catalysts:
            print(f"  - [{c.get('sentiment')}] {c.get('title')} ({c.get('source')})")
    else:
        print("  - No major breaking alerts flagged in the top catalyst filter.")

    print("\n[4] TOP HEADLINES:")
    headlines = news.get("headlines", [])
    for h in headlines[:8]:
        print(f"  * [{h.get('sentiment')}] {h.get('title')}")

    # 2. Local Market APIs (Kite live feed)
    client = create_market_data()
    try:
        snap = client.get_snapshot()
        opts = client.get_options(strike_window=4)
    finally:
        client.close()
    und = snap.get("underlying", {})
    opt_sum = opts.get("summary", {})

    print("\n[5] NIFTY 50 LIVE SPOT & STRUCTURE (09:15-09:20 IST):")
    print(f"  - Spot Price:    ₹{und.get('last_price')}")
    print(f"  - Day Open:      ₹{und.get('open')}")
    print(f"  - Day High:      ₹{und.get('high')}")
    print(f"  - Day Low:       ₹{und.get('low')}")
    print(f"  - Prev Close:    ₹{und.get('close')}")
    print(f"  - Change:        +{und.get('change_pct')}%")
    high_val = und.get('high')
    low_val = und.get('low')
    spread = round(float(high_val) - float(low_val), 2) if (high_val is not None and low_val is not None) else 0.0
    print(f"  - Range Spread:  {spread} pts")

    exp_str = str(opts.get('expiry') or '')
    try:
        exp_day_name = datetime.strptime(exp_str, "%Y-%m-%d").strftime("%A") if exp_str else "Unknown"
    except Exception:
        exp_day_name = "Weekly"
    print(f"  - Expiry:        {exp_str} ({exp_day_name} 0DTE Expiry)" if exp_str == MarketClock.today_ist_str() else f"  - Expiry:        {exp_str} ({exp_day_name} Expiry)")
    print(f"  - ATM Strike:    {opt_sum.get('atm_strike')}")
    print(f"  - PCR (OI):      {opt_sum.get('pcr_oi')}")
    print(f"  - PCR (Volume):  {opt_sum.get('pcr_volume')}")
    call_oi = opt_sum.get('call_open_interest')
    put_oi = opt_sum.get('put_open_interest')
    call_oi_str = f"{call_oi:,}" if isinstance(call_oi, (int, float)) else "N/A"
    put_oi_str = f"{put_oi:,}" if isinstance(put_oi, (int, float)) else "N/A"
    print(f"  - Total Call OI: {call_oi_str}")
    print(f"  - Total Put OI:  {put_oi_str}")


    print("\n[7] OPTION CHAIN BID/ASK & PREMIUMS:")
    for s in opts.get("strikes", []):
        strike_val = s.get("strike")
        ce = s.get("call", {})
        pe = s.get("put", {})
        print(f"  Strike {int(strike_val)}: CE LTP=₹{ce.get('ltp')} (bid: {ce.get('bid')}, ask: {ce.get('ask')}) | PE LTP=₹{pe.get('ltp')} (bid: {pe.get('bid')}, ask: {pe.get('ask')})")

    # 3. Macro / Technical Assessment
    print("\n" + "=" * 65)
    print("CONTEXT SUMMARY & MORNING PLAYBOOK:")
    spot_val = und.get("last_price")
    pcr_val = opt_sum.get("pcr_oi")
    if spot_val is not None:
        spot = float(spot_val)
        pcr = float(pcr_val if pcr_val is not None else 1.0)
        atm = opt_sum.get("atm_strike", 22650)
        print(f"  - Spot Level: Currently trading at {spot:.1f} (High: {und.get('high')}, Low: {und.get('low')}).")
        if pcr < 0.8:
            print("  - Order Flow Bias: PCR is < 0.80, indicating heavy Call writing / resistance above.")
        elif pcr > 1.2:
            print("  - Order Flow Bias: PCR is > 1.20, indicating strong Put writing support underneath.")
        else:
            print("  - Order Flow Bias: PCR is neutral/balanced (0.80 - 1.20).")
    else:
        print("  - Spot & Options data: Broker execution server currently offline (pre-market).")
    print("  - Strategy Alignment: Ready for market open; awaiting morning pre-flight & live session.")
    print("=" * 65)
    return 0

if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    sys.exit(fetch_full_market_context() or 0)
