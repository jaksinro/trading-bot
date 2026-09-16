"""MarketMakingEngine (etape 7, feuille de route performance) - boucle
principale dediee au market making, en parallele de `Engine`.

`Engine._decide` suppose un seul signal directionnel par bougie (achat =
ouvre un lot, vente = ferme tous les lots) - ce cycle ne correspond pas au
market making, qui cote les DEUX cotes (bid + ask) a chaque bougie et peut
remplir l'un, l'autre, les deux ou aucun. D'ou un moteur dedie plutot qu'une
extension de `Engine`.

LIMITE CONNUE (documentee dans STB/STC) : il n'existe pas de carnet
d'ordres historique dans ce projet (seulement des bougies OHLCV, voir
data_feed.py), et aucun ordre limite qui reste en attente (BacktestExecutor/
PaperExecutor executent au marche). Les fills sont donc SIMULES a partir du
high/low de la bougie : le bid est considere touche si `candle.low <=
bid_price`, l'ask si `candle.high >= ask_price`. C'est une approximation
raisonnable en l'absence de donnees tick/L2, mais plus optimiste qu'un vrai
carnet (pas de concurrence avec d'autres market makers, pas de glissement
intra-bougie).
"""

from typing import Callable

from tradingbot.execution.base import ExecutionAdapter
from tradingbot.portfolio import Portfolio
from tradingbot.shared_pool import InsufficientFunds, SharedPool, credit_for_sell, reserve_for_buy, settle_or_release_buy
from tradingbot.strategies.market_making import MarketMakingStrategy
from tradingbot.types import Candle, OrderResult, Side


class MarketMakingEngine:
    def __init__(
        self,
        strategy: MarketMakingStrategy,
        executor: ExecutionAdapter,
        portfolio: Portfolio,
        on_fill: Callable[[OrderResult], None] | None = None,
        on_decision: Callable[[Candle, str], None] | None = None,
        shared_pool: SharedPool | None = None,
        instance_name: str | None = None,
        capital_cap: float | None = None,
    ):
        """`shared_pool`/`instance_name`/`capital_cap` : meme role qu'avec
        `Engine` (panier de capital commun, voir shared_pool.py) - le fill du
        bid reserve/regle sur le panier partage, le fill de l'ask le
        credite. `capital_cap` n'est utilise ici que pour l'allocation
        dynamique (`update_allocation_after_trade`), pas pour dimensionner
        les ordres : le market making cote une quantite FIXE
        (`strategy.order_size_base`), pas un % du capital."""
        self.strategy = strategy
        self.executor = executor
        self.portfolio = portfolio
        self.on_fill = on_fill
        self.on_decision = on_decision
        self.shared_pool = shared_pool
        self.instance_name = instance_name
        self.capital_cap = capital_cap

    def process_candle(self, candle: Candle) -> None:
        message = self._decide(candle)
        self.portfolio.record_equity(candle.timestamp, candle.close)
        if self.on_decision is not None:
            self.on_decision(candle, message)

    def _decide(self, candle: Candle) -> str:
        inventory = self.portfolio.total_position_quantity
        quote = self.strategy.quote(candle, inventory)
        if quote is None:
            return "Aucune cotation (inventaire au plafond ou nul des deux cotes)"

        messages = []
        if quote.bid_price is not None and candle.low <= quote.bid_price:
            messages.append(self._fill_bid(quote.bid_price, quote.bid_qty, candle))
        if quote.ask_price is not None and candle.high >= quote.ask_price:
            messages.append(self._fill_ask(quote.ask_price, quote.ask_qty, candle))

        if not messages:
            return f"Cotation posee (bid={quote.bid_price}, ask={quote.ask_price}), aucun fill"
        return " ; ".join(messages)

    def _fill_bid(self, bid_price: float, bid_qty: float, candle: Candle) -> str:
        reservation_id = None
        if self.shared_pool is not None:
            try:
                reservation_id = reserve_for_buy(
                    self.shared_pool, self.instance_name, bid_qty, bid_price, self.portfolio.fee_pct
                )
            except InsufficientFunds:
                return "Fill bid ignore : panier de capital commun insuffisant"

        order = self.executor.place_order(Side.BUY, bid_qty, bid_price, candle.timestamp, reason="market_making_bid")

        if self.shared_pool is not None:
            settle_or_release_buy(self.shared_pool, reservation_id, order, self.portfolio.fee_pct)

        if self.on_fill is not None:
            self.on_fill(order)

        if order.status == "rejected":
            return "Fill bid rejete par l'exchange"
        return "Fill bid execute"

    def _fill_ask(self, ask_price: float, ask_qty: float, candle: Candle) -> str:
        """`ask_qty` (calcule par la strategie a partir de l'inventaire TOTAL,
        potentiellement reparti sur plusieurs lots - chaque fill bid ouvre un
        nouveau lot, voir Portfolio.open_new_lot) peut depasser la quantite
        du lot le plus ancien pris isolement. `Portfolio.apply_fill` (FIFO
        sans lot_id) ne verifie PAS que `order.quantity <= positions[0].quantity`
        - lui passer un montant trop grand en un seul ordre fausserait le
        cout d'acquisition impute (prix d'entree du plus vieux lot applique a
        une quantite qu'il n'a jamais detenue), creant un profit fictif. On
        vend donc lot par lot, en FIFO, avec `lot_id` explicite, jusqu'a
        satisfaire `ask_qty` ou epuiser l'inventaire - jamais plus que ce que
        chaque lot detient reellement."""
        remaining = ask_qty
        fills = 0
        rejections = 0
        for position in list(self.portfolio.positions):
            if remaining <= 1e-12:
                break
            sell_qty = min(remaining, position.quantity)
            order = self.executor.place_order(
                Side.SELL, sell_qty, ask_price, candle.timestamp, reason="market_making_ask", lot_id=position.lot_id
            )

            if self.shared_pool is not None:
                base_cap = self.capital_cap if self.capital_cap is not None else self.portfolio.starting_capital
                credit_for_sell(
                    self.shared_pool, self.instance_name, order, self.portfolio.fee_pct,
                    self.portfolio.trade_history, base_cap,
                )

            if self.on_fill is not None:
                self.on_fill(order)

            if order.status == "rejected":
                rejections += 1
            else:
                fills += 1
                remaining -= order.quantity

        if fills == 0 and rejections == 0:
            return "Fill ask ignore : aucune position a vendre"
        if fills == 0:
            return "Fill ask rejete par l'exchange"
        return f"Fill ask execute ({fills} lot(s))" if rejections == 0 else f"Fill ask execute ({fills} lot(s), {rejections} rejete(s))"

    def run_backtest(self, candles: list[Candle]) -> None:
        for candle in candles:
            self.process_candle(candle)
