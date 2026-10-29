import re

with open("ai_consultant.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Imports and Paths
import_replacement = """from market_clock import MarketClock
from trading.bootstrap import configure_console
from trading.domain.prices import round_tick

logger = logging.getLogger("AIConsultant")
LOG_DIR = Path("logs")

PENDING_FILE_JSON = LOG_DIR / "pending_consultation.json"
PENDING_FILE_MD = LOG_DIR / "pending_consultation.md"
VERDICT_FILE = LOG_DIR / "ai_verdict.json"

PENDING_SL_FILE_JSON = LOG_DIR / "pending_stop_loss.json"
PENDING_SL_FILE_MD = LOG_DIR / "pending_stop_loss.md"
SL_VERDICT_FILE = LOG_DIR / "ai_stop_verdict.json"


@dataclass
class StopLossDossier:
    symbol: str
    direction: str                     # "CE" or "PE"
    fill_price: float                  # Exact execution price from broker (e.g. 82.12)
    quantity: int                      # Contract quantity (e.g. 130)
    current_spot: float                # Spot level at fill
    vwap: float                        # Current session VWAP
    ema_9: float                       # 5m EMA9
    ema_20: float                      # 5m EMA20
    setup_type: str                    # "TREND_PULLBACK", "CLIMAX_SPRING", etc.
    active_stop_price: float           # Current baseline broker stop (e.g. 30% initial stop)
    trigger_candle_open: float = 0.0
    trigger_candle_high: float = 0.0
    trigger_candle_low: float = 0.0
    trigger_candle_close: float = 0.0
    recent_swing_low: float = 0.0      # For CE stop reference
    recent_swing_high: float = 0.0     # For PE stop reference
    time_ist: str = ""
    requested_at: str = ""

    def to_markdown(self) -> str:
        lines = [
            f"# 🛑 Post-Fill AI Stop-Loss Consultation Dossier",
            f"**Time:** {self.time_ist} IST | **Setup:** `{self.setup_type}` | **Direction:** `{self.direction}`",
            "",
            "## 📦 Execution Facts",
            f"- **Instrument:** `{self.symbol}`",
            f"- **Execution Fill Price:** ₹{self.fill_price:.2f}",
            f"- **Filled Quantity:** {self.quantity} contracts",
            f"- **Baseline Safety Stop Floor:** ₹{self.active_stop_price:.2f} (Active at Broker)",
            "",
            "## 📈 Spot Technical Structure at Entry",
            f"- **Spot at Fill:** {self.current_spot:.2f}",
            f"- **Session VWAP:** {self.vwap:.2f} (Dist: {self.current_spot - self.vwap:+.1f} pts)",
            f"- **5m EMA9:** {self.ema_9:.2f} | **5m EMA20:** {self.ema_20:.2f}",
            f"- **Trigger Candle [O/H/L/C]:** [{self.trigger_candle_open:.1f} / {self.trigger_candle_high:.1f} / {self.trigger_candle_low:.1f} / {self.trigger_candle_close:.1f}]",
            f"- **Key Structural Reference:** {'Swing Low: ' + str(round(self.recent_swing_low, 1)) if self.direction == 'CE' else 'Swing High: ' + str(round(self.recent_swing_high, 1))}",
            "",
            "## 🎯 Action Required",
            f"Set technical `ai_stop_price` and optional `spot_invalidation_level` in `logs/ai_stop_verdict.json`:",
            "```json",
            "{",
            f'  "ai_stop_price": {round(self.fill_price * 0.82, 2)},',
            f'  "spot_invalidation_level": {round(self.recent_swing_low if self.direction == "CE" else self.recent_swing_high, 1)},',
            '  "trailing_style": "standard",',
            '  "reasoning": "Technical stop aligned with market structure"',
            "}",
            "```",
        ]
        return "\\n".join(lines)


@dataclass
class AIStopLossVerdict:
    ai_stop_price: float
    spot_invalidation_level: Optional[float] = None
    trailing_style: str = "standard"
    reasoning: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)"""

old_target = """from market_clock import MarketClock
from trading.bootstrap import configure_console

logger = logging.getLogger("AIConsultant")
LOG_DIR = Path("logs")

PENDING_FILE_JSON = LOG_DIR / "pending_consultation.json"
PENDING_FILE_MD = LOG_DIR / "pending_consultation.md"
VERDICT_FILE = LOG_DIR / "ai_verdict.json\""""

assert old_target in content, "old_target not found in content"
content = content.replace(old_target, import_replacement, 1)

# 2. Add Stop Loss Methods to AIConsultant
sl_methods = """
    # =========================================================================
    # TWO-STEP AI STOP-LOSS CONSULTATION GATEWAY
    # =========================================================================
    def evaluate_stop_loss(self, dossier: StopLossDossier) -> AIStopLossVerdict:
        \"\"\"Evaluate technical Stop-Loss for an already-filled trade.\"\"\"
        if self.mode in ("rules", "playbook"):
            return self._evaluate_stop_loss_rules(dossier)
        elif self.mode == "chat":
            return self._evaluate_stop_loss_chat(dossier)
        else:
            return self._evaluate_stop_loss_rules(dossier)

    def _evaluate_stop_loss_rules(self, d: StopLossDossier) -> AIStopLossVerdict:
        \"\"\"Deterministic structural stop calculation based on trigger candle wicks and delta.\"\"\"
        now_ts = datetime.now().isoformat()
        if d.direction == "CE":
            cand_low = d.trigger_candle_low if d.trigger_candle_low > 0 else d.recent_swing_low
            inval = cand_low if cand_low > 0 else (d.current_spot - 15.0)
            spot_risk = max(5.0, d.current_spot - inval)
            opt_risk = spot_risk * 0.50
            target_stop = d.fill_price - opt_risk
            # Bound between 12% drop and 25% drop
            min_stop = d.fill_price * 0.75
            max_stop = d.fill_price * 0.88
            ai_stop = round_tick(max(min_stop, min(max_stop, target_stop)))
            ai_stop = max(ai_stop, d.active_stop_price)
            return AIStopLossVerdict(
                ai_stop_price=ai_stop,
                spot_invalidation_level=round(inval, 1),
                trailing_style="standard",
                reasoning=f"Structural stop set at ₹{ai_stop:.2f} below candle low ({inval:.1f} Spot)",
                timestamp=now_ts
            )
        else:
            cand_high = d.trigger_candle_high if d.trigger_candle_high > 0 else d.recent_swing_high
            inval = cand_high if cand_high > 0 else (d.current_spot + 15.0)
            spot_risk = max(5.0, inval - d.current_spot)
            opt_risk = spot_risk * 0.50
            target_stop = d.fill_price - opt_risk
            min_stop = d.fill_price * 0.75
            max_stop = d.fill_price * 0.88
            ai_stop = round_tick(max(min_stop, min(max_stop, target_stop)))
            ai_stop = max(ai_stop, d.active_stop_price)
            return AIStopLossVerdict(
                ai_stop_price=ai_stop,
                spot_invalidation_level=round(inval, 1),
                trailing_style="standard",
                reasoning=f"Structural stop set at ₹{ai_stop:.2f} above candle high ({inval:.1f} Spot)",
                timestamp=now_ts
            )

    def _evaluate_stop_loss_chat(self, d: StopLossDossier) -> AIStopLossVerdict:
        \"\"\"Pair-trading synchronous evaluation for stop loss with timeout.\"\"\"
        PENDING_SL_FILE_JSON.parent.mkdir(parents=True, exist_ok=True)
        PENDING_SL_FILE_MD.parent.mkdir(parents=True, exist_ok=True)
        if SL_VERDICT_FILE.exists():
            try:
                SL_VERDICT_FILE.unlink()
            except Exception:
                pass
        payload = {
            "status": "AWAITING_STOP_LOSS",
            "created_at": MarketClock.now_ist().isoformat(),
            "timeout_seconds": self.timeout_seconds,
            "dossier": asdict(d)
        }
        with open(PENDING_SL_FILE_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        with open(PENDING_SL_FILE_MD, "w", encoding="utf-8") as f:
            f.write(d.to_markdown() + f"\\n\\n*Awaiting stop-loss verdict in `{SL_VERDICT_FILE}`*\\n")

        start = time.time()
        while (time.time() - start) < self.timeout_seconds:
            if SL_VERDICT_FILE.exists():
                try:
                    with open(SL_VERDICT_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ai_sl = float(data.get("ai_stop_price") or data.get("stop_loss") or data.get("stop_price") or 0.0)
                    if ai_sl > 0:
                        ai_sl = round_tick(ai_sl)
                        inval = data.get("spot_invalidation_level") or data.get("invalidation_level")
                        inval_level = float(inval) if inval is not None else None
                        trailing = data.get("trailing_style") or data.get("trailing", "standard")
                        reason = data.get("reasoning") or data.get("reason", "AI Stop-Loss received.")
                        for p in (PENDING_SL_FILE_JSON, PENDING_SL_FILE_MD, SL_VERDICT_FILE):
                            try:
                                if p.exists():
                                    p.unlink()
                            except Exception:
                                pass
                        return AIStopLossVerdict(
                            ai_stop_price=ai_sl,
                            spot_invalidation_level=inval_level,
                            trailing_style=trailing,
                            reasoning=reason,
                            timestamp=datetime.now().isoformat()
                        )
                except Exception:
                    pass
            time.sleep(0.5)

        # Timeout: fallback to rules-based structural stop
        fallback = self._evaluate_stop_loss_rules(d)
        fallback.reasoning = f"Timeout ({self.timeout_seconds}s) expired; structural baseline applied."
        return fallback

    def request_stop_loss_consultation(
        self,
        trade: Dict[str, Any],
        ctx: Dict[str, Any],
        ratchet_callback,
        save_callback
    ):
        \"\"\"Publishes stop loss dossier or sets up deterministic stop immediately.\"\"\"
        fill_price = float(trade.get("entry_price") or 0.0)
        if fill_price <= 0:
            return

        symbol = trade.get("symbol", "")
        direction = "CE" if ("CE" in symbol or "-CE" in symbol) else "PE"
        quantity = int(trade.get("quantity") or 0)
        spot = float(ctx.get("spot") or ctx.get("current_close") or 0.0)
        vwap = float(ctx.get("session_vwap") or spot)
        ema9 = float(ctx.get("ema_9") or spot)
        ema20 = float(ctx.get("ema_20") or spot)
        setup_type = trade.get("setup_type", "TREND_PULLBACK")

        active_stop = 0.0
        if trade.get("stops"):
            active_stop = max([float(s.get("trigger_price") or 0.0) for s in trade["stops"]])
        if active_stop <= 0:
            active_stop = round_tick(fill_price * 0.70)

        trigger_o = float(ctx.get("candle_open") or 0.0)
        trigger_h = float(ctx.get("candle_high") or 0.0)
        trigger_l = float(ctx.get("candle_low") or 0.0)
        trigger_c = float(ctx.get("candle_close") or 0.0)
        swing_l = float(ctx.get("swing_low") or ctx.get("box_low_15m") or (spot - 20.0))
        swing_h = float(ctx.get("swing_high") or ctx.get("box_high_15m") or (spot + 20.0))

        dossier = StopLossDossier(
            symbol=symbol,
            direction=direction,
            fill_price=fill_price,
            quantity=quantity,
            current_spot=spot,
            vwap=vwap,
            ema_9=ema9,
            ema_20=ema20,
            setup_type=setup_type,
            active_stop_price=active_stop,
            trigger_candle_open=trigger_o,
            trigger_candle_high=trigger_h,
            trigger_candle_low=trigger_l,
            trigger_candle_close=trigger_c,
            recent_swing_low=swing_l,
            recent_swing_high=swing_h,
            time_ist=MarketClock.now_ist().strftime("%H:%M:%S"),
            requested_at=MarketClock.now_ist().isoformat()
        )

        if self.mode in ("rules", "playbook"):
            verdict = self._evaluate_stop_loss_rules(dossier)
            trade["ai_stop_price"] = verdict.ai_stop_price
            trade["desired_stop_trigger"] = verdict.ai_stop_price
            if verdict.spot_invalidation_level is not None:
                trade["invalidation_level"] = verdict.spot_invalidation_level
            trade["ai_stop_status"] = "ARMED"
            trade["ai_stop_reasoning"] = verdict.reasoning
            save_callback(trade)
            ratchet_callback(trade, verdict.ai_stop_price)
            logger.info(f"🎯 [DETERMINISTIC SL ARMED] Stop: ₹{verdict.ai_stop_price:.2f} | Spot Inval: {verdict.spot_invalidation_level} | {verdict.reasoning}")
        elif self.mode == "chat":
            PENDING_SL_FILE_JSON.parent.mkdir(parents=True, exist_ok=True)
            PENDING_SL_FILE_MD.parent.mkdir(parents=True, exist_ok=True)
            if SL_VERDICT_FILE.exists():
                try:
                    SL_VERDICT_FILE.unlink()
                except Exception:
                    pass
            payload = {
                "status": "AWAITING_STOP_LOSS",
                "created_at": MarketClock.now_ist().isoformat(),
                "timeout_seconds": self.timeout_seconds,
                "dossier": asdict(dossier)
            }
            with open(PENDING_SL_FILE_JSON, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            with open(PENDING_SL_FILE_MD, "w", encoding="utf-8") as f:
                f.write(dossier.to_markdown() + f"\\n\\n*Awaiting stop-loss verdict in `{SL_VERDICT_FILE}`*\\n")
            trade["ai_stop_status"] = "PENDING"
            trade["ai_stop_requested_at"] = MarketClock.now_ist().isoformat()
            save_callback(trade)
            logger.info(f"\\n" + "=" * 80)
            logger.info(f"🛑 [AI STOP-LOSS CONSULTATION REQUIRED] Filled {direction} @ ₹{fill_price:.2f}")
            logger.info(f"   Dossier: {PENDING_SL_FILE_MD}")
            logger.info(f"   Active Baseline Safety Stop at Broker: ₹{active_stop:.2f}")
            logger.info(f"   Submit verdict to {SL_VERDICT_FILE} or CLI '--set-sl'...")
            logger.info("=" * 80 + "\\n")

    def poll_stop_loss_verdict(
        self,
        trade: Dict[str, Any],
        ratchet_callback,
        save_callback,
        timeout_seconds: int = 60
    ) -> Optional[AIStopLossVerdict]:
        \"\"\"Non-blocking poll called during monitoring ticks for chat mode.\"\"\"
        now = datetime.now()
        requested_at_str = trade.get("ai_stop_requested_at")
        elapsed = 0.0
        if requested_at_str:
            try:
                requested_dt = MarketClock.parse_to_ist(requested_at_str)
                if requested_dt:
                    elapsed = max(0.0, (now.astimezone(requested_dt.tzinfo) - requested_dt).total_seconds())
            except Exception:
                pass

        if SL_VERDICT_FILE.exists():
            try:
                with open(SL_VERDICT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ai_sl = float(data.get("ai_stop_price") or data.get("stop_loss") or data.get("stop_price") or 0.0)
                inval = data.get("spot_invalidation_level") or data.get("invalidation_level")
                inval_level = float(inval) if inval is not None else None
                trailing = data.get("trailing_style") or data.get("trailing", "standard")
                reason = data.get("reasoning") or data.get("reason", "AI Stop-Loss received via chat.")

                if ai_sl > 0:
                    ai_sl = round_tick(ai_sl)
                    trade["ai_stop_price"] = ai_sl
                    trade["desired_stop_trigger"] = ai_sl
                    if inval_level is not None:
                        trade["invalidation_level"] = inval_level
                    trade["ai_stop_status"] = "ARMED"
                    trade["ai_stop_reasoning"] = reason
                    save_callback(trade)

                    # Ratchet the broker protective stop to the new AI level
                    ratchet_callback(trade, ai_sl)

                    logger.info(f"🎯 [AI STOP-LOSS ARMED] Stop ratcheted to ₹{ai_sl:.2f} | Spot Inval: {inval_level} | {reason}")
                    
                    for p in (PENDING_SL_FILE_JSON, PENDING_SL_FILE_MD, SL_VERDICT_FILE):
                        try:
                            if p.exists():
                                p.unlink()
                        except Exception:
                            pass
                    return AIStopLossVerdict(
                        ai_stop_price=ai_sl,
                        spot_invalidation_level=inval_level,
                        trailing_style=trailing,
                        reasoning=reason,
                        timestamp=now.isoformat()
                    )
            except Exception as e:
                logger.warning(f"Error parsing AI stop verdict file: {e}")

        # Check timeout
        if elapsed >= timeout_seconds:
            trade["ai_stop_status"] = "TIMEOUT_BASELINE_RETAINED"
            trade["ai_stop_reasoning"] = f"Timeout ({timeout_seconds}s) expired without AI stop verdict. Baseline safety stop retained."
            save_callback(trade)
            logger.warning(f"⏱️ [AI STOP-LOSS TIMEOUT] {timeout_seconds}s elapsed without verdict. Baseline broker stop retained.")
            for p in (PENDING_SL_FILE_JSON, PENDING_SL_FILE_MD):
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
        return None
"""

cli_marker = '# CLI Helper to submit verdicts or inspect pending consultations'
assert cli_marker in content, "cli_marker not found in content"
content = content.replace(cli_marker, sl_methods + "\n\n" + cli_marker, 1)

# 3. Update CLI parser to support --set-sl and --invalidation
old_cli = """    parser.add_argument("--reason", type=str, default="", help="Rationale for approval or veto")
    parser.add_argument("--trailing", type=str, default="runner_ema9", choices=["runner_ema9", "tight_ema20", "standard"])
    args = parser.parse_args()"""

new_cli = """    parser.add_argument("--reason", type=str, default="", help="Rationale for approval or veto")
    parser.add_argument("--trailing", type=str, default="runner_ema9", choices=["runner_ema9", "tight_ema20", "standard"])
    parser.add_argument("--set-sl", type=float, default=None, help="Set AI Stop-Loss price for filled position")
    parser.add_argument("--invalidation", type=float, default=None, help="Set underlying Spot invalidation level")
    args = parser.parse_args()"""

assert old_cli in content, "old_cli not found in content"
content = content.replace(old_cli, new_cli, 1)

cli_body_marker = "    if args.approve or args.veto:"
new_cli_body = """    if args.set_sl is not None:
        payload = {
            "ai_stop_price": args.set_sl,
            "spot_invalidation_level": args.invalidation,
            "trailing_style": args.trailing,
            "reasoning": args.reason or "Manual stop-loss set via CLI",
            "submitted_at": datetime.now().isoformat()
        }
        SL_VERDICT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SL_VERDICT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"\\n[AI STOP-LOSS] Submitted Stop: ₹{args.set_sl:.2f}")
        if args.invalidation:
            print(f"Spot Invalidation: {args.invalidation:.1f}")
        print(f"Reason: {payload['reasoning']}\\n")
        sys.exit(0)

    if args.approve or args.veto:"""

assert cli_body_marker in content, "cli_body_marker not found in content"
content = content.replace(cli_body_marker, new_cli_body, 1)

with open("ai_consultant.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully updated ai_consultant.py")
