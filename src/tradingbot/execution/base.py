"""Interface ExecutionAdapter (STC section 3.4).

Backtest/Paper implementent cette meme interface : la Strategy et le
Risk Manager fonctionnent sans modification dans les deux modes (EF-03,
EF-04 de la STB).
"""

from abc import ABC, abstractmethod

from tradingbot.types import OrderResult, Position, Side


class ExecutionAdapter(ABC):
    # EF-99 : True si l'adapter simule un compte entierement interne (backtest) ;
    # le moteur dimensionne alors les achats sur le CASH disponible et non sur
    # le capital de depart. Les adapters reels (paper/testnet) gardent False :
    # c'est l'exchange qui refuse un achat sans fonds.
    sizes_on_cash: bool = False

    @abstractmethod
    def place_order(
        self, side: Side, quantity: float, price: float, timestamp: int, reason: str = "", lot_id: int | None = None
    ) -> OrderResult:
        """`lot_id` identifie le lot a fermer pour une vente (EF-21, plusieurs
        positions simultanees) ; ignore pour un achat, qui cree toujours un
        nouveau lot. Sans `lot_id` sur une vente, ferme le plus ancien (FIFO)."""
        raise NotImplementedError

    @abstractmethod
    def get_position(self) -> Position:
        """Compatibilite : le premier lot ouvert (le plus ancien), ou une
        position vide. Utiliser get_positions() pour la liste complete."""
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def get_balance(self) -> float:
        raise NotImplementedError
