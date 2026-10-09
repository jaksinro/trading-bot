"""Types partages entre tous les composants (STC section 3)."""

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Candle:
    timestamp: int  # unix ms
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    side: Side
    reason: str = ""
    # EF-97 : niveaux de sortie PROPRES a ce trade (ex. stop sous la meche de rejet,
    # objectif a 2 fois le risque), attaches au lot achete et surveilles par le
    # moteur comme le stop-loss. None = seuls les reglages de risque du bot.
    stop_price: float | None = None
    target_price: float | None = None
    # EF-104 : position visee par le signal. "short" : SELL ouvre une vente a
    # decouvert, BUY la rachete. "long" (defaut) : BUY achete, SELL revend.
    position_side: str = "long"


@dataclass(frozen=True)
class Quote:
    """Cotation a deux cotes (market making, etape 7 feuille de route
    performance) - un `Signal` directionnel ne peut pas exprimer "coter
    bid ET ask en meme temps avec des prix explicites". `bid_price`/
    `ask_price` a `None` signifie "ne pas coter ce cote ce cycle" (ex:
    inventaire au plafond -> pas de bid ; inventaire nul -> pas d'ask)."""
    bid_price: float | None
    ask_price: float | None
    bid_qty: float
    ask_qty: float
    reason: str = ""


@dataclass(frozen=True)
class FundingRatePoint:
    """Un versement de funding sur un contrat perpetuel (etape 8, feuille de
    route performance - funding rate arbitrage). `funding_rate` est le taux
    de CETTE echeance (ex: 0.0001 = 0.01%), pas un taux annualise."""
    timestamp: int  # unix ms, moment du prelevement
    funding_rate: float


@dataclass(frozen=True)
class OrderResult:
    side: Side
    quantity: float
    price: float
    timestamp: int
    status: str  # "filled" | "rejected"
    reason: str = ""  # "stop_loss" | "take_profit" | raison du signal de strategie
    # EF-104 : sens de la position concernee. "short" : un SELL ouvre une position
    # vendeuse, un BUY la ferme (rachat). "long" (defaut) : comportement historique.
    position_side: str = "long"


@dataclass
class Position:
    """Un lot achete. Plusieurs positions peuvent etre ouvertes en meme
    temps sur une instance (voir RiskConfig.max_concurrent_positions) -
    `lot_id` les distingue pour cloturer la bonne lors d'une vente."""
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    entry_timestamp: int = 0
    lot_id: int = 0
    entry_fee: float = 0.0  # frais payes a l'achat, deduits du P&L a la revente
    peak_price: float = 0.0  # plus haut prix observe depuis l'entree (trailing stop)
    partial_exit_done: bool = False  # sortie partielle (EF-32) deja declenchee sur ce lot, ne se redeclenche pas
    direction: str = "long"            # EF-104 : "long" (achat) ou "short" (vente a decouvert, CFD)
    stop_price: float | None = None    # EF-97 : stop propre au trade (Signal.stop_price)
    target_price: float | None = None  # EF-97 : objectif propre au trade (Signal.target_price)

    @property
    def is_open(self) -> bool:
        return self.quantity != 0.0
