path = "tests/test_macd_momentum_strategy.py"
with open(path, "r", encoding="utf-8") as fp:
    content = fp.read()

new_tests = '''
    def test_ema_confirmation_filters_overextended_crossover(self):
        bars = self.bars(64)
        cfg = {
            "entry": {
                "require_ema_confirmation": True,
                "ema_proximity_pts": 10.0,
                "require_ema20_trend_alignment": True
            }
        }
        strat = MacdMomentumStrategy(cfg)
        now = MarketClock.parse_to_ist(bars[-1]["start_time"])
        with MarketClock.at(now):
            # Overextended: spot is 25 pts away from EMA9
            ctx = {"candles_1m": bars, "spot": 23050.0, "ema_9": 23025.0, "ema_20": 23020.0}
            cand = strat.evaluate(ctx)
            if cand.signal != "NEUTRAL":
                self.fail("Overextended entry should be rejected")

    def test_ema_confirmation_filters_counter_trend_crossover(self):
        bars = self.bars(64)
        cfg = {
            "entry": {
                "require_ema_confirmation": True,
                "ema_proximity_pts": 10.0,
                "require_ema20_trend_alignment": True
            }
        }
        strat = MacdMomentumStrategy(cfg)
        now = MarketClock.parse_to_ist(bars[-1]["start_time"])
        with MarketClock.at(now):
            # Counter-trend: Spot is below EMA20 for CE
            ctx = {"candles_1m": bars, "spot": 23000.0, "ema_9": 23002.0, "ema_20": 23020.0}
            cand = strat.evaluate(ctx)
            self.assertEqual("NEUTRAL", cand.signal)

    def test_min_invalidation_buffer_enforced(self):
        cfg = {
            "entry": {
                "min_invalidation_buffer_pts": 15.0
            }
        }
        strat = MacdMomentumStrategy(cfg)
        # Find count that generates a crossover
        for count in range(54, 121, 2):
            bars = self.bars(count)
            now = MarketClock.parse_to_ist(bars[-1]["start_time"])
            with MarketClock.at(now):
                cand = strat.evaluate({"candles_1m": bars})
                if cand.signal == "BUY_CE":
                    spot = bars[-1]["close"]
                    self.assertLessEqual(cand.invalidation_level, spot - 15.0)
                elif cand.signal == "BUY_PE":
                    spot = bars[-1]["close"]
                    self.assertGreaterEqual(cand.invalidation_level, spot + 15.0)
'''

if "def test_ema_confirmation_filters_overextended_crossover" not in content:
    # Append inside TestMacdMomentumStrategy class
    updated = content + new_tests
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(updated)
    print("Added EMA confirmation tests to test_macd_momentum_strategy.py")
else:
    print("Tests already present")
