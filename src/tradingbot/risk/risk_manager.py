"""Risk Manager (STC section 6, EF-09 de la STB).

Valide chaque signal avant transmission a l'Execution Adapter. Un signal
de strategie ne devient jamais un ordre sans passer par cette validation.
"""

from dataclasses import dataclass

from tradingbot.types import Position, Side, Signal


@dataclass
class RiskConfig:
    max_position_size_pct: float = 0.10  # % du capital par position
    stop_loss_pct: float | None = 0.02  # None = pas de stop-loss (etape 9, decision assumee - voir dip_bounce.py)
    take_profit_pct: float | None = None
    max_daily_loss_pct: float = 0.05
    max_concurrent_positions: int = 1  # EF-21 : 1 = comportement historique (une seule position a la fois)
    fee_pct: float = 0.001  # EF-22 : frais par ordre (0.1% = taker Binance spot typique)
    block_buy_if_any_position_losing: bool = True  # EF-23 : n'empile pas les positions perdantes
    trailing_stop_pct: float | None = None  # EF-24 : stop suiveur, desactive par defaut
    partial_take_profit_pct: float | None = None  # EF-32 : palier de sortie partielle, desactive par defaut
    partial_exit_fraction: float = 0.5  # part du lot vendue au palier partiel (le reste continue avec stop/trailing)
    profit_lock_arm_pct: float | None = None  # etape 9 : arme le verrou une fois ce gain latent depasse
    profit_lock_trigger_pct: float | None = None  # ... puis vend si le gain retombe a ou sous ce seuil


