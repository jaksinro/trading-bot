"""BacktestExecutor (STC section 5) - simule les fills sans reseau ni cle API.

Premier adapter developpe : c'est le seul qui ne necessite aucune cle API,
il permet de valider tout le pipeline (EF-03 de la STB) avant de brancher
un exchange reel.
"""

from tradingbot.execution.base import ExecutionAdapter
from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Position, Side


class BacktestExecutor(ExecutionAdapter):
    sizes_on_cash = True

    def __init__(self, portfolio: Portfolio):
        self.portfolio = portfolio

    def place_order(
        self, side: Side, quantity: float, price: float, timestamp: int, reason: str = "", lot_id: int | None = None
    ) -> OrderResult:
        if quantity <= 0:
            return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected", reason=reason)

        # EF-99 : jamais de credit - un achat dont le cout + frais depasse le cash est refuse.
        if side == Side.BUY and quantity * price * (1 + self.portfolio.fee_pct) > self.portfolio.cash + 1e-9:
            return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected", reason=reason)

        order = OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="filled", reason=reason)
        self.portfolio.apply_fill(order, lot_id=lot_id)
        return order

    def get_position(self) -> Position:
        return self.portfolio.position

    def get_positions(self) -> list[Position]:
        return list(self.portfolio.positions)

    def get_balance(self) -> float:
        return self.portfolio.cash
