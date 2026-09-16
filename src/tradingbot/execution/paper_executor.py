"""PaperExecutor (STC section 5) - envoie de vrais ordres, mais sur le
testnet Binance : aucun argent reel n'est engage (EF-04 de la STB).

Meme interface que BacktestExecutor : la Strategy et le RiskManager
fonctionnent sans modification (STC section 3.4).
"""

import ccxt

from tradingbot.execution.base import ExecutionAdapter
from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Position, Side


class PaperExecutor(ExecutionAdapter):
    def __init__(
        self,
        exchange_id: str,
        symbol: str,
        api_key: str = "",
        api_secret: str = "",
        exchange=None,
    ):
        """`exchange` permet d'injecter un client deja construit (tests) ;
        sinon un client ccxt reel en sandbox est cree a partir des cles."""
        if exchange is not None:
            self.exchange = exchange
        else:
            if not api_key or not api_secret:
                raise ValueError(
                    "Cles API testnet manquantes (BINANCE_TESTNET_API_KEY / "
                    "BINANCE_TESTNET_API_SECRET dans .env)"
                )
            exchange_class = getattr(ccxt, exchange_id)
            self.exchange = exchange_class({"apiKey": api_key, "secret": api_secret, "enableRateLimit": True})
            self.exchange.set_sandbox_mode(True)

        self.symbol = symbol
        self.base, self.quote = symbol.split("/")
        self.exchange.load_markets()
        self.portfolio = self._load_portfolio_from_exchange()

    def _load_portfolio_from_exchange(self) -> Portfolio:
        balance = self.exchange.fetch_balance()
        quote_balance = balance.get(self.quote, {}).get("free", 0.0) or 0.0
        base_balance = balance.get(self.base, {}).get("free", 0.0) or 0.0

        portfolio = Portfolio(starting_capital=float(quote_balance))
        if base_balance > 0:
            ticker = self.exchange.fetch_ticker(self.symbol)
            portfolio.positions.append(
                Position(quantity=float(base_balance), avg_entry_price=float(ticker["last"]), lot_id=portfolio._next_lot_id)
            )
            portfolio._next_lot_id += 1
        return portfolio

    def _fits_exchange_limits(self, quantity: float, price: float) -> bool:
        """Certaines paires n'acceptent que des quantites entieres (ex: DOGE
        sur Binance, contrairement a BTC/ETH qui acceptent des fractions), et
        toutes ont un montant minimum par ordre. Sans cette verification,
        l'exchange rejette l'ordre et ccxt leve une exception qui plante
        tout le process du bot."""
        market = self.exchange.market(self.symbol)
        limits = market.get("limits", {})
        min_qty = (limits.get("amount") or {}).get("min")
        min_cost = (limits.get("cost") or {}).get("min")
        if min_qty is not None and quantity < min_qty:
            return False
        if min_cost is not None and quantity * price < min_cost:
            return False
        return True

    def place_order(
        self, side: Side, quantity: float, price: float, timestamp: int, reason: str = "", lot_id: int | None = None
    ) -> OrderResult:
        if quantity <= 0:
            return OrderResult(side=side, quantity=quantity, price=price, timestamp=timestamp, status="rejected", reason=reason)

        rounded_quantity = float(self.exchange.amount_to_precision(self.symbol, quantity))
        if rounded_quantity <= 0 or not self._fits_exchange_limits(rounded_quantity, price):
            return OrderResult(side=side, quantity=rounded_quantity, price=price, timestamp=timestamp, status="rejected", reason=reason)

        raw_order = self.exchange.create_order(self.symbol, "market", side.value, rounded_quantity)
        filled_qty = float(raw_order.get("filled") or rounded_quantity)
        avg_price = float(raw_order.get("average") or raw_order.get("price") or price)
        status = "filled" if raw_order.get("status") in (None, "closed") else raw_order["status"]

        result = OrderResult(side=side, quantity=filled_qty, price=avg_price, timestamp=timestamp, status=status, reason=reason)
        self.portfolio.apply_fill(result, lot_id=lot_id)
        return result

    def get_position(self) -> Position:
        return self.portfolio.position

    def get_positions(self) -> list[Position]:
        return list(self.portfolio.positions)

    def get_balance(self) -> float:
        return self.portfolio.cash
