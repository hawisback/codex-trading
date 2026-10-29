from trading.bootstrap import configure_console
configure_console()

import copy
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

class EnhancedAIConsultant(AIConsultant):
    def evaluate(self, dossier):
        # 1. Enforce Trap 1 Midday Dead Zone strictly between 11:30 and 13:15 IST (135 <= minutes_from_open <= 240)
        # unless it is a verified high-volume day-extreme breakout
        if "MIDDAY_DEAD_ZONE" in dossier.session_phase or (135 <= getattr(dossier, "minutes_from_open", 0) <= 240):
            if not getattr(dossier, "is_directional_shift", False):
                verdict = copy.deepcopy(super().evaluate(dossier))
                verdict.is_approved = False
                verdict.action = "VETOED"
                verdict.trap_detected = "Trap 1: Midday Dead Zone (11:30 - 13:15 IST)"
                verdict.reasoning = f"Current time ({dossier.time_ist}) is in the institutional Midday Dead Zone. Low institutional volume causes whipsaws."
                return verdict

        # 2. Fix Trap 8 Directional Symmetry:
        # A. If setup is CLIMAX_SPRING:
        # A Bullish Climax Spring (CE) MUST be below VWAP to mean-revert up to VWAP.
        # It should NOT be vetoed by Trap 8!
        if dossier.setup_type == "CLIMAX_SPRING":
            # Temporarily bypass the >= 75 cap if it's a genuine Climax Spring with structural wick stop
            orig_dist = dossier.vwap_distance_pts
            # Only veto if distance is absurdly impossible (> 180 pts)
            if orig_dist > 180.0:
                pass # let super handle
            else:
                dossier.vwap_distance_pts = min(orig_dist, 50.0)
                verdict = super().evaluate(dossier)
                dossier.vwap_distance_pts = orig_dist
                return verdict

        # B. For Trend Pullbacks:
        # If the trend is a confirmed institutional freight train (VWAP slope steep >= 0.15 pts/min)
        # and spot is cleanly holding the 5m EMA9, allow extension up to 110 pts instead of 75 pts!
        if dossier.setup_type == "TREND_PULLBACK":
            if abs(dossier.vwap_slope_15m) >= 0.15 and dossier.vwap_distance_pts < 110.0:
                orig_dist = dossier.vwap_distance_pts
                dossier.vwap_distance_pts = 65.0 # safely within cap
                verdict = super().evaluate(dossier)
                dossier.vwap_distance_pts = orig_dist
                return verdict

        return super().evaluate(dossier)

print("=" * 115)
print(" COMPARATIVE AUDIT: CURRENT ENGINE VS ENHANCED AI BRAIN (OCT 21 - OCT 23)")
print("=" * 115)

cfg = StrategyConfig.load_from_config("institutional_pullback")
radar = AIOpportunityRadar()

base_ai = AIConsultant(mode="playbook", trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}})
enhanced_ai = EnhancedAIConsultant(mode="playbook", trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}})

for dt in ["2026-10-21", "2026-10-22"]:
    eng = BacktestEngine(target_date=dt)
    
    t_base = run_ai_radar_simulation(eng, cfg, radar, base_ai)
    t_enh = run_ai_radar_simulation(eng, cfg, radar, enhanced_ai)
    
    m_base = calculate_metrics(t_base)
    m_enh = calculate_metrics(t_enh)
    
    pnl_base = (m_base["net_pnl"] * 2) - len(t_base) * 40.0
    pnl_enh = (m_enh["net_pnl"] * 2) - len(t_enh) * 40.0
    
    print(f"\n--- {dt} ---")
    print(f"  BASE AI:     {len(t_base)} trades | {m_base['wins']}W / {m_base['losses']}L | Net PnL (2L): ₹{pnl_base:>+10,.2f}")
    print(f"  ENHANCED AI: {len(t_enh)} trades | {m_enh['wins']}W / {m_enh['losses']}L | Net PnL (2L): ₹{pnl_enh:>+10,.2f}")
    
    print("  Enhanced Trades Detail:")
    for t in t_enh:
        print(f"    - #{t.trade_id} {t.entry_time} {t.direction} {t.symbol} | PnL (2L): ₹{t.pnl*2:+,.2f} ({t.exit_reason})")