@dataclass
class MarketMakingConfig:
    """Config de risque dediee au market making (etape 7, feuille de route
    performance) - a cote de `RiskConfig`, pas une extension : les concepts
    stop-loss/take-profit/max_position_size_pct (paris directionnels) n'ont
    pas de sens pour une strategie qui cote les deux cotes en continu. Ne
    porte QUE les champs a portee "risque" ; les parametres de cotation
    (spread, taille d'ordre, inventaire max, skew) appartiennent a
    `MarketMakingStrategy` elle-meme (strategies/market_making.py), pas a
    cette config - eviter de les dupliquer aux deux endroits."""
    fee_pct: float = 0.001  # frais par ordre, meme role que RiskConfig.fee_pct
    max_daily_loss_pct: float = 0.05  # meme garde-fou global que RiskConfig


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self._daily_pnl_pct = 0.0
        self._halted_for_today = False

    def reset_daily_counters(self) -> None:
        self._daily_pnl_pct = 0.0
        self._halted_for_today = False

    def record_realized_pnl_pct(self, pnl_pct: float) -> None:
        self._daily_pnl_pct += pnl_pct
        if self._daily_pnl_pct <= -abs(self.config.max_daily_loss_pct):
            self._halted_for_today = True

    def size_for_signal(self, capital: float, price: float, size_multiplier: float = 1.0) -> float:
        """Calcule la quantite a acheter selon max_position_size_pct.
        `capital` doit etre le capital DE REFERENCE de l'instance, pas le
        cash restant de CETTE seule instance - sinon chaque position
        supplementaire serait plus petite que la precedente sans raison. En
        mode backtest/isole, c'est le capital alloue initial (fixe). En mode
        paper avec panier commun (STC section 3.5 revisee), l'appelant
        (Engine._buy_capital_reference) passe `min(plafond dynamique de ce
        bot, cash disponible dans le panier partage)` : la reference reste
        stable pour CE bot d'un trade a l'autre (meme raisonnement que
        ci-dessus), mais est bornee par ce que le panier commun a
        reellement, puisque plusieurs bots peuvent y puiser en meme temps.
        `size_multiplier` (feuille de route performance, etape 2) permet a
        un composant externe (AtrSizer) de REDUIRE la taille en periode de
        forte volatilite - jamais de l'augmenter au-dela du plafond
        `max_position_size_pct` (defaut 1.0 = comportement historique)."""
        position_value = capital * self.config.max_position_size_pct * size_multiplier
        return position_value / price

    def should_stop_loss(self, position: Position, current_price: float) -> bool:
        if not position.is_open or position.quantity <= 0 or self.config.stop_loss_pct is None:
            return False
        loss_pct = (position.avg_entry_price - current_price) / position.avg_entry_price
        return loss_pct >= self.config.stop_loss_pct

    def should_take_profit(self, position: Position, current_price: float) -> bool:
        if not position.is_open or position.quantity <= 0 or self.config.take_profit_pct is None:
            return False
        gain_pct = (current_price - position.avg_entry_price) / position.avg_entry_price
        return gain_pct >= self.config.take_profit_pct

    def should_trailing_stop(self, position: Position, current_price: float) -> bool:
        """EF-24 : sort si le prix retombe de `trailing_stop_pct` sous le
        plus haut observe depuis l'entree (pas depuis le prix d'achat) -
        protege les gains acquis sans plafonner le potentiel de hausse."""
        if not position.is_open or position.quantity <= 0 or self.config.trailing_stop_pct is None:
            return False
        peak = max(position.peak_price, position.avg_entry_price)
        if peak <= 0:
            return False
        drop_from_peak_pct = (peak - current_price) / peak
        return drop_from_peak_pct >= self.config.trailing_stop_pct

    def should_profit_lock(self, position: Position, current_price: float) -> bool:
        """Etape 9 (feuille de route performance) : verrou de gain a deux
        seuils - une fois que le PIC de gain latent depuis l'entree a
        depasse `profit_lock_arm_pct` (le verrou s'ARME), vend des que le
        gain COURANT retombe a ou sous `profit_lock_trigger_pct`. Different
        du trailing stop (EF-24, distance fixe depuis le pic quel qu'il
        soit) : ici le plancher de sortie est un seuil ABSOLU une fois arme,
        pas une distance relative au pic - peu importe a quel point le pic a
        depasse le seuil d'armement, on ne vend que si le gain retombe
        jusqu'a ce plancher precis. Reutilise `position.peak_price`, deja
        maintenu par Engine._decide exactement comme pour should_trailing_stop -
        aucun nouveau champ sur `Position`."""
        if not position.is_open or position.quantity <= 0:
            return False
        if self.config.profit_lock_arm_pct is None or self.config.profit_lock_trigger_pct is None:
            return False
        peak = max(position.peak_price, position.avg_entry_price)
        peak_gain_pct = (peak - position.avg_entry_price) / position.avg_entry_price
        if peak_gain_pct < self.config.profit_lock_arm_pct:
            return False  # jamais arme : le pic n'a jamais depasse le seuil d'armement
        current_gain_pct = (current_price - position.avg_entry_price) / position.avg_entry_price
        return current_gain_pct <= self.config.profit_lock_trigger_pct

    def should_partial_take_profit(self, position: Position, current_price: float) -> bool:
        """EF-32 : declenche une sortie partielle (voir Portfolio.apply_fill)
        une seule fois par lot (`position.partial_exit_done`), a un palier
        de gain distinct du take-profit complet - typiquement plus bas, pour
        securiser une partie du gain tot tout en laissant courir le reste
        avec le stop-loss/trailing stop existant."""
        if not position.is_open or position.quantity <= 0:
            return False
        if self.config.partial_take_profit_pct is None or position.partial_exit_done:
            return False
        gain_pct = (current_price - position.avg_entry_price) / position.avg_entry_price
        return gain_pct >= self.config.partial_take_profit_pct

    def validate(
        self,
        signal: Signal,
        *,
        open_positions_count: int,
        open_positions: list[Position] | None = None,
        current_price: float | None = None,
    ) -> bool:
        """Retourne True si le signal peut etre transmis a l'execution.
        `open_positions`/`current_price` sont optionnels : necessaires
        uniquement pour la regle anti-accumulation (EF-23) sur un achat."""
        if self._halted_for_today:
            return False
        if signal.side == Side.BUY:
            if open_positions_count >= self.config.max_concurrent_positions:
                return False
            if self.config.block_buy_if_any_position_losing and open_positions and current_price is not None:
                if any(current_price < p.avg_entry_price for p in open_positions):
                    return False
            return True
        return open_positions_count > 0  # SELL : rien a vendre si aucune position ouverte

    def explain_rejection(
        self,
        signal: Signal,
        *,
        open_positions_count: int,
        open_positions: list[Position] | None = None,
        current_price: float | None = None,
    ) -> str:
        """Message lisible expliquant pourquoi `validate` a refuse ce signal
        (utilise pour le journal des decisions affiche sur le dashboard)."""
        if self._halted_for_today:
            return "trading suspendu pour aujourd'hui (perte journaliere max atteinte)"
        if signal.side == Side.BUY:
            if open_positions_count >= self.config.max_concurrent_positions:
                return (
                    f"limite de {self.config.max_concurrent_positions} position(s) simultanee(s) "
                    f"atteinte ({open_positions_count} ouverte(s))"
                )
            if self.config.block_buy_if_any_position_losing and open_positions and current_price is not None:
                if any(current_price < p.avg_entry_price for p in open_positions):
                    return "au moins une position ouverte est deja en perte latente (pas d'achat supplementaire)"
        return "aucune position a vendre"
