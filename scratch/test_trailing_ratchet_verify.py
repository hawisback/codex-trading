import sys, os
sys.path.insert(0, os.path.abspath("."))
from nifty_trader_scheduler import NiftyOptionsTrader

trader = NiftyOptionsTrader()

test_trade = {
    'trade_id': 'test_trade_123',
    'entry_order_id': 'test_order_123',
    'stop_order_id': 'test_stop_123',
    'instrument_id': 'INST-NIFTY-2026-10-19-23050-CE',
    'symbol': 'NIFTY26O1923050CE',
    'quantity': 65,
    'entry_price': 98.80,
    'last_bid': 120.00,
    'peak_bid': 120.00,
    'current_stop_trigger': 69.15,
    'current_stop_limit': 67.75,
    'setup_type': 'CLIMAX_SPRING',
    'invalidation_level': 22969.35,
    'entry_time': '2026-10-19T09:34:13'
}

test_ctx = {
    'spot': 23150.0,
    'session_vwap': 23090.0,
    'ema_9': 23100.0,
    'ema_20': 23100.0,
    'heavyweights': {'advancing': 3, 'declining': 2}
}

# Mock modify_stop_loss to track calls
modified_calls = []
trader.client.modify_stop_loss = lambda sid, trigger_price, limit_price: (
    modified_calls.append((sid, trigger_price, limit_price)) or {'order_id': sid}
)

# Test 1: At 120.0 (gain = +21.4%), peak_gain >= 20%
# Progressive floor tier 20% -> floor_pct = 10% -> floor = 98.8 * 1.1 = 108.68
# peak_bid * 0.9 = 120 * 0.9 = 108.0 -> trail_stop = 108.68 -> 108.70
res1 = trader.manage_open_trades([test_trade], test_ctx, {})
print('Test 1 (At 120.00):')
print('  Modified calls count:', len(modified_calls))
print('  Latest modify args:', modified_calls[-1] if modified_calls else None)
print('  Current stop trigger:', test_trade.get('current_stop_trigger'))
assert len(modified_calls) == 1
assert test_trade.get('current_stop_trigger') == 108.70

# Test 2: Price climbs to 146.50 (+48.3%)
test_trade['peak_bid'] = 146.50
test_trade['last_bid'] = 146.50
res2 = trader.manage_open_trades([test_trade], test_ctx, {})
print('\nTest 2 (At 146.50):')
print('  Modified calls count:', len(modified_calls))
print('  Latest modify args:', modified_calls[-1])
print('  Current stop trigger:', test_trade.get('current_stop_trigger'))
assert len(modified_calls) == 2
assert test_trade.get('current_stop_trigger') == 131.85

# Test 3: Price pulls back below trail_stop (drops to 125.0 < 131.85) -> Must exit immediately!
exit_calls = []
trader.exit_trade = lambda tid, reason, limit_price: exit_calls.append((tid, reason, limit_price)) or {'status': 'FILLED'}
test_trade['last_bid'] = 125.00
res3 = trader.manage_open_trades([test_trade], test_ctx, {})
print('\nTest 3 (Pullback to 125.00 < 131.85):')
print('  Exit calls count:', len(exit_calls))
print('  Exit reason:', exit_calls[0][1] if exit_calls else None)
assert len(exit_calls) == 1
assert 'DYNAMIC TRAILING RATCHET' in exit_calls[0][1]

print('\n============================================================')
print('>>> VERIFICATION PASSED: TRAILING SL RATCHET BUG IS 100% FIXED! <<<')
print('============================================================')
