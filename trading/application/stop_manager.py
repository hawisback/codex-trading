"""Durable protective-order transitions; acknowledgements never imply protection."""

import logging
from typing import Any

from entry_policy import timestamp
from execution_safety import ReconciliationError, TERMINAL, remaining, status
from market_clock import MarketClock
from trading.domain.prices import round_tick
from trading.domain.unified_stop_policy import unified_floor

logger = logging.getLogger("NiftyAI")


class StopManager:
    def __init__(self, owner: Any):
        self.owner = owner
        self.client = owner.client
        self.cfg = owner.strategy_cfg.get("exit", {})

    def save(self, state):
        self.owner.save_active_position(state)

    def expired(self, started):
        return (MarketClock.now_ist() - timestamp(started)).total_seconds() >= float(
            self.cfg.get("stop_confirmation_timeout_sec", 10)
        )

    @staticmethod
    def ref(stop):
        return stop.get("entry_order_id") or stop.get("parent_order_id")

    def confirm(self, state):
        balances = state.get("entry_balances", {})
        covered = {ref: 0 for ref in balances}
        confirmed = not state.get("stop_replacement")
        active = [s for s in state["stops"] if status(s) not in TERMINAL]
        for stop in state["stops"]:
            pending = stop.get("pending_modification")
            if pending:
                if status(stop) in TERMINAL or (
                    status(stop) == "TRIGGER_PENDING"
                    and float(stop.get("trigger_price") or 0) >= pending["trigger_price"]
                ):
                    stop.pop("pending_modification", None)
                else:
                    confirmed = False
                    if self.expired(pending["requested_at"]):
                        state["risk_exit_required"] = "Stop modification confirmation timed out"
            if status(stop) in TERMINAL:
                continue
            ref = self.ref(stop)
            if ref not in covered:
                state["risk_exit_required"] = "Protective SELL has an unknown entry reference"
                confirmed = False
                continue
            covered[ref] += remaining(stop)
            if status(stop) == "OPEN":
                state["risk_exit_required"] = "Protective stop triggered but remains unfilled"
            if status(stop) != "TRIGGER_PENDING" or stop.get("pending_modification"):
                confirmed = False
            if float(stop.get("trigger_price") or 0) + float(
                self.cfg.get("stop_min_improvement_points", 0.50)
            ) < float(state.get("desired_stop_trigger") or 0):
                confirmed = False
        if any(covered.get(ref, 0) > qty for ref, qty in balances.items()):
            state["risk_exit_required"] = "Protective SELL quantities exceed remaining long exposure"
        state["protection_confirmed"] = confirmed and covered == balances
        if active:
            state["current_stop_trigger"] = min(float(s.get("trigger_price") or 0) for s in active)
        self.save(state)

    def floor(self, state):
        balances = state.get("entry_balances", {})
        existing = max(
            [float(s.get("trigger_price") or 0) for s in state["stops"] if balances.get(self.ref(s), 0) > 0]
            + [float(state.get("desired_stop_trigger") or 0)]
        )
        options = getattr(self.owner, "trading_cfg", {}).get("r01_policy", {})
        if (options.get("enabled") is not True or options.get("unified_stop_enabled") is not True
                or state.get("r01_policy_version") != "r01-owner-20261029-v1"):
            # Do not migrate an already-open legacy position just because
            # the operator enables R01 mid-session.
            return existing

        # Never loosen any confirmed broker stop. Price gains require the
        # existing monitoring quote to have been verified; quote failure
        # cannot turn an unknown bid into a profit ratchet.
        entry = state.get("entry_price")
        highest = state.get("peak_bid") if state.get("quote_verified") else entry
        proposal = unified_floor(
            entry, highest, existing, MarketClock.now_ist().strftime("%H:%M"),
            initial_loss_pct=getattr(self.owner, "trading_cfg", {}).get("risk", {})
            .get("option_hard_stop_pct", 25))
        return max(existing, float(proposal.trigger_floor)) if proposal else existing

    def place(self, state, ref, trigger):
        if not self.owner.refresh_monitor_quote(state, reuse=True):
            state["risk_exit_required"] = "Fresh bid unavailable while protection is missing"
            self.save(state)
            return None
        if trigger <= 0 or trigger >= state["last_bid"]:
            state["risk_exit_required"] = "Protective stop floor already breached"
            self.save(state)
            return None
        stop = dict(
            request_id=self.owner.next_intent("STOP"),
            entry_order_id=ref,
            quantity=state["entry_balances"][ref],
            kind="STOP",
            trigger_price=trigger,
            limit_price=round_tick(trigger * 0.98),
            status="SUBMITTING",
            modifications=0,
        )
        state["stops"].append(stop)
        self.save(state)

        def preflight():
            if not self.owner.refresh_monitor_quote(state, reuse=True) or trigger >= state["last_bid"]:
                return {"error": True, "detail": "STOP_FLOOR_BREACHED_OR_QUOTE_UNAVAILABLE"}
            return None

        response = self.client.place_stop_loss(
            ref, trigger, stop["limit_price"], request_id=stop["request_id"], before_submit=preflight
        )
        if response.get("order_id"):
            stop.update(order_id=response["order_id"], status="UNKNOWN")
            self.save(state)
            try:
                self.owner._refresh_record(stop, [])
            except ReconciliationError:
                pass
        else:
            stop["status"] = "UNKNOWN" if response.get("outcome_unknown", True) else "REJECTED"
            stop["last_error"] = response.get("detail")
        if status(stop) == "REJECTED":
            state["risk_exit_required"] = "Protective stop creation rejected"
        self.save(state)
        return stop

    def ensure(self, state):
        if not self.owner.state_verified or any(status(e) not in TERMINAL for e in state["exits"]):
            return
        self.confirm(state)
        if state.get("stop_replacement"):
            self.replace(state)
            return
        if state.get("risk_exit_required"):
            return
        for ref, qty in state.get("entry_balances", {}).items():
            active = [s for s in state["stops"] if self.ref(s) == ref and status(s) not in TERMINAL]
            if active and sum(remaining(s) for s in active) != qty:
                state["risk_exit_required"] = (
                    "Protective SELL quantities do not match remaining long exposure"
                )
                self.save(state)
                return
            if qty <= 0 or active:
                continue
            trigger = round_tick(
                max(
                    state["entry_price"] * (1 - self.cfg.get("initial_stop_pct", 30) / 100), self.floor(state)
                )
            )
            self.place(state, ref, trigger)
            if state.get("risk_exit_required"):
                break
        self.confirm(state)

    def replace(self, state, stop=None):
        """Resume cancel/verify/reconcile/create after any interruption, without sleeps."""
        if stop is not None:
            state["stop_replacement"] = dict(
                old_order_id=stop["order_id"],
                entry_order_id=self.ref(stop),
                started_at=MarketClock.now_ist().isoformat(),
                phase="CANCEL_PENDING",
            )
            state["protection_confirmed"] = False
            self.save(state)  # Intent precedes the cancellation, including a lost acknowledgement.
            self.client.cancel_stop_loss(stop["order_id"])
        replacement = state["stop_replacement"]
        old = next(s for s in state["stops"] if s.get("order_id") == replacement["old_order_id"])
        self.owner._refresh_record(old, [])
        if status(old) not in TERMINAL:
            if self.expired(replacement["started_at"]):
                state["risk_exit_required"] = "Stop replacement cancellation remains unconfirmed"
            self.save(state)
            return
        # A fill during cancellation changes both position and per-entry residuals.
        current, _ = self.owner.get_trades_state(ensure_protection=False)
        if not self.owner.state_verified or not current:
            return
        state.clear()
        state.update(current[0])
        if state.get("status") != "OPEN" or state.get("risk_exit_required"):
            return
        replacement = state["stop_replacement"]
        ref = replacement["entry_order_id"]
        if state["entry_balances"].get(ref, 0) <= 0:
            state.pop("stop_replacement")
            self.confirm(state)
            return
        active = [s for s in state["stops"] if self.ref(s) == ref and status(s) not in TERMINAL]
        if not active:
            # Recovery may discover existing protection. Never create a competing SELL.
            replacement["phase"] = "CREATE_PENDING"
            self.save(state)
            created = self.place(state, ref, round_tick(self.floor(state)))
            active = [created] if created is not None else []
        if len(active) == 1 and status(active[0]) == "TRIGGER_PENDING":
            if float(active[0]["trigger_price"]) >= self.floor(state):
                state.pop("stop_replacement")
            elif active[0].get("order_id") != replacement["old_order_id"]:
                # Raise adopted protection while retaining the desired floor.
                state.pop("stop_replacement")
                self.ratchet(state, self.floor(state))
        if state.get("stop_replacement") and self.expired(replacement["started_at"]):
            state["risk_exit_required"] = "Replacement protection was not confirmed"
        self.confirm(state)

    def ratchet(self, state, trigger):
        trigger = round_tick(max(float(state.get("desired_stop_trigger") or 0), trigger, self.floor(state)))
        state["desired_stop_trigger"] = trigger
        self.save(state)
        self.confirm(state)
        if state.get("risk_exit_required"):
            return
        if state.get("stop_replacement"):
            self.replace(state)
            return
        for stop in state["stops"]:
            if status(stop) in TERMINAL:
                continue
            self.owner._refresh_record(stop, [])
            self.confirm(state)
            if state.get("risk_exit_required"):
                return
            if status(stop) != "TRIGGER_PENDING" or stop.get("pending_modification"):
                continue
            minimum_improvement = (
                0.0
                if state.get("ai_stop_status") == "APPLYING"
                else float(self.cfg.get("stop_min_improvement_points", 0.50))
            )
            if trigger <= float(stop.get("trigger_price") or 0) + minimum_improvement:
                continue
            if not self.owner.refresh_monitor_quote(state, reuse=True):
                return
            if trigger >= state["last_bid"]:
                state["risk_exit_required"] = "Trailing stop floor already breached"
                self.save(state)
                return
            if int(stop.get("modifications", 0)) >= 25:
                self.replace(state, stop)
                return  # A fresh broker snapshot is required before touching another stop.
            stop["pending_modification"] = dict(
                trigger_price=trigger, requested_at=MarketClock.now_ist().isoformat()
            )
            stop["modifications"] = int(stop.get("modifications", 0)) + 1
            state["protection_confirmed"] = False
            self.save(state)

            def preflight():
                if not self.owner.refresh_monitor_quote(state, reuse=True) or trigger >= state["last_bid"]:
                    state["risk_exit_required"] = (
                        "Trailing floor breached or quote unavailable before modification"
                    )
                    return {"error": True, "detail": state["risk_exit_required"]}
                return None

            response = self.client.modify_stop_loss(
                stop["order_id"], trigger, round_tick(trigger * 0.98), before_submit=preflight
            )
            if response.get("error") and not response.get("outcome_unknown", True):
                stop.pop("pending_modification", None)
                if response.get("not_submitted"):
                    stop["modifications"] -= 1
                stop["last_error"] = response.get("detail")
                if "modifications exceeded" in str(response.get("detail", "")).lower():
                    stop["modifications"] = 25
            self.owner._refresh_record(stop, [])
            self.confirm(state)
        self.confirm(state)
