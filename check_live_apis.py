import json
import os
import sys
from datetime import datetime
from execution_client import AIExecutionClient
from trading.adapters.market_data import create_market_data
from market_clock import MarketClock

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def run_diagnostics():
    market = create_market_data()
    try:
        return _run_diagnostics(market)
    finally:
        market.close()


def _run_diagnostics(market):
    client = AIExecutionClient()
    print("=" * 60)
    print("LIVE API READ-ONLY DIAGNOSTIC REPORT")
    print(f"Report Timestamp: {MarketClock.now_ist_str()}")
    print("=" * 60)

    # 0. Market Clock & Session Timing
    mins_from_open, mins_to_close = MarketClock.get_session_minutes()
    is_open = MarketClock.is_market_open()
    phase = MarketClock.get_session_phase()
    allowed, allow_reason = MarketClock.is_new_trade_allowed()
    sec_to_open = MarketClock.get_seconds_until_next_open()
    next_open = MarketClock.get_next_open_datetime()

    print("\n[0] INSTITUTIONAL MARKET CLOCK (IST):")
    print(f"  - Current Time:     {MarketClock.now_ist_str()}")
    print(f"  - Session Phase:    {phase}")
    print(f"  - Session Progress: Min {max(0, mins_from_open)} of 375 ({mins_to_close} mins to close)")
    print(f"  - Market Open Now:  {'YES (Live Exchange)' if is_open else 'NO (Exchange Closed)'}")
    print(f"  - Trading Allowed:  {'YES' if allowed else 'NO'} ({allow_reason})")
    if not is_open:
        print(f"  - Next Market Open: {next_open.strftime('%A %Y-%m-%d 09:15:00 IST')} (in {sec_to_open/3600:.1f} hours)")

    # 1. Execution Status
    st = client.get_status()
    print("\n[1] EXECUTION STATUS & AUTH:")
    print(f"  - Active Mode: {st.get('mode')}")
    print(f"  - Execution Enabled: {st.get('execution_enabled')}")
    print(f"  - Live Capability Enabled: {st.get('live_capability_enabled')}")
    print(f"  - Live Authorized: {st.get('live_authorized')} ({st.get('live_authorization_reason')})")
    print(f"  - Execution Broker: {st.get('execution_broker')}")
    print(f"  - Paper Simulation: {st.get('paper_simulation')}")

    # 2. Broker Sessions
    sessions = client.get_broker_sessions()
    print("\n[2] BROKER SESSIONS:")
    for b_name in ["kite", "breeze"]:
        b_info = sessions.get(b_name)
        if isinstance(b_info, dict):
            print(f"  - {b_name.upper()}: Status={b_info.get('status')} | Connected={b_info.get('connected')} | Expires={b_info.get('expires_at')}")

    # 3. Account Funds & Margin
    acc = client._request("GET", "/account/context", with_auth=True) or {}
    broker_live = acc.get("broker_live") or {}
    funds = broker_live.get("funds") or {}
    positions = broker_live.get("positions") or []
    print("\n[3] LIVE BROKER ACCOUNT CAPITAL (KITE):")
    print(f"  - Available Margin: ₹{funds.get('available_margin', 'N/A')}")
    print(f"  - Total Cash:       ₹{funds.get('total_cash', 'N/A')}")
    print(f"  - Used Margin:      ₹{funds.get('used_margin', 'N/A')}")
    print(f"  - Unrealized M2M:   ₹{funds.get('unrealized_m2m', 'N/A')}")
    print(f"  - Currency:         {funds.get('currency', 'INR')}")
    open_positions = [p for p in positions if int(p.get("quantity") or 0) != 0]
    print(f"  - Broker Positions: {len(open_positions)} open ({len(positions)} total today)")

    # 4. Active Journal / AI Positions
    pos = client.get_positions()
    orders = client.get_orders()
    pos_count = len(pos if isinstance(pos, list) else pos.get("positions", []))
    orders_count = len(orders if isinstance(orders, list) else orders.get("orders", []))
    print("\n[4] AI JOURNAL & ORDERS:")
    print(f"  - Active Journal Positions: {pos_count}")
    print(f"  - Recent Orders Count: {orders_count}")

    # 5. Market Feeds & Data Quality
    dq = market.get_data_quality()
    mf = dq.get("market_feed", {})
    ef = dq.get("execution_feed", {})
    nq = dq.get("nifty_quote", {})
    print("\n[5] MARKET DATA QUALITY:")
    print(f"  - Market Feed: Status={mf.get('status')} | Latency={mf.get('latency_sec')}s | Last Tick={mf.get('last_tick_time')}")
    print(f"  - Execution Feed: Healthy={ef.get('healthy')} | Status={ef.get('status')}")
    print(f"  - NIFTY Quote Fresh: {nq.get('fresh')} | Latency={nq.get('age_seconds')}s")

    # 6. NIFTY Snapshot & Spot Price
    snap = market.get_snapshot()
    und = snap.get("underlying", {})
    print("\n[6] NIFTY 50 SPOT & MARKET OPEN:")
    print(f"  - Spot Price: ₹{und.get('last_price', 'N/A')}")
    print(f"  - High: ₹{und.get('high', 'N/A')} | Low: ₹{und.get('low', 'N/A')} | Open: ₹{und.get('open', 'N/A')} | Prev Close: ₹{und.get('close', 'N/A')}")
    print(f"  - Net Change: {und.get('change_pct', 'N/A')}%")

    # 7. Options Chain & Nearest Expiry
    opts = market.get_options(strike_window=3)
    opt_summary = opts.get("summary", {})
    print("\n[7] OPTION CHAIN (EXPIRY: " + str(opts.get("expiry")) + "):")
    print(f"  - ATM Strike: {opt_summary.get('atm_strike')}")
    print(f"  - PCR (OI): {opt_summary.get('pcr_oi')}")
    print(f"  - PCR (Volume): {opt_summary.get('pcr_volume')}")
    print(f"  - Strikes Loaded:")
    for s in opts.get("strikes", [])[:5]:
        strike_val = s.get("strike")
        ce = s.get("call", {})
        pe = s.get("put", {})
        print(f"    * Strike {strike_val}: CALL LTP={ce.get('ltp')} (bid: {ce.get('bid')}, ask: {ce.get('ask')}) | PUT LTP={pe.get('ltp')} (bid: {pe.get('bid')}, ask: {pe.get('ask')})")

    print("\n" + "=" * 60)
    print("ALL READ-ONLY APIS OPERATIONAL - ZERO TRADES PLACED")
    print("=" * 60)

if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    run_diagnostics()
