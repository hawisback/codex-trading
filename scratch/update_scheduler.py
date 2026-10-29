with open('nifty_trader_scheduler.py', 'r', encoding='utf-8') as f:
    text = f.read()

target1 = """            self._timed_call("monitor_quote", self.refresh_monitor_quote, open_trades[0], reuse=True)
            self.save_active_position(open_trades[0])
            self._timed_call("position_management", self.manage_open_trades, open_trades, ctx, {})"""

replacement1 = """            self._timed_call("monitor_quote", self.refresh_monitor_quote, open_trades[0], reuse=True)
            self.save_active_position(open_trades[0])
            self._timed_call("ai_stop_loss_check", self._check_ai_stop_loss, open_trades[0], ctx)
            self._timed_call("position_management", self.manage_open_trades, open_trades, ctx, {})"""

check_method = """    def _check_ai_stop_loss(self, trade: dict, ctx: dict):
        \"\"\"Asynchronous Two-Step Stop Loss check called on monitoring ticks.\"\"\"
        if not trade or trade.get("status") != "OPEN":
            return
        status = trade.get("ai_stop_status")
        if status is None:
            # Step 2: Post-fill consultation request (entry already filled and safe)
            self.ai_consultant.request_stop_loss_consultation(
                trade, ctx, ratchet_callback=self.ratchet_stops, save_callback=self.save_active_position
            )
        elif status == "PENDING":
            # Next call: check if AI verdict has arrived
            self.ai_consultant.poll_stop_loss_verdict(
                trade, ratchet_callback=self.ratchet_stops, save_callback=self.save_active_position
            )

    def _run_cycle(self, ignore_feed_health: bool = False):"""

target2 = """    def _run_cycle(self, ignore_feed_health: bool = False):"""

assert target1 in text, "target1 not found"
assert target2 in text, "target2 not found"

text = text.replace(target1, replacement1, 1).replace(target2, check_method, 1)

with open('nifty_trader_scheduler.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Updated nifty_trader_scheduler.py successfully")
