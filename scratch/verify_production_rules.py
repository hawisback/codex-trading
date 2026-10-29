import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from trading.bootstrap import configure_console
configure_console()
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict

class ProductionConsultant(AIConsultant):
    def _evaluate_playbook(self, d) -> AIVerdict:
        v = super()._evaluate_playbook(d)
        if not v.is_approved:
            return v
        now_ts = "production"
        
        # 1. Climax Overextension Cap (>= 75 pts from VWAP)
        if d.vwap_distance_pts >= 75.0:
            return AIVerdict(False, "VETOED", 90, "Trap 8: Climax Overextension (>= 75 pts)", "Rubber band stretched", "tight_ema20", now_ts)
            
        # 2. Overbought Call Exhaustion at Day High (RSI >= 70 within 12 pts of high)
        if d.direction == "CE" and d.rsi_1m >= 70.0 and d.distance_to_day_extreme <= 12.0:
            return AIVerdict(False, "VETOED", 90, "Trap 3: Overbought Call Top Chasing", "Buying CE at day high with RSI >= 70", "tight_ema20", now_ts)
            
        # 3. Dead Ribbon Compression in Midday on Non-Expiry Days (< 2 pts)
        if not d.is_expiry_0dte and abs(d.ema_spread_5m) < 2.0 and "MIDDAY" in d.session_phase:
            return AIVerdict(False, "VETOED", 85, "Trap 6: Dead Midday Ribbon Compression (< 2 pts)", "5m EMA spread < 2 pts", "tight_ema20", now_ts)
            
        # 4. Non-Expiry Late-Day Lockout (Post-14:30)
        if not d.is_expiry_0dte and d.minutes_to_close <= 60:
            return AIVerdict(False, "VETOED", 90, "Trap 5: Non-Expiry Late-Day Lockout (Post-14:30)", "Post-14:30 on non-expiry day", "standard", now_ts)
            
        # 5. Protect Alpha on First Loss after Big Win (>= ₹1,800)
        if d.realized_pnl_today >= 1800.0 and d.consecutive_losses_today >= 1 and d.minutes_from_open >= 195:
            return AIVerdict(False, "VETOED", 95, "Trap 5: Alpha Preservation After Loss", "Protect locked alpha", "standard", now_ts)
            
        return v

def verify_all():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c_prod = ProductionConsultant(mode="playbook")

    # 1. Today (Oct 13, 2026 - 0DTE Expiry)
    eng_td = BacktestEngine("2026-10-13")
    raw_td = eng_td.run_simulation(s3)
    dte_td = eng_td.get_expiry_days()
    app_td = []
    for i, t in enumerate(raw_td, 1):
        idx = [k for k, x in enumerate(eng_td.spot_candles) if t.entry_time in x["start_time"]][0]
        dos = generate_market_dossier("2026-10-13", eng_td.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw_td[:i-1], dte_td, True)
        if c_prod.evaluate(dos).is_approved:
            app_td.append(t)
    m_td = calculate_metrics(app_td)
    fric_td = len(app_td) * 40.0
    net1_td = m_td["net_pnl"] - fric_td
    net2_td = (m_td["net_pnl"] * 2) - fric_td
    print("=" * 115)
    print(f" 🚀 TODAY'S 0DTE VERIFICATION (OCT 13, 2026): {len(app_td)} Trades | Win Rate: {m_td['win_rate']:.1f}% | Net (1 Lot): ₹{net1_td:+.2f} | Net (2 Lots): ₹{net2_td:+.2f}")
    print("=" * 115)

    # 2. 3-Week Comprehensive Test
    weeks = [
        ("Week 8", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
        ("Week 9", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]),
        ("Week 10", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
    ]
    tot_tr = 0; tot_w = 0; tot_net1 = 0
    for w_name, days in weeks:
        w_net = 0
        w_cnt = 0
        w_wins = 0
        for d in days:
            eng = BacktestEngine(d)
            raw = eng.run_simulation(s3)
            dte = eng.get_expiry_days()
            app = []
            for i, t in enumerate(raw, 1):
                idx = [k for k, x in enumerate(eng.spot_candles) if t.entry_time in x["start_time"]][0]
                dos = generate_market_dossier(d, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte <= 0.2))
                if c_prod.evaluate(dos).is_approved:
                    app.append(t)
            m = calculate_metrics(app)
            net = m["net_pnl"] - len(app) * 40.0
            w_net += net
            w_cnt += len(app)
            w_wins += m["wins"]
        print(f"  {w_name}: {w_cnt} trds | Win Rate: {(w_wins/w_cnt*100):.1f}% | Net (1 Lot) = ₹{w_net:+10.2f} | Net (2 Lots) = ₹{w_net*2:+10.2f}")
        tot_tr += w_cnt; tot_w += w_wins; tot_net1 += w_net

    print("-" * 115)
    print(f"🏆 GRAND 3-WEEK TOTAL: {tot_tr} trds | Win Rate: {(tot_w/tot_tr*100):.1f}% | Net (1 Lot): ₹{tot_net1:+10.2f} | Net (2 Lots / 10k margin): ₹{tot_net1*2:+10.2f}")
    print("=" * 115)

if __name__ == "__main__":
    verify_all()
