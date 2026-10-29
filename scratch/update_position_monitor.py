with open('trading/application/position_monitor.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = """            known_floor = max(
                float(t.get("desired_stop_trigger") or 0), float(t.get("current_stop_trigger") or 0)
            )"""

replacement1 = """            known_floor = max(
                float(t.get("desired_stop_trigger") or 0),
                float(t.get("current_stop_trigger") or 0),
                float(t.get("ai_stop_price") or 0),
            )"""

target2 = """            elif known_floor > 0 and last_bid <= known_floor:
                exit_reason = (
                    f"PERSISTED TRAILING FLOOR: Bid ({last_bid:.2f}) breached floor ({known_floor:.2f})"
                )"""

replacement2 = """            elif known_floor > 0 and last_bid <= known_floor:
                ai_sl = float(t.get("ai_stop_price") or 0)
                if ai_sl > 0 and last_bid <= ai_sl:
                    exit_reason = (
                        f"AI STOP LOSS: Option bid ({last_bid:.2f}) breached AI stop level ({ai_sl:.2f})"
                    )
                else:
                    exit_reason = (
                        f"PERSISTED TRAILING FLOOR: Bid ({last_bid:.2f}) breached floor ({known_floor:.2f})"
                    )"""

target3 = """            # 0b. Structural Wick Invalidation (for Climax Spring Reversals)
            elif (
                enable_structural_wick_stop
                and t.get("invalidation_level") is not None
                and (
                    (is_ce and spot and spot <= float(t["invalidation_level"]))
                    or (is_pe and spot and spot >= float(t["invalidation_level"]))
                )
            ):
                inval_level = float(t["invalidation_level"])
                exit_reason = f"STRUCTURAL WICK STOP: Spot ({spot:.1f}) breached climax wick ({inval_level:.1f}). Cutting trade early to protect capital.\""""

replacement3 = """            # 0b. Structural Invalidation (Spot breached technical invalidation level)
            elif (
                enable_structural_wick_stop
                and t.get("invalidation_level") is not None
                and (
                    (is_ce and spot and spot <= float(t["invalidation_level"]))
                    or (is_pe and spot and spot >= float(t["invalidation_level"]))
                )
            ):
                inval_level = float(t["invalidation_level"])
                exit_reason = f"STRUCTURAL INVALIDATION: Spot ({spot:.1f}) breached invalidation level ({inval_level:.1f}). Cutting trade early to protect capital.\""""

assert target1 in text, "target1 not found"
assert target2 in text, "target2 not found"
assert target3 in text, "target3 not found"

text = text.replace(target1, replacement1, 1).replace(target2, replacement2, 1).replace(target3, replacement3, 1)

with open('trading/application/position_monitor.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated position_monitor.py successfully")
