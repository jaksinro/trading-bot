"""Garde-fou de perte journaliere (EF-71) - tests INTEGRES.

POURQUOI CE FICHIER EXISTE. `max_daily_loss_pct` etait une configuration
MORTE : presente dans toutes les configs, annoncee dans le README, et
**testee unitairement** - mais `record_realized_pnl_pct` n'etait appelee
nulle part dans le code de production, donc l'arret ne se declenchait
jamais. Les tests existants passaient parce qu'ils appellent la methode
DIRECTEMENT au lieu de verifier le comportement du moteur.

Ces tests-ci partent donc tous d'un `Engine` reel joue sur des bougies : ils
echouent si le cablage disparait, ce que les tests unitaires ne savaient pas
faire.
"""
from datetime import datetime, timezone

import pytest

from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
START = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)


class Scripted(Strategy):
    """Strategie pilotee : un signal impose par bougie (None = rien)."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = 0

    def on_candle(self, candle):
        side = self.script[self.seen] if self.seen < len(self.script) else None
        self.seen += 1
        return Signal(side=side) if side is not None else None


def build(script, *, max_daily_loss_pct=0.05, capital=1000.0):
    risk = RiskManager(RiskConfig(
        max_position_size_pct=1.0, max_daily_loss_pct=max_daily_loss_pct,
        stop_loss_pct=None, take_profit_pct=None, max_concurrent_positions=1,
        fee_pct=0.0, block_buy_if_any_position_losing=False,
    ))
    portfolio = Portfolio(starting_capital=capital, fee_pct=0.0)
    engine = Engine(Scripted(script), risk, BacktestExecutor(portfolio), portfolio)
    return engine, risk, portfolio


def candles(prices, start=START, step=HOUR_MS):
    return [Candle(timestamp=start + i * step, open=p, high=p, low=p, close=p, volume=1.0)
            for i, p in enumerate(prices)]


# --- le cablage lui-meme (ce qui manquait) ---


def test_a_realised_loss_is_actually_recorded_by_the_engine():
    """LE test qui manquait : le moteur doit alimenter le compteur. Sans ce
    cablage, `max_daily_loss_pct` ne sert a rien."""
    engine, risk, _ = build([Side.BUY, Side.SELL])

    for candle in candles([100.0, 90.0]):
        engine.process_candle(candle)

    assert risk._daily_pnl_pct < 0, "la perte realisee doit remonter au RiskManager"
    assert abs(risk._daily_pnl_pct - (-0.10)) < 1e-6, "achat a 100, vente a 90 = -10 % du capital"


def test_a_realised_gain_is_recorded_too():
    engine, risk, _ = build([Side.BUY, Side.SELL])

    for candle in candles([100.0, 120.0]):
        engine.process_candle(candle)

    assert risk._daily_pnl_pct > 0


def test_a_loss_beyond_the_limit_halts_further_buying():
    """Perte de 10 % sur un plafond de 5 % : le rachat du meme jour doit etre
    refuse."""
    engine, risk, portfolio = build([Side.BUY, Side.SELL, Side.BUY])

    for candle in candles([100.0, 90.0, 90.0]):
        engine.process_candle(candle)

    assert risk._halted_for_today is True
    assert portfolio.positions == [], "aucun rachat ne devait passer apres l'arret"


def test_a_loss_within_the_limit_does_not_halt():
    engine, risk, portfolio = build([Side.BUY, Side.SELL, Side.BUY])

    # -2 % realise, sous le plafond de 5 %.
    for candle in candles([100.0, 98.0, 98.0]):
        engine.process_candle(candle)

    assert risk._halted_for_today is False
    assert len(portfolio.positions) == 1, "le rachat devait passer"


# --- l'arret ne doit JAMAIS empecher de sortir ---


def test_the_halt_never_blocks_a_sell():
    """Un arret qui empeche de vendre enfermerait dans une position perdante
    le jour meme ou la perte max est atteinte - un garde-fou qui aggrave le
    risque. Meme choix que dans `live_executor.py`."""
    risk = RiskManager(RiskConfig(max_daily_loss_pct=0.05))
    risk.record_realized_pnl_pct(-0.10)

    assert risk._halted_for_today is True
    assert risk.validate(Signal(Side.SELL), open_positions_count=1) is True
    assert risk.validate(Signal(Side.BUY), open_positions_count=0) is False


def test_a_position_opened_before_the_halt_can_still_be_closed():
    """Verification integree du meme principe : la strategie ouvre, une perte
    declenche l'arret, et la vente suivante doit quand meme passer."""
    engine, risk, portfolio = build([Side.BUY, Side.SELL, Side.BUY, None, Side.SELL])

    # 100 -> 90 realise -10 % (arret), le rachat est refuse, puis on demande
    # une vente : elle doit etre acceptee meme si rien n'est ouvert.
    for candle in candles([100.0, 90.0, 90.0, 90.0, 95.0]):
        engine.process_candle(candle)

    assert risk._halted_for_today is True
    assert portfolio.positions == []


