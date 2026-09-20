"""Engine (STC section 3.2) - boucle principale de l'orchestrateur.

Lit une bougie -> Risk Manager (sorties par lot) -> Strategy -> Risk Manager
(validation) -> Execution -> Portfolio. Cette classe est independante du
mode (backtest/paper) : seul l'ExecutionAdapter injecte change.

Supporte plusieurs positions ("lots") ouvertes simultanement (EF-21) :
chaque lot est verifie independamment pour son stop-loss/take-profit ; un
signal d'achat ouvre un nouveau lot si la limite configuree
(RiskConfig.max_concurrent_positions) n'est pas atteinte ; un signal de
vente de la strategie cloture TOUS les lots ouverts (sortie de tendance
complete, pas une sortie partielle).
"""

from datetime import datetime, timezone
from typing import Callable

from tradingbot.analysis.atr_sizer import AtrSizer
from tradingbot.analysis.price_level_sizer import PriceLevelSizer
from tradingbot.analysis.probability_gate import ProbabilityGate
from tradingbot.analysis.trend_filter import TrendFilter
from tradingbot.execution.base import ExecutionAdapter
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskManager
from tradingbot.shared_pool import InsufficientFunds, SharedPool, credit_for_sell, reserve_for_buy, settle_or_release_buy
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, OrderResult, Position, Side


