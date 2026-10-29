with open('nifty_trader_scheduler.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_init = """    def __init__(self, quantity: int = DEFAULT_QUANTITY, strategy: str | None = None, ai_mode: str | None = None,
                 *, client: ExecutionGateway | None = None, intelligence: IntelligenceSource | None = None,
                 state_store: PositionStore | None = None, strategy_registry: StrategyRegistry | None = None):
        ensure_environment()
        state_path = state_store.path if state_store is not None else LOG_DIR / "active_position.json"
        self.initialize_safety(state_path, store=state_store)
        self.quantity = quantity
        self.strategy_registry = strategy_registry if strategy_registry is not None else StrategyRegistry()
        self.client = client if client is not None else AIExecutionClient()"""

new_init = """    def __init__(self, quantity: int = DEFAULT_QUANTITY, strategy: str | None = None, ai_mode: str | None = None,
                 *, client: ExecutionGateway | None = None, intelligence: IntelligenceSource | None = None,
                 state_store: PositionStore | None = None, strategy_registry: StrategyRegistry | None = None,
                 broker: str | None = None):
        ensure_environment()
        state_path = state_store.path if state_store is not None else LOG_DIR / "active_position.json"
        self.initialize_safety(state_path, store=state_store)
        self.quantity = quantity
        self.strategy_registry = strategy_registry if strategy_registry is not None else StrategyRegistry()
        if client is not None:
            self.client = client
        elif broker:
            self.client = create_execution_gateway(broker)
        else:
            self.client = AIExecutionClient()"""

assert old_init in text, "old_init not found"
text = text.replace(old_init, new_init, 1)

with open('nifty_trader_scheduler.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Successfully patched nifty_trader_scheduler.py")
