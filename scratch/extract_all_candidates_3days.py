import json
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from backtest_ai_opportunity_radar import AIOpportunityRadar

cfg = StrategyConfig.load_from_config("institutional_pullback")
radar = AIOpportunityRadar()

for dt in ["2026-10-21", "2026-10-22"]:
    eng = BacktestEngine(target_date=dt)
    print(f"\n==================== CANDIDATES FOR {dt} ====================")
    spot_closes = []
    spot_typicals = []
    rsi_history = []
    day_open = eng.spot_candles[0]["open"]
    
    candidates = []
    for idx, bar in enumerate(eng.spot_candles):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        spot_closes.append(close)
        spot_typicals.append((high + low + close) / 3.0)
        session_vwap = sum(spot_typicals) / len(spot_typicals)
        bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
        ema9 = eng.calculate_ema(bars_5m, 9)
        ema20 = eng.calculate_ema(bars_5m, 20)
        rsi = eng.calculate_rsi(spot_closes, 14)
        rsi_history.append(rsi)
        recent_15m = eng.spot_candles[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)
        
        opp = radar.evaluate(
            bar_idx=idx, bar=bar, all_bars=eng.spot_candles,
            spot_closes=spot_closes, session_vwap=session_vwap,
            ema9=ema9, ema20=ema20, rsi=rsi, rsi_history=rsi_history,
            day_open=day_open, box_high=box_high, box_low=box_low
        )
        if opp.action in ["BUY_CE", "BUY_PE"] and opp.conviction >= 80:
            sym, strike = eng.select_contract(close, "CE" if opp.action == "BUY_CE" else "PE", mode=cfg.strike_selection)
            _, _, opt_entry = eng.get_option_bar(sym, strike, "CE" if opp.action == "BUY_CE" else "PE", idx, bar)
            dossier = generate_market_dossier(
                target_date=dt, candles=eng.spot_candles, current_bar_idx=idx,
                direction="CE" if opp.action == "BUY_CE" else "PE", symbol=sym, strike=strike,
                option_entry_price=opt_entry, trade_history=[], days_to_expiry=eng.get_expiry_days(),
                is_expiry_0dte=False
            )
            candidates.append({
                "bar_idx": idx,
                "time_utc": bar["start_time"][11:19],
                "time_ist": dossier.time_ist,
                "action": opp.action,
                "regime": opp.regime,
                "strike": strike,
                "opt_entry": opt_entry,
                "spot": close,
                "vwap": session_vwap,
                "dist_vwap": abs(close - session_vwap),
                "slope_15m": dossier.vwap_slope_15m,
                "phase": dossier.session_phase,
                "ema9": ema9,
                "ema20": ema20,
                "rsi": rsi,
                "box_spread": box_high - box_low,
                "thesis": opp.thesis
            })
    print(f"Total raw radar candidates: {len(candidates)}")
    for c in candidates:
        print(f"  [{c['time_ist']}] {c['action']} {c['strike']} @ {c['opt_entry']:.2f} ({c['regime']}) | Spot: {c['spot']:.1f} | VWAP: {c['vwap']:.1f} (Dist: {c['dist_vwap']:.1f}) | Slope: {c['slope_15m']:+.3f} | Phase: {c['phase']}")