class Engine:
    def __init__(
        self,
        strategy: Strategy,
        risk_manager: RiskManager,
        executor: ExecutionAdapter,
        portfolio: Portfolio,
        on_fill: Callable[[OrderResult], None] | None = None,
        on_decision: Callable[[Candle, str], None] | None = None,
        probability_gate: ProbabilityGate | None = None,
        trend_filter: TrendFilter | None = None,
        atr_sizer: AtrSizer | None = None,
        price_level_sizer: PriceLevelSizer | None = None,
        shared_pool: SharedPool | None = None,
        instance_name: str | None = None,
        capital_cap: float | None = None,
    ):
        """`shared_pool`/`instance_name`/`capital_cap` activent le panier de
        capital commun (mode paper multi-bots, voir shared_pool.py) : quand
        `shared_pool` est fourni, les achats reservent/reglent leur cout sur
        le panier partage au lieu de se fier uniquement au capital isole de
        `portfolio`, et `capital_cap` (le `capital_allocated` de la config)
        sert de plafond de mise dynamique plutot que de budget exclusif. En
        mode backtest (`shared_pool=None`), le comportement historique base
        sur `portfolio.starting_capital` est inchange."""
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.executor = executor
        self.portfolio = portfolio
        self.on_fill = on_fill
        self.on_decision = on_decision
        self.probability_gate = probability_gate
        self.trend_filter = trend_filter
        self.atr_sizer = atr_sizer
        self.price_level_sizer = price_level_sizer
        self.shared_pool = shared_pool
        self.instance_name = instance_name
        self.capital_cap = capital_cap
        self._last_price: float | None = None
        self._current_day = None  # journee UTC en cours, pour la remise a zero du compteur

    def _roll_daily_counters_if_new_day(self, candle: Candle) -> None:
        """Remet a zero le compteur de perte journaliere au changement de jour
        UTC. Base sur l'horodatage de la BOUGIE et non sur l'horloge systeme :
        un backtest doit rester reproductible, et rejouer la meme periode doit
        toujours donner le meme resultat."""
        day = datetime.fromtimestamp(candle.timestamp / 1000, tz=timezone.utc).date()
        if self._current_day is None:
            self._current_day = day
        elif day != self._current_day:
            self._current_day = day
            self.risk_manager.reset_daily_counters()

    def process_candle(self, candle: Candle) -> None:
        self._roll_daily_counters_if_new_day(candle)
        if self.trend_filter is not None:
            self.trend_filter.update(candle.close)  # mis a jour a chaque bougie, achat ou non
        if self.atr_sizer is not None:
            self.atr_sizer.update(candle)
        if self.price_level_sizer is not None:
            self.price_level_sizer.update(candle)
        messages = self._decide(candle)
        delta_note = self._price_delta_note(candle.close)

        self.portfolio.record_equity(candle.timestamp, candle.close)
        if self.on_decision is not None:
            for message in messages:
                self.on_decision(candle, message + delta_note)

    def process_price_update(self, candle: Candle) -> list[str]:
        """Verifie UNIQUEMENT les sorties par lot (stop-loss/take-profit/
        trailing/verrou de gain/sortie partielle) sur ce prix, sans jamais
        appeler la strategie ni les sizers - pour surveiller les positions a
        une granularite plus fine (ex: bougies 5 minutes) qu'un signal
        d'entree base sur des bougies plus larges (ex: 1 heure), demande de
        l'utilisateur suite au constat qu'un verrou de gain arme puis vendu
        au prix de CLOTURE de la bougie suivante peut deja avoir derape loin
        sous le seuil de declenchement sur un grand timeframe. Ne fait
        JAMAIS avancer l'etat de la strategie (fenetre glissante, etc.) -
        reste coherent avec les entrees decidees sur le timeframe large."""
        self._roll_daily_counters_if_new_day(candle)
        messages = self.check_lot_exits(candle)
        delta_note = self._price_delta_note(candle.close)

        self.portfolio.record_equity(candle.timestamp, candle.close)
        if self.on_decision is not None:
            for message in messages:
                self.on_decision(candle, message + delta_note)
        return messages

    def _price_delta_note(self, price: float) -> str:
        """Ecart de prix vs la bougie precedente, ajoute a chaque log de
        decision pour donner du contexte sur le mouvement de marche (ex: un
        'aucun signal' pendant une chute de prix n'a pas le meme sens qu'un
        'aucun signal' sur un marche stable)."""
        previous = self._last_price
        self._last_price = price
        if previous is None or previous == 0:
            return f" [prix {price:.4f}]"
        delta = price - previous
        delta_pct = delta / previous * 100
        sign = "+" if delta >= 0 else ""
        return f" [prix {price:.4f}, {sign}{delta:.4f} / {sign}{delta_pct:.2f}%]"

    def check_lot_exits(self, candle: Candle) -> list[str]:
        """Sorties par lot (stop-loss / take-profit / trailing stop / verrou
        de gain / sortie partielle), independantes de la strategie - extrait
        de `_decide` pour pouvoir etre appele seul sur des prix plus
        frequents que les bougies vues par la strategie (`process_price_update`)."""
        messages: list[str] = []
        for position in list(self.executor.get_positions()):
            position.peak_price = max(position.peak_price, position.avg_entry_price, candle.close)
            if self.risk_manager.should_stop_loss(position, candle.close):
                self._close_position(position, candle, reason="stop_loss")
                messages.append(f"Vente (stop-loss) lot #{position.lot_id}")
            elif self.risk_manager.should_take_profit(position, candle.close):
                self._close_position(position, candle, reason="take_profit")
                messages.append(f"Vente (take-profit) lot #{position.lot_id}")
            elif self.risk_manager.should_trailing_stop(position, candle.close):
                self._close_position(position, candle, reason="trailing_stop")
                messages.append(f"Vente (trailing stop, pic a {position.peak_price:.4f}) lot #{position.lot_id}")
            elif self.risk_manager.should_profit_lock(position, candle.close):
                self._close_position(position, candle, reason="profit_lock")
                messages.append(f"Vente (verrou de gain, pic a {position.peak_price:.4f}) lot #{position.lot_id}")
            elif self.risk_manager.should_partial_take_profit(position, candle.close):
                fraction = self.risk_manager.config.partial_exit_fraction
                self._partial_close_position(position, candle)
                messages.append(f"Vente partielle ({fraction:.0%} du lot, palier atteint) lot #{position.lot_id}")
        return messages

    def _decide(self, candle: Candle) -> list[str]:
        # 1. Sorties par lot (stop-loss / take-profit / trailing stop), independantes.
        messages: list[str] = list(self.check_lot_exits(candle))

        # 2. Signal de la strategie (achat = nouveau lot, vente = sortie complete).
        signal = self.strategy.on_candle(candle)
        if signal is not None:
            open_positions = self.executor.get_positions()
            open_positions_count = len(open_positions)
            action = "Achat" if signal.side == Side.BUY else "Vente"

            if self.risk_manager.validate(
                signal, open_positions_count=open_positions_count,
                open_positions=open_positions, current_price=candle.close,
            ):
                if signal.side == Side.BUY:
                    messages.append(self._handle_buy_signal(signal, candle))
                else:
                    messages.extend(self._close_all_positions(candle, reason=signal.reason or "signal"))
            else:
                rejection = self.risk_manager.explain_rejection(
                    signal, open_positions_count=open_positions_count,
                    open_positions=open_positions, current_price=candle.close,
                )
                messages.append(f"{action} ignore : {rejection}")

        if not messages:
            messages.append("Aucun signal de la strategie")
        return messages

    def _handle_buy_signal(self, signal, candle: Candle) -> str:
        if self.trend_filter is not None and not self.trend_filter.is_bullish(candle.close):
            return (
                f"Achat bloque par le filtre de tendance "
                f"(prix {candle.close:.4f} sous l'EMA{self.trend_filter.ema_period} a {self.trend_filter.ema:.4f})"
            )

        if self.probability_gate is not None:
            allowed, probability = self.probability_gate.allows_buy()
            if not allowed:
                pct = f"{probability:.0%}" if probability >= 0 else "indisponible"
                return (
                    f"Achat bloque par le filtre de probabilite "
                    f"({pct} de hausse estimee sur 24h, seuil {self.probability_gate.min_probability:.0%})"
                )

        size_multiplier = self.atr_sizer.size_multiplier() if self.atr_sizer is not None else 1.0
        if self.price_level_sizer is not None:
            size_multiplier *= self.price_level_sizer.size_multiplier(candle.close)
        capital_reference = self._buy_capital_reference()
        quantity = self.risk_manager.size_for_signal(capital_reference, candle.close, size_multiplier)

        reservation_id = None
        if self.shared_pool is not None:
            try:
                reservation_id = reserve_for_buy(
                    self.shared_pool, self.instance_name, quantity, candle.close, self.portfolio.fee_pct
                )
            except InsufficientFunds:
                return "Achat ignore : panier de capital commun insuffisant"

        order = self._place_order(Side.BUY, quantity, candle, reason=signal.reason)

        if self.shared_pool is not None:
            settle_or_release_buy(self.shared_pool, reservation_id, order, self.portfolio.fee_pct)

        if order.status == "rejected":
            return "Achat rejete par l'exchange (quantite/montant sous le minimum autorise)"
        reason = f" ({signal.reason})" if signal.reason else ""
        return f"Achat execute{reason}"

    def _buy_capital_reference(self) -> float:
        """Reference de capital passee a `RiskManager.size_for_signal` :
        sans panier commun, le comportement historique (capital isole fixe).
        Avec panier commun, le plafond dynamique de ce bot (capital_cap
        module par sa performance recente, voir shared_pool.effective_cap)
        borne par ce que le panier a reellement disponible - un bot ne peut
        jamais viser plus que ce qui existe globalement, meme si son propre
        plafond est plus grand."""
        if self.shared_pool is None:
            return self.portfolio.starting_capital
        base_cap = self.capital_cap if self.capital_cap is not None else self.portfolio.starting_capital
        effective_cap = self.shared_pool.effective_cap(self.instance_name, base_cap)
        return min(effective_cap, self.shared_pool.available_cash())

    def _close_position(self, position: Position, candle: Candle, reason: str) -> OrderResult:
        return self._place_order(Side.SELL, position.quantity, candle, reason=reason, lot_id=position.lot_id)

    def _partial_close_position(self, position: Position, candle: Candle) -> OrderResult:
        sell_quantity = position.quantity * self.risk_manager.config.partial_exit_fraction
        return self._place_order(Side.SELL, sell_quantity, candle, reason="partial_take_profit", lot_id=position.lot_id)

    def _close_all_positions(self, candle: Candle, reason: str) -> list[str]:
        messages = []
        for position in list(self.executor.get_positions()):
            order = self._close_position(position, candle, reason=reason)
            if order.status == "rejected":
                messages.append(f"Vente rejetee par l'exchange pour le lot #{position.lot_id}")
            else:
                messages.append(f"Vente executee (lot #{position.lot_id}, {reason})" if reason else f"Vente executee (lot #{position.lot_id})")
        return messages

    def _place_order(
        self, side: Side, quantity: float, candle: Candle, reason: str = "", lot_id: int | None = None
    ) -> OrderResult:
        realized_before = self.portfolio.realized_pnl
        order = self.executor.place_order(side, quantity, candle.close, candle.timestamp, reason=reason, lot_id=lot_id)

        # Alimente le garde-fou de perte journaliere (EF-71). Sans cet appel,
        # `max_daily_loss_pct` etait une configuration MORTE : presente dans
        # toutes les configs, annoncee dans le README, testee unitairement, et
        # jamais alimentee - donc `_halted_for_today` ne passait jamais a True.
        # Reference : le capital de depart, seule base stable d'un trade a
        # l'autre (meme raisonnement que `size_for_signal`).
        realized_delta = self.portfolio.realized_pnl - realized_before
        if realized_delta and self.portfolio.starting_capital:
            self.risk_manager.record_realized_pnl_pct(
                realized_delta / self.portfolio.starting_capital
            )

        if self.shared_pool is not None and side == Side.SELL:
            # Vente : quantite/prix deja connus, pas de reservation prealable
            # necessaire (contrairement a l'achat) - on reverse directement
            # le produit net au panier commun.
            base_cap = self.capital_cap if self.capital_cap is not None else self.portfolio.starting_capital
            credit_for_sell(
                self.shared_pool, self.instance_name, order, self.portfolio.fee_pct,
                self.portfolio.trade_history, base_cap,
            )
        if self.on_fill is not None:
            self.on_fill(order)
        return order

    def run_backtest(self, candles: list[Candle]) -> None:
        for candle in candles:
            self.process_candle(candle)
