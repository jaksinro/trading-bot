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

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.types import Candle, Quote


class MarketMakingStrategy:
    def __init__(
        self,
        spread_pct: float = 0.004,
        order_size_quote: float = 0.0,
        max_inventory_quote: float = 0.0,
        skew_factor: float = 1.0,
        volatility_adaptive_spread: bool = False,
        atr_period: int = 14,
        atr_baseline_period: int = 100,
        max_spread_multiplier: float = 3.0,
    ):
        """`volatility_adaptive_spread`/`atr_period`/`atr_baseline_period`/
        `max_spread_multiplier` (feuille de route performance, etape 7 piste 2) :
        elargit le spread quand la volatilite recente (ATR, meme mecanique
        que `analysis/atr_sizer.py`) depasse son niveau habituel, pour
        reduire le risque de selection adverse en marche trending (le
        market maker se fait plus facilement "cross" dans un sens quand le
        marche part en tendance forte). Desactive par defaut pour ne pas
        changer le comportement des configurations existantes. Ne RETRECIT
        jamais le spread sous sa valeur configuree (une volatilite sous la
        normale ne justifie pas un spread plus serre que ce qui a ete
        choisi), seulement l'elargir, jamais au-dela de `max_spread_multiplier`."""
        if spread_pct <= 0:
            raise ValueError("spread_pct doit etre strictement positif")
        if order_size_quote <= 0:
            raise ValueError("order_size_quote doit etre strictement positif")
        if max_inventory_quote <= 0:
            raise ValueError("max_inventory_quote doit etre strictement positif")
        if max_spread_multiplier < 1.0:
            raise ValueError("max_spread_multiplier doit etre >= 1.0")
        self.spread_pct = spread_pct
        self.order_size_quote = order_size_quote
        self.max_inventory_quote = max_inventory_quote
        self.skew_factor = skew_factor
        self.volatility_adaptive_spread = volatility_adaptive_spread
        self.max_spread_multiplier = max_spread_multiplier
        self._atr_sizer = (
            AtrSizer(atr_period=atr_period, baseline_period=atr_baseline_period)
            if volatility_adaptive_spread
            else None
        )

    def _spread_multiplier(self) -> float:
        """Lit l'etat ATR tel qu'il etait a la fin de la bougie PRECEDENTE
        (voir `quote()` : mis a jour seulement apres avoir calcule la
        cotation de la bougie courante) - jamais le high/low de la bougie en
        cours, qui ne sont pas encore "connus" au moment de coter (meme
        principe que `mid = candle.open` ci-dessous)."""
        if self._atr_sizer is None:
            return 1.0
        atr = self._atr_sizer.atr
        baseline = self._atr_sizer.baseline
        if atr is None or baseline is None or baseline <= 0:
            return 1.0
        return max(1.0, min(atr / baseline, self.max_spread_multiplier))

    def quote(self, candle: Candle, inventory: float) -> Quote | None:
        """`inventory` = quantite d'actif de base deja detenue (fournie par
        l'appelant, typiquement `Portfolio.total_position_quantity`).
        `mid` = prix d'ouverture de la bougie (seul prix connu au moment de
        la decision, avant d'observer le high/low qui servira a simuler les
        fills - voir MarketMakingEngine)."""
        mid = candle.open
        half_spread = mid * self.spread_pct * self._spread_multiplier() / 2
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

        if self._atr_sizer is not None:
            self._atr_sizer.update(candle)  # apres coup seulement, voir _spread_multiplier()

        if bid_price is None and ask_price is None:
            return None

        return Quote(
            bid_price=bid_price,
            ask_price=ask_price,
            bid_qty=order_size_base,
            ask_qty=min(order_size_base, inventory) if inventory > 0 else 0.0,
            reason="market_making",
        )
