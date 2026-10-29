# R01 owner-policy implementation status

**Branch:** `feature/r01-approved-policy-contracts-20261029`
**Date:** 2026-10-29
**Release class:** OFFLINE IMPLEMENTATION / POLICY DESIGN; **not live enabled**
**Tests:** authored only; not run at owner's request

This increment preserves production mode/configuration/OMS/entry/exit
behavior. In particular it does not replace the active MACD strategy's
compounding milestones, does not expand today's two-entry strategy cap,
does not unify trailing stops, and does not change any LIVE broker
authorization, consultation or veto.

| Policy | Owner direction | Current implementation / remaining gate |
| --- | --- | --- |
| POL-01 | Capital tier ceiling 2/4/6/8/10, max 10 | **Implemented as pure offline preview** with exact inclusive boundaries and explicit undecided basis; no live sizing changes. Source field requires final owner definition and broker validation. |
| POL-02 | Entry hard cutoff 14:15 IST; square-off trigger 15:15 IST | Already operative hard constants in `trading/domain/limits.py`; JSON still advertises 14:45/15:20. Preserved as-is to avoid behavioral divergence across paths; migration and parity review pending. |
| POL-03 | **No penny-option rule; no spot-level or arbitrary option-premium-band trade bias** | **Owner decision recorded.** No new ₹12/₹30 veto; existing AI sub-₹12 Trap 2, ₹15 minimum and ₹135 maximum premium filters still exist in code/config, pending a separate review to remove unwanted price-only rejection without weakening affordability, quote/expiry integrity, consultation or existing-position protection. No LIVE behavior changed. |
| POL-04 | No static capital assumption for LIVE | Pure preview requires explicit funds and executable option ask; LIVE funding checks unchanged. Broker authentication, account identity and data freshness must be enforced by integration, not this pure code. |
| POL-05 | Up to 10 trades per session, unless unacceptable loss | `MAX_DAILY_ENTRIES=10` already exists, but MACD retains `entry.max_daily_entries=2`. Daily loss threshold, P&L basis and exact trade-counting meaning not selected; no permission to increase trade frequency yet. |
| POL-06 | Strategy-independent stop/trailing by time of day | Architecture direction documented; **no stop modification** until exact stop and ratchet formulas are signed off. No weakening active position protection. |
| POL-07 | Intended production LIVE | Native Kite/Breeze still require explicit `--live`, broker account verification, mode authorization and all existing safety gates. No automatic arming or proxy routing change. |
| POL-08 | Reliable holiday + expiry selection | Architecture direction recorded (exchange calendar + broker instrument master). No change to live expiry inference/source refresh yet; needs provenance, freshness and outage design. |

## How to inspect the approved sizing boundaries offline

No credentials, authenticated broker connection, or order capabilities are
needed. Values below are **made-up demonstration inputs**; they must never
be interpreted as verified broker data.

```bash
python -m tools.owner_policy_preview \
  --capital-basis available_margin \
  --bracket-capital 80000 \
  --available-margin 80000 \
  --executable-option-ask 100 \
  --lot-size 65 \
  --broker-order-limit 650
```

The code explicitly accepts either `available_margin` or `account_equity`
as a **hypothetical comparison input** because the owner has not selected
the live tier capital basis. The CLI is a calculation aid only. A positive
quantity is **not an instruction to trade**.

For example, ₹80,000 falls in the 8-lot tier; ₹80,000.01 falls in
the 10-lot tier. The actual preview ceiling may be lower because of
option affordability, reserve, broker per-order limit and the existing
650-contract hard cap. If the native broker permits only one lot per
single order, the preview caps at one lot; it **does not** silently split
an order into multiple submissions.

## Merge and production gates

1. Review open decisions in `POLICY_DECISIONS.md` and
   `ADR-0001-OWNER-LOT-LADDER.md`.
2. Explicitly settle the tier-capital broker field; the terms “equity”,
   “available funds”, “buying power” and “spot price” are not interchangeable.
3. Define daily-loss stop and cross-strategy trailing rules separately.
4. Capture baseline/replay parity and full offline regression evidence;
   tests were intentionally not executed in this increment.
5. Implement a separate, gated LIVE integration with policy/version stamps,
   broker/account/quote freshness checks, and OMS-aware protection.
6. Require supervised operational acceptance before deployment. An unmerged
   branch is neither production-ready nor evidence that a broker order is safe.

**No change to `main` or live trading deployment is made by this increment.**
