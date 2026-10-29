import os

with open('ai_consultant.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '''        if is_counter_trend and not is_reversal_expansion:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 7: Counter-Trend VWAP Slope Trap",
                reasoning=f"Direction {d.direction} is fighting active institutional VWAP trajectory ({d.vwap_slope_15m:+.3f} pts/min). Never trade counter-trend against a steeply sloping session benchmark.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )

        # -------------------------------------------------------------
        # Trap 8: Climax Overextension Trap (Parabolic Rubber Band)
        # -------------------------------------------------------------
        # Hard Climax Cap (>= 75.0 pts from VWAP): Never chase if spot is already >= 75 pts from VWAP
        if d.vwap_distance_pts >= 75.0:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 8: Climax Overextension Cap (>= 75 pts)",
                reasoning=f"Spot is {d.vwap_distance_pts:.1f} pts extended from VWAP (>= 75 pts). Rubber band is at extreme stretch with violent mean-reversion risk.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )

        is_climax = getattr(d, "is_climax_extended", False) or (d.vwap_distance_pts > 80.0)
        if is_climax and not is_reversal_expansion:'''

replacement = '''        if is_counter_trend and not is_reversal_expansion:
            # Check if setup qualifies as a confirmed Institutional Reversal Inflection
            # (Moderate slope <= 0.85 pts/min, Runway <= 140 pts, and 2m Candle Aligned)
            is_inflection = getattr(d, "is_reversal_inflection", False)
            if not is_inflection:
                return AIVerdict(
                    is_approved=False,
                    action="VETOED",
                    confidence_score=90,
                    trap_detected="Trap 7: Counter-Trend VWAP Slope Trap",
                    reasoning=f"Direction {d.direction} is fighting active institutional VWAP trajectory ({d.vwap_slope_15m:+.3f} pts/min) without confirmed inflection alignment. Never trade counter-trend against a steeply sloping session benchmark.",
                    recommended_trailing="tight_ema20",
                    timestamp=now_ts
                )

        # -------------------------------------------------------------
        # Trap 8: Climax Overextension Trap (Parabolic Rubber Band)
        # -------------------------------------------------------------
        # Hard Climax Cap (>= 75.0 pts from VWAP): Never chase if spot is already >= 75 pts from VWAP
        # Note: Validated Reversal Inflections moving back towards VWAP are governed by Trap 7's 140 pt runway limit.
        is_chasing_away = (d.direction == "CE" and d.spot_price > d.session_vwap) or \\
                          (d.direction == "PE" and d.spot_price < d.session_vwap)
        is_inflection = getattr(d, "is_reversal_inflection", False)

        if d.vwap_distance_pts >= 75.0 and (is_chasing_away or not is_inflection):
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 8: Climax Overextension Cap (>= 75 pts)",
                reasoning=f"Spot is {d.vwap_distance_pts:.1f} pts extended from VWAP (>= 75 pts). Rubber band is at extreme stretch with violent mean-reversion risk.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )

        is_climax = getattr(d, "is_climax_extended", False) or (d.vwap_distance_pts > 80.0)
        if is_climax and not is_reversal_expansion and (is_chasing_away or not is_inflection):'''

assert target in content, "Target not found in content"
new_content = content.replace(target, replacement, 1)
with open('ai_consultant.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print("SUCCESSFULLY UPDATED ai_consultant.py")
