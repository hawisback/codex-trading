The staged fixtures retain their original market contexts and strategy proposals.
Their expected verdicts were reviewed and refreshed for the current policy:

- Trap 1 is deprecated. Tests of mandatory veto behavior now use active Trap 8.
- Refined Trap 7 retains its veto when no completed, aligned trigger grants an exception.
- Missing contracts remain non-executable through the invalid-entry-envelope gate.
- The configured premium cap is 135; a 67 reference has a 70.35 upper band.
- Configured approval TTL is 15 seconds, while default-policy unit tests retain 5 seconds.
- Selection diagnostics now mention both purchasing power and premium limits.

The refresh changes verdict/envelope fields and diagnostics, not the recorded
market inputs or strategy signal/quantity expectations. Dedicated Path A tests
cover completed candles, handoff identity, veto precedence, reversal stops and
exact-contract historical estimates independently of these frozen fixtures.
