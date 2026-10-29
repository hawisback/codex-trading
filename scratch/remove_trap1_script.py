with open('ai_consultant.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        # -------------------------------------------------------------
        # Trap 1: The VWAP Blender (Chop Ping-Pong across Flat VWAP)
        # -------------------------------------------------------------
        # Exception: A structural directional shift flipping after an opposite-side failure
        # is an institutional trend reversal expansion (like July 23 or Sep 24), not a chop blender.
        is_reversal_expansion = bool(d.is_directional_shift)

        if d.vwap_blender_warning and not is_reversal_expansion:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=95,
                trap_detected="Trap 1: The VWAP Blender",
                reasoning=f"Spot is only {d.vwap_distance_pts:.1f} pts from flat VWAP with {d.vwap_cross_count_60m} crosses in 60m. High probability of immediate stop out.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )
            
        if "MIDDAY_DEAD_ZONE" in d.session_phase and abs(d.vwap_slope_15m) < 0.08 and not is_reversal_expansion:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 1: Midday Flat-VWAP Chop Trap",
                reasoning=f"Midday Dead Zone (11:30 - 13:15 IST) with zero VWAP slope ({d.vwap_slope_15m:+.3f} pts/min). Institutions are paused; avoid lunch-hour churn.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )'''

replacement = '''        # -------------------------------------------------------------
        # Trap 1: REMOVED (User Directive & Bottleneck Optimization)
        # Midday Dead Zone & VWAP Blender vetoes disabled to unlock high-probability momentum runners.
        # -------------------------------------------------------------
        is_reversal_expansion = bool(d.is_directional_shift)'''

assert target in content, "Target Trap 1 code not found in ai_consultant.py"
new_content = content.replace(target, replacement, 1)

with open('ai_consultant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("SUCCESSFULLY REMOVED TRAP 1 FROM ai_consultant.py")
