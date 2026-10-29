with open('trading/application/scheduler.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_args = """    parser.add_argument(
        "--live",
        action="store_true",
        help="Arm real-money LIVE broker execution on Zerodha Kite (default is PAPER)",
    )"""

new_args = """    parser.add_argument(
        "--broker",
        type=str,
        default=os.getenv("EXECUTION_BROKER", "proxy"),
        choices=["kite", "breeze", "proxy"],
        help="Broker gateway to use: 'kite' (direct Zerodha Kite), 'breeze' (direct ICICI Breeze), or 'proxy' (local REST API gateway)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Arm real-money LIVE broker execution on Zerodha Kite (default is PAPER)",
    )"""

old_factory = """    trader = trader_factory(quantity=qty, strategy=args.strategy, ai_mode=args.ai_mode)"""
new_factory = """    trader = trader_factory(quantity=qty, strategy=args.strategy, ai_mode=args.ai_mode, broker=args.broker)"""

assert old_args in text, "old_args not found"
assert old_factory in text, "old_factory not found"

text = text.replace(old_args, new_args, 1)
text = text.replace(old_factory, new_factory, 1)

with open('trading/application/scheduler.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Successfully patched trading/application/scheduler.py")
