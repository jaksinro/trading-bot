"""Portfolio Tracker (STC section 3.2, EF-07 de la STB).

Supporte plusieurs positions ("lots") ouvertes simultanement (EF-21) : chaque
achat cree un nouveau lot independant avec son propre prix d'entree, chaque
vente ferme un lot precis (identifie par `lot_id`). Par defaut
(max_concurrent_positions=1 dans la config de risque), le comportement est
identique a l'ancien modele a une seule position.

Simule aussi les frais de transaction (EF-22) : un pourcentage est deduit a
l'achat ET a la vente, comme le ferait reellement un exchange.
"""

from dataclasses import dataclass, field
from typing import Callable

from tradingbot.types import OrderResult, Position, Side


@dataclass
class Portfolio:
    starting_capital: float
    fee_pct: float = 0.0
    cash: float = field(init=False)
    positions: list[Position] = field(default_factory=list)
    equity_curve: list[tuple[int, float]] = field(default_factory=list)
    realized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    trade_history: list[dict] = field(default_factory=list)
    on_trade_closed: Callable[[dict], None] | None = None
    _next_lot_id: int = field(default=1, init=False, repr=False)

    def __post_init__(self):
        self.cash = self.starting_capital

    @property
    def position(self) -> Position:
        """Compatibilite : le premier lot ouvert (le plus ancien), ou une
        position vide s'il n'y en a aucun. A utiliser uniquement la ou une
        seule position est attendue (max_concurrent_positions=1)."""
        return self.positions[0] if self.positions else Position()

    @property
    def total_position_quantity(self) -> float:
        return sum(p.quantity for p in self.positions)

    def open_new_lot(self, order: OrderResult, fee: float) -> Position:
        """Cree un nouveau lot ouvert a partir d'un ordre d'achat execute."""
        position = Position(
            quantity=order.quantity,
            avg_entry_price=order.price,
            entry_timestamp=order.timestamp,
            lot_id=self._next_lot_id,
            entry_fee=fee,
            peak_price=order.price,
            direction=order.position_side,
        )
        self._next_lot_id += 1
        return position

    def apply_fill(self, order: OrderResult, lot_id: int | None = None) -> None:
        """`lot_id` precise quel lot fermer lors d'une vente (obligatoire des
        que plusieurs positions peuvent etre ouvertes en meme temps). Sans
        `lot_id`, on ferme le plus ancien (FIFO) - comportement historique,
        correct tant qu'il n'y a jamais plus d'un lot ouvert."""
        if order.status != "filled":
            return

        gross = order.quantity * order.price
        fee = gross * self.fee_pct
        self.total_fees_paid += fee

        # EF-104 : un BUY ouvre une position acheteuse, un SELL "short" ouvre une
        # vente a decouvert. Dans les deux cas le montant engage est immobilise
        # (position entierement couverte, sans levier : jamais de cash negatif).
        opening = (order.side == Side.BUY) == (order.position_side != "short")
        if opening:
            self.cash -= gross + fee
            self.positions.append(self.open_new_lot(order, fee))
            return

        target_lot_id = lot_id if lot_id is not None else (self.positions[0].lot_id if self.positions else None)
        if target_lot_id is None:
            return
        idx = next((i for i, p in enumerate(self.positions) if p.lot_id == target_lot_id), None)
        if idx is None:
            return

        position = self.positions[idx]
        # Vente a decouvert : on recupere le montant immobilise plus l'ecart
        # (entree - sortie) - meme formule de P&L ensuite que pour un achat.
        close_value = (gross if position.direction != "short"
                       else order.quantity * (2 * position.avg_entry_price - order.price))
        net_proceeds = close_value - fee
        is_partial = order.quantity < position.quantity - 1e-12  # marge flottante

        if is_partial:
            # Sortie partielle (EF-32) : seule une FRACTION de la position est
            # vendue, le lot reste ouvert avec le reste (meme prix d'entree,
            # meme lot_id). Le frais d'entree est reparti au prorata de la
            # quantite vendue, pour que le P&L de CHAQUE portion (celle-ci et
            # celle qui reste) reste correct - sans ca, la portion restante
            # se verrait facturer un frais d'entree qu'elle ne "doit" plus.
            sold_fraction = order.quantity / position.quantity
            entry_fee_share = position.entry_fee * sold_fraction
            entry_value = position.avg_entry_price * order.quantity
            trade_pnl = net_proceeds - entry_value - entry_fee_share
            self.realized_pnl += trade_pnl
            trade = {
                "timestamp": order.timestamp,
                "pnl": trade_pnl,
                "entry_price": position.avg_entry_price,
                "entry_timestamp": position.entry_timestamp,
                "exit_price": order.price,
                "quantity": order.quantity,
                "reason": order.reason,
                "lot_id": position.lot_id,
                "direction": position.direction,
                "fees_paid": fee + entry_fee_share,
                "partial": True,
            }
            self.trade_history.append(trade)
            self.cash += net_proceeds
            position.quantity -= order.quantity
            position.entry_fee -= entry_fee_share
            position.partial_exit_done = True
            if self.on_trade_closed is not None:
                self.on_trade_closed(trade)
            return

        closed = self.positions.pop(idx)
        entry_value = closed.avg_entry_price * order.quantity
        trade_pnl = net_proceeds - entry_value - closed.entry_fee
        self.realized_pnl += trade_pnl
        trade = {
            "timestamp": order.timestamp,
            "pnl": trade_pnl,
            "entry_price": closed.avg_entry_price,
            "entry_timestamp": closed.entry_timestamp,
            "exit_price": order.price,
            "quantity": order.quantity,
            "reason": order.reason,
            "lot_id": closed.lot_id,
            "direction": closed.direction,
            "fees_paid": fee + closed.entry_fee,
        }
        self.trade_history.append(trade)
        self.cash += net_proceeds
        if self.on_trade_closed is not None:
            self.on_trade_closed(trade)

    def equity(self, current_price: float) -> float:
        return self.cash + sum(position_value(p, current_price) for p in self.positions)

    def record_equity(self, timestamp: int, current_price: float) -> None:
        self.equity_curve.append((timestamp, self.equity(current_price)))


def position_value(position: Position, price: float) -> float:
    """Valeur d'un lot au cours `price` : quantite x cours pour un achat ; pour
    une vente a decouvert (EF-104), montant immobilise + (entree - cours) x quantite."""
    if position.direction == "short":
        return position.quantity * (2 * position.avg_entry_price - price)
    return position.quantity * price
