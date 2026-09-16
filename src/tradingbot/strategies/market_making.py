"""Strategie de market making - etape 7 de la feuille de route performance.

Contrairement a sma_cross/scalp_dip/mean_reversion (paris directionnels sur
le sens du prix), le market making ne parie pas sur une direction : il cote
en continu un bid (achat) et un ask (vente) autour du prix courant, et
capture l'ecart (spread) quand les deux se remplissent. L'edge vise est
structurel (le spread lui-meme), pas une prediction de mouvement.

Cette classe n'implemente PAS l'interface `Strategy` (`strategies/base.py`) :
celle-ci suppose une fonction pure `on_candle(candle) -> Signal|None`, sans
etat externe. Le market making depend intrinsequement de l'inventaire
courant (combien l'actif de base est deja detenu) pour decider combien
recentrer ses cotations - ce n'est pas une fonction pure de la seule bougie,
d'ou la methode `quote(candle, inventory)` dediee, pilotee par
`MarketMakingEngine` (voir mm_engine.py) plutot que par `Engine`.

`order_size_quote`/`max_inventory_quote` sont exprimes en devise de
COTATION (ex: USDT), pas en actif de base : une quantite fixe d'actif de
base (ex: "0.01 BTC") ne generaliserait pas d'un symbole a l'autre (0.01 BTC
et 0.01 DOGE n'ont rien a voir en valeur) - la grille de `optimize.py` doit
pouvoir tester les memes valeurs sur plusieurs symboles, comme le fait deja
`max_position_size_pct` (un %, pas une quantite) pour les autres strategies.
"""

from tradingbot.types import Candle, Quote


class MarketMakingStrategy:
    def __init__(
        self,
        spread_pct: float = 0.004,
        order_size_quote: float = 0.0,
        max_inventory_quote: float = 0.0,
        skew_factor: float = 1.0,
    ):
        if spread_pct <= 0:
            raise ValueError("spread_pct doit etre strictement positif")
        if order_size_quote <= 0:
            raise ValueError("order_size_quote doit etre strictement positif")
        if max_inventory_quote <= 0:
            raise ValueError("max_inventory_quote doit etre strictement positif")
        self.spread_pct = spread_pct
        self.order_size_quote = order_size_quote
        self.max_inventory_quote = max_inventory_quote
        self.skew_factor = skew_factor

    def quote(self, candle: Candle, inventory: float) -> Quote | None:
        """`inventory` = quantite d'actif de base deja detenue (fournie par
        l'appelant, typiquement `Portfolio.total_position_quantity`).
        `mid` = prix d'ouverture de la bougie (seul prix connu au moment de
        la decision, avant d'observer le high/low qui servira a simuler les
        fills - voir MarketMakingEngine)."""
        mid = candle.open
        half_spread = mid * self.spread_pct / 2
        order_size_base = self.order_size_quote / mid
        max_inventory_base = self.max_inventory_quote / mid
        inventory_value = inventory * mid

        # Recentrage par l'inventaire : plus le stock est eleve, plus les
        # deux prix sont abaisses (achat moins probable, vente plus
        # probable) pour ramener l'inventaire vers 0. Pas de symetrie
        # negative : en spot, on ne peut pas etre "short" (inventaire < 0).
        skew = (inventory_value / self.max_inventory_quote) * self.skew_factor * mid * self.spread_pct

        bid_price = mid - half_spread - skew
        ask_price = mid + half_spread - skew

        if inventory_value >= self.max_inventory_quote:
            bid_price = None
        if inventory <= 0:
            ask_price = None

        if bid_price is None and ask_price is None:
            return None

        return Quote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_qty=order_size_base,
            ask_qty=min(order_size_base, inventory) if inventory > 0 else 0.0,
            reason="market_making",
        )
