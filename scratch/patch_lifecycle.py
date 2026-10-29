with open('position_lifecycle.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. _refresh_record
t1 = """            record.update(verified)
            record["status"] = status(record)"""
r1 = """            record.update(verified)
            if not record.get("entry_order_id") and record.get("parent_order_id"):
                record["entry_order_id"] = record["parent_order_id"]
            record["status"] = status(record)"""
assert t1 in text, "t1 not found"
text = text.replace(t1, r1, 1)

# 2. _entry_balances
t2 = """            qty = filled(order)
            ref = order.get("entry_order_id")"""
r2 = """            qty = filled(order)
            ref = order.get("entry_order_id") or order.get("parent_order_id")"""
assert t2 in text, "t2 not found"
text = text.replace(t2, r2, 1)

# 3. get_trades_state scoped collection
t3 = """                for order in journal:
                    owned = order["order_id"] in known or order.get("entry_order_id") in refs or order.get("request_id") in requests"""
r3 = """                for order in journal:
                    if not order.get("entry_order_id") and order.get("parent_order_id"):
                        order["entry_order_id"] = order["parent_order_id"]
                    owned = (order["order_id"] in known or order.get("entry_order_id") in refs
                             or order.get("parent_order_id") in refs or order.get("request_id") in requests)"""
assert t3 in text, "t3 not found"
text = text.replace(t3, r3, 1)

# 4. scoped round trips checks
t4 = """                                balance = filled(order) - sum(filled(child) for child in scoped
                                    if child.get("entry_order_id") == order["order_id"]
                                    and child["kind"] in ("STOP", "EXIT"))"""
r4 = """                                balance = filled(order) - sum(filled(child) for child in scoped
                                    if (child.get("entry_order_id") == order["order_id"] or child.get("parent_order_id") == order["order_id"])
                                    and child["kind"] in ("STOP", "EXIT"))"""
assert t4 in text, "t4 not found"
text = text.replace(t4, r4, 1)

t4b = """                                active_refs = {e.get("order_id") for e in state["entries"]}
                                if order.get("entry_order_id") not in active_refs and order["order_id"] not in known:"""
r4b = """                                active_refs = {e.get("order_id") for e in state["entries"]}
                                child_ref = order.get("entry_order_id") or order.get("parent_order_id")
                                if child_ref not in active_refs and order["order_id"] not in known:"""
assert t4b in text, "t4b not found"
text = text.replace(t4b, r4b, 1)

# 5. _ensure_protection abort on exit and ref fallback
t5 = """    def _ensure_protection(self, state):
        if not self.state_verified or any(status(o) not in TERMINAL for o in state["exits"]):
            return
        balances = state.get("entry_balances", {})
        for stop in state["stops"]:
            if status(stop) in TERMINAL:
                continue
            ref = stop.get("entry_order_id")
            coverage = sum(remaining(s) for s in state["stops"]
                           if s.get("entry_order_id") == ref and status(s) not in TERMINAL)
            if ref not in balances or coverage > balances[ref]:
                state["protection_confirmed"] = False
                state["risk_exit_required"] = "Protective SELL quantities do not match remaining long exposure"
                self.save_active_position(state)
                return
        for ref, qty in balances.items():
            if qty <= 0:
                continue
            stops = [s for s in state["stops"] if s.get("entry_order_id") == ref and status(s) not in TERMINAL]
            if stops:
                continue
            old_floor = max([float(s.get("trigger_price") or 0) for s in state["stops"]
                             if balances.get(s.get("entry_order_id"), 0) > 0] +
                            [float(state.get("desired_stop_trigger") or 0)])"""
r5 = """    def _ensure_protection(self, state):
        if not self.state_verified or any(status(o) not in TERMINAL for o in state["exits"]):
            return
        if state.get("status") in ("EXIT_PENDING", "EXIT_UNKNOWN") or state.get("risk_exit_required"):
            return
        balances = state.get("entry_balances", {})
        for stop in state["stops"]:
            if status(stop) in TERMINAL:
                continue
            ref = stop.get("entry_order_id") or stop.get("parent_order_id")
            coverage = sum(remaining(s) for s in state["stops"]
                           if (s.get("entry_order_id") == ref or s.get("parent_order_id") == ref) and status(s) not in TERMINAL)
            if ref not in balances or coverage > balances[ref]:
                state["protection_confirmed"] = False
                state["risk_exit_required"] = "Protective SELL quantities do not match remaining long exposure"
                self.save_active_position(state)
                return
        for ref, qty in balances.items():
            if qty <= 0:
                continue
            stops = [s for s in state["stops"] if (s.get("entry_order_id") == ref or s.get("parent_order_id") == ref) and status(s) not in TERMINAL]
            if stops:
                continue
            old_floor = max([float(s.get("trigger_price") or 0) for s in state["stops"]
                             if balances.get(s.get("entry_order_id") or s.get("parent_order_id"), 0) > 0] +
                            [float(state.get("desired_stop_trigger") or 0)])"""
assert t5 in text, "t5 not found"
text = text.replace(t5, r5, 1)

# 6. coverage loop at the end of _ensure_protection
t6 = """        for stop in state["stops"]:
            if status(stop) in TERMINAL:
                continue
            ref = stop.get("entry_order_id")
            if status(stop) not in ("OPEN", "TRIGGER_PENDING") or ref not in covered:"""
r6 = """        for stop in state["stops"]:
            if status(stop) in TERMINAL:
                continue
            ref = stop.get("entry_order_id") or stop.get("parent_order_id")
            if status(stop) not in ("OPEN", "TRIGGER_PENDING") or ref not in covered:"""
assert t6 in text, "t6 not found"
text = text.replace(t6, r6, 1)

# 7. exit_trade refresh without protection
t7 = """            def refresh():
                current, _ = self.get_trades_state()"""
r7 = """            def refresh():
                current, _ = self.get_trades_state(ensure_protection=False)"""
assert t7 in text, "t7 not found"
text = text.replace(t7, r7, 1)

with open('position_lifecycle.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Successfully patched position_lifecycle.py")
