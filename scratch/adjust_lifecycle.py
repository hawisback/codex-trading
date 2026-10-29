with open('position_lifecycle.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Revert the guard in _ensure_protection that blocked re-arming
old_guard = """    def _ensure_protection(self, state):
        if not self.state_verified or any(status(o) not in TERMINAL for o in state["exits"]):
            return
        if state.get("status") in ("EXIT_PENDING", "EXIT_UNKNOWN") or state.get("risk_exit_required"):
            return"""

new_guard = """    def _ensure_protection(self, state):
        if not self.state_verified or any(status(o) not in TERMINAL for o in state["exits"]):
            return"""

if old_guard in text:
    text = text.replace(old_guard, new_guard, 1)

# Revert refresh() back to get_trades_state()
old_refresh = """            def refresh():
                current, _ = self.get_trades_state(ensure_protection=False)"""

new_refresh = """            def refresh():
                current, _ = self.get_trades_state()"""

if old_refresh in text:
    text = text.replace(old_refresh, new_refresh, 1)

with open('position_lifecycle.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Adjusted position_lifecycle.py")
