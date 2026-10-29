# ADR-0002: Retire penny-option price-only veto policy

- **Status:** OWNER DIRECTION CONFIRMED; EXISTING LIVE FILTER REMOVAL NOT IMPLEMENTED
- **Date:** 2026-10-29
- **Change class:** POLICY (future behavior change)
- **Related policy:** POL-03
- **Branch:** `feature/r01-approved-policy-contracts-20261029`

## Decision

The owner states that trading must **not be biased by an arbitrary NIFTY
spot level or an option's "penny" price label**. There is no approved
₹12/₹30 penny-option threshold and no replacement arbitrary fixed price
floor. In particular **do not introduce** a new 0DTE premium-only veto.

The underlying NIFTY spot remains valid context for technical signals,
contract/strike identification and structural invalidation when actually
needed. This decision is **not** permission to ignore expiry risks,
instrument identity, minimum broker execution requirements, liquidity,
fresh bid/ask, margin affordability, or AI consultation. Every actual BUY
still requires the real consultation verdict and all independent safety
checks; a veto is not automatically converted to approval.

## Existing runtime code not yet reconciled

- `ai_consultant.py` contains the old **Trap 2** decision vetoing a 0DTE
  candidate if option entry premium is below ₹12.
- `config/rules_playbook.md` presents that rule as active.
- `config/trading.json` includes
  `option_selection.min_option_premium=15` and
  `max_option_premium=135`.
- `entry_policy.py` uses both values when calculating approved
  entry-price bounds; `trading/application/selection.py` uses the
  maximum as a candidate filter. A maximum price filter is not the same
  as a penny veto, and is not automatically classified as unsafe; it
  must be reviewed against the owner's no-price-bias requirement.
- `config/trading.json` has `use_current_expiry_on_0dte=false` and
  existing market/expiry guardrails; these are separate policies.

The owner's clarification **settles the business rule**; it is not
evidence that old runtime price-only filters have been deactivated.
This commit intentionally changes no production signal, price bound,
consultation gate, candidate selection, trading config or OMS orders.

## Proposed safe implementation review

1. Characterize when Trap 2 and both premium bounds are consulted in
   `rules`, `playbook`, `chat` and other consultation modes, and
   during option selection and final order validation.
2. Separate arbitrary price-class rejection from executable-ask
   affordability, quote freshness/spread/liquidity and exact-contract
   0DTE/expiry identity.
3. Draft a narrow, owner-reviewable code change that removes **only**
   unjustified fixed-price bias. The change must not turn a real
   consultation veto/error/stale approval into an unconditional BUY.
4. Add and eventually execute offline parity/failure fixtures including
   zero/negative/stale quotes, penny-priced but liquid contracts, 0DTE,
   insufficient margin and vetoed consultation. Supervised broker UAT
   is required separately before deployment.
5. Document potential increase in trade count/exposure and safe rollback.
   Existing open positions must keep their protection and provenance.

## Live status

No trading behavior has been changed; no tests have been run at the
owner's request. This direction must be considered by any R01 LIVE
integration and must not be represented as deployed.
