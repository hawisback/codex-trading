"""Small structural interfaces for the application's external dependencies.

These protocols describe existing contracts. They introduce no runtime type
coercion, validation rules, or replacement of the actual AI consultant.
"""

from pathlib import Path
from typing import Any, Callable, ContextManager, Iterable, Protocol

JsonObject = dict[str, Any]


class JsonTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        payload: JsonObject | None = None,
        *,
        headers: dict[str, str],
        timeout: float,
        retry_reads: bool,
        deadline: Callable[[], float | None],
        log_path: str,
    ) -> Any: ...


class PositionStore(Protocol):
    path: Path

    def exists(self) -> bool: ...
    def load(self) -> JsonObject: ...
    def save(self, data: JsonObject) -> None: ...
    def delete(self, *, missing_ok: bool = False) -> None: ...


class QuoteReader(Protocol):
    def get_contract_quote(self, instrument_id: str, *, timeout_sec: float = 1.0) -> JsonObject: ...


class MarketReader(Protocol):
    def __call__(self, path: str, timeout: float = 5) -> Any: ...


class OrderReader(Protocol):
    def read_budget(self, seconds: float) -> ContextManager[None]: ...
    def get_status(self) -> JsonObject: ...
    def get_positions(self) -> Any: ...
    def get_orders(self) -> Any: ...
    def get_order(self, order_id: str) -> JsonObject: ...
    def get_funds(self) -> JsonObject: ...


class OrderWriter(Protocol):
    def set_mode(self, mode: str) -> JsonObject: ...
    def place_buy_order(
        self,
        instrument_id: str,
        quantity: int,
        limit_price: float,
        request_id: str | None = None,
        before_submit: Callable[[], Any] | None = None,
    ) -> JsonObject: ...
    def wait_for_fill(
        self,
        order_id: str,
        timeout_sec: float = 15,
        poll_interval: float = 0.5,
        return_on_partial: bool = False,
    ) -> JsonObject: ...
    def cancel_entry_order(self, order_id: str) -> JsonObject: ...
    def place_stop_loss(
        self,
        entry_order_id: str,
        trigger_price: float,
        limit_price: float,
        request_id: str | None = None,
        before_submit: Callable[[], Any] | None = None,
    ) -> JsonObject: ...
    def modify_stop_loss(
        self,
        stop_order_id: str,
        trigger_price: float,
        limit_price: float,
        before_submit: Callable[[], Any] | None = None,
    ) -> JsonObject: ...
    def cancel_stop_loss(self, stop_order_id: str) -> JsonObject: ...
    def wait_for_stop_cancellation(
        self, stop_order_id: str, timeout_sec: int = 10, poll_interval: float = 0.5
    ) -> JsonObject: ...
    def cancel_all_resting_stops_for_symbol(
        self,
        symbol: str,
        *,
        known_stops: Iterable[JsonObject] = (),
        entry_order_ids: Iterable[str] = (),
        scope: JsonObject | None = None,
    ) -> JsonObject: ...
    def exit_position(
        self,
        entry_order_id: str,
        limit_price: float,
        request_id: str | None = None,
        max_retries: int = 3,
        *,
        before_submit: Callable[[JsonObject], Any] | None = None,
        cancel_and_verify: Callable[[], JsonObject] | None = None,
        fresh_price: Callable[[], float | None] | None = None,
        price_preflight: Callable[[JsonObject], Any] | None = None,
    ) -> JsonObject: ...


class ExecutionGateway(QuoteReader, OrderReader, OrderWriter, Protocol):
    """One serialized broker gateway, viewed through its smaller role interfaces."""


class IntelligenceSource(Protocol):
    def get_market_intelligence(self, spot_change_pct: float = 0.0) -> JsonObject: ...
    def stop_worker(self, timeout: float = 1.0) -> bool: ...