# --- remise a zero au changement de journee ---


def test_the_counter_resets_on_a_new_day():
    engine, risk, portfolio = build([Side.BUY, Side.SELL, None, Side.BUY])

    day1 = candles([100.0, 90.0, 90.0])
    day2 = candles([90.0], start=START + DAY_MS)
    for candle in day1 + day2:
        engine.process_candle(candle)

    assert risk._halted_for_today is False, "l'arret ne doit pas survivre au changement de jour"
    assert risk._daily_pnl_pct == 0.0
    assert len(portfolio.positions) == 1, "le rachat du lendemain devait passer"


def test_the_reset_uses_candle_timestamps_not_the_wall_clock():
    """Un backtest doit rester reproductible : rejouer la meme periode doit
    toujours donner le meme resultat, quelle que soit l'heure d'execution."""
    engine, risk, _ = build([Side.BUY, Side.SELL] + [None] * 5)

    # Bougies etalees sur 3 jours, tres loin de la date du jour.
    old = candles([100.0, 90.0], start=int(datetime(2020, 5, 1, tzinfo=timezone.utc).timestamp() * 1000))
    next_day = candles([90.0], start=int(datetime(2020, 5, 2, tzinfo=timezone.utc).timestamp() * 1000))
    for candle in old:
        engine.process_candle(candle)
    assert risk._halted_for_today is True
    engine.process_candle(next_day[0])
    assert risk._halted_for_today is False


def test_the_exit_only_path_also_rolls_the_day():
    """`process_price_update` (surveillance fine des sorties) doit aussi
    declencher la remise a zero : sinon un bot en timeframe double resterait
    bloque tout un jour de plus."""
    engine, risk, _ = build([Side.BUY, Side.SELL])

    for candle in candles([100.0, 90.0]):
        engine.process_candle(candle)
    assert risk._halted_for_today is True

    engine.process_price_update(candles([90.0], start=START + DAY_MS)[0])
    assert risk._halted_for_today is False


# --- interactions a ne pas casser ---


def test_losses_accumulate_across_several_trades_in_the_same_day():
    """Le plafond porte sur le CUMUL de la journee, pas sur un trade isole :
    deux pertes de 3 % doivent declencher un plafond a 5 %."""
    engine, risk, _ = build(
        [Side.BUY, Side.SELL, Side.BUY, Side.SELL], max_daily_loss_pct=0.05,
    )

    for candle in candles([100.0, 97.0, 97.0, 94.09]):
        engine.process_candle(candle)

    assert risk._halted_for_today is True


def test_a_limit_of_zero_means_zero_tolerance_not_disabled():
    """PIEGE A CONNAITRE : `max_daily_loss_pct: 0` ne DESACTIVE pas le
    garde-fou, il le rend maximalement strict - la comparaison
    `_daily_pnl_pct <= -abs(0)` est vraie des la moindre perte. Avant que le
    garde-fou ne soit cable, une telle config ne faisait rien ; elle arrete
    desormais les achats au premier centime perdu. Comportement documente
    plutot que reinvente : il n'existe pas de valeur "desactive" dans
    `RiskConfig` (le champ est un float, pas un `float | None`)."""
    engine, risk, portfolio = build([Side.BUY, Side.SELL, Side.BUY], max_daily_loss_pct=0.0)

    for candle in candles([100.0, 99.9, 99.9]):
        engine.process_candle(candle)

    assert risk._halted_for_today is True
    assert portfolio.positions == [], "avec une tolerance nulle, le rachat est refuse"


def test_buying_alone_never_records_anything():
    """Un achat ne realise aucun P&L : il ne doit pas toucher le compteur."""
    engine, risk, _ = build([Side.BUY, None, None])

    for candle in candles([100.0, 110.0, 120.0]):
        engine.process_candle(candle)

    assert risk._daily_pnl_pct == 0.0


def test_the_reference_is_the_starting_capital():
    """La perte est exprimee en pourcentage du capital de DEPART, seule base
    stable d'un trade a l'autre (meme raisonnement que `size_for_signal`)."""
    engine, risk, _ = build([Side.BUY, Side.SELL], capital=2000.0)

    # 2000 investis a 100, vendus a 95 : -100 sur 2000 = -5 %.
    for candle in candles([100.0, 95.0]):
        engine.process_candle(candle)

    assert abs(risk._daily_pnl_pct - (-0.05)) < 1e-6


@pytest.mark.parametrize("limit,expect_halt", [(0.02, True), (0.05, True), (0.20, False)])
def test_the_configured_limit_is_respected(limit, expect_halt):
    engine, risk, _ = build([Side.BUY, Side.SELL], max_daily_loss_pct=limit)

    for candle in candles([100.0, 90.0]):  # -10 % realise
        engine.process_candle(candle)

    assert risk._halted_for_today is expect_halt
