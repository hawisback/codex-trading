import sys
sys.path.insert(0, ".")
import json
from collections import Counter
import scratch.run_full_ai_companion_30_sessions as s

trading_cfg = json.load(open("config/trading.json"))
strats_cfg = json.load(open("config/strategies.json"))
strat_cfg = strats_cfg["strategies"]["macd_momentum"]
strategy = s.MacdMomentumStrategy(strat_cfg)
consultant = s.AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)

veto_counts = Counter()
for d_idx, dt_str in enumerate(s.DATES):
    spot_bars, opt_candles = s.r.load_session_data(dt_str)
    if not spot_bars or len(spot_bars) < 60: continue
    prior_bars = []
    if d_idx > 0: prior_bars, _ = s.r.load_session_data(s.DATES[d_idx - 1])
    if not prior_bars: prior_bars = spot_bars[:60]
    warmup_candles = prior_bars[-100:] if len(prior_bars) >= 100 else prior_bars
    
    target_d = s.datetime.strptime(dt_str, "%Y-%m-%d").date()
    expiry_d = target_d + s.timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
    days_base = max(0.1, float((expiry_d - target_d).days))
    is_0dte = (target_d.weekday() == 1)
    
    clean_d = dt_str.replace("-", "")
    fut_file = f"data/fut_candles_{clean_d}.json"
    fut_bars = json.load(open(fut_file, "r")) if s.os.path.exists(fut_file) else []
    closes_1m = [b["close"] for b in spot_bars]
    vols_1m = [b.get("volume", 1000) for b in fut_bars] if fut_bars and len(fut_bars) == len(spot_bars) else [b.get("volume", 1000) for b in spot_bars]
    
    for idx in range(15, min(len(spot_bars) - 1, 300)):
        bars_so_far = spot_bars[:idx + 1]
        t_now = s.exchange_time(bars_so_far[-1]["start_time"]) + s.timedelta(minutes=1)
        time_hm = t_now.strftime("%H:%M")
        if time_hm >= "14:15": break
        if "13:00" <= time_hm < "13:15": continue
        vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
        with s.MarketClock.at(t_now):
            ctx = {"candles_1m": bars_so_far, "prior_session_warmup_candles": warmup_candles, "exchange_holidays": [], "spot": bars_so_far[-1]["close"], "session_vwap": vwap}
            candidate = strategy.evaluate(ctx)
        if candidate.signal == "NEUTRAL": continue
        direction = candidate.signal.replace("BUY_", "")
        spot_p = bars_so_far[-1]["close"]
        strike = s.select_strike(spot_p, direction, "STRICT_ITM")
        if strike == spot_p: strike += -50 if direction == "CE" else 50
        strike_macd_data = s.r.compute_strike_macd(spot_bars, strike, direction, idx, days_base, opt_candles)
        c_vol = sum(vols_1m[max(0, idx - 4): idx + 1]) / 5.0
        p_vol = sum(vols_1m[max(0, idx - 24): max(1, idx - 4)]) / 20.0 if idx >= 24 else c_vol
        vol_ratio = c_vol / p_vol if p_vol > 0 else 1.0
        sub_closes = closes_1m[:idx + 1]
        deltas = [sub_closes[k] - sub_closes[k - 1] for k in range(1, len(sub_closes))]
        gains = [max(0.0, d) for d in deltas[-14:]]
        losses = [max(0.0, -d) for d in deltas[-14:]]
        avg_g = sum(gains) / 14.0 if gains else 0
        avg_l = sum(losses) / 14.0 if losses else 0
        rsi_val = 100.0 - (100.0 / (1.0 + (avg_g / avg_l))) if avg_l > 0 else 50.0
        next_idx = idx + 1
        if next_idx >= len(spot_bars) - 1: continue
        entry_p = s.r.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
        if entry_p <= 5.0: continue
        dossier = s.generate_market_dossier(target_date=dt_str, candles=bars_so_far, current_bar_idx=idx, direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike, option_entry_price=entry_p, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte)
        dossier.setup_type = "MACD_2M_MOMENTUM"
        rules_verdict = consultant.evaluate(dossier)
        if not rules_verdict.is_approved:
            veto_counts["Rules: " + rules_verdict.reasoning[:35]] += 1
            continue
        ai_approved, ai_reason, ai_trap, ai_conf = s.evaluate_ai_companion_dossier(dossier, strike_macd_data, vol_ratio, rsi_val)
        if not ai_approved:
            veto_counts["AI: " + ai_trap] += 1
        else:
            veto_counts["APPROVED"] += 1

print("\n--- VETO REASON SUMMARY ---")
for k, v in veto_counts.most_common():
    print(f"{v:3d} : {k}")
