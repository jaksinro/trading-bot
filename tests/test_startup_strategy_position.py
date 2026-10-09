"""Etat "en position" des strategies au demarrage des bots (EF-102).

Bug constate le 2026-10-09 en construisant l'atelier de backtest (EF-100) :
le rechauffage (`warm_up_strategy`, `ib_warm_up_strategy`) donne l'historique
a la strategie en IGNORANT ses signaux. Une strategie qui retient son propre
etat - achat unique, RSI, Bollinger - pouvait donc finir le rechauffage en se
croyant en position alors que le bot n'avait rien : l'achat unique ne
rachetait jamais, RSI et Bollinger attendaient une vente avant d'acheter. A
l'inverse, une position restauree depuis la base n'etait pas vue par la
strategie, qui ne la revendait jamais sur son propre signal.

Chaque test rejoue le demarrage reel : rechauffage, puis premiere decision du
bot sur la derniere bougie close (`poll_new_closed_candle` -> `Engine`)."""
import pytest

from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.run_backtest import build_strategy
from tradingbot.run_paper import _row_to_candle, poll_new_closed_candle, warm_up_strategy
from tradingbot.types import Position


class FakeExchange:
    def __init__(self, rows):
        self._rows = rows

    def fetch_ohlcv(self, symbol, timeframe, limit):
        return self._rows[-limit:]


def _rows(closes):
    """Une ligne par cloture, plus la bougie en cours (jamais traitee)."""
    rows = [[i * 1000, c, c, c, c, 1.0] for i, c in enumerate(closes)]
    rows.append([len(closes) * 1000, closes[-1], closes[-1], closes[-1], closes[-1], 1.0])
    return rows


def _engine(strategy, portfolio, max_positions=1, stop_loss_pct=None):
    risk = RiskConfig(max_position_size_pct=0.4, stop_loss_pct=stop_loss_pct, fee_pct=0.0,
                      max_concurrent_positions=max_positions)
    return Engine(strategy, RiskManager(risk), BacktestExecutor(portfolio), portfolio)


def _start_bot(strategy_config, closes, restored_position=None, max_positions=1):
    """Demarrage du bot : rechauffage sur toutes les clotures sauf la derniere,
    puis premiere decision sur la derniere. Renvoie le portefeuille."""
    strategy = build_strategy({"strategy": strategy_config})
    exchange = FakeExchange(_rows(closes))
    last_ts = warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, warmup_candles=len(closes) - 1)
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.0)
    if restored_position is not None:
        portfolio.positions = [restored_position]  # comme restore_persisted_state
        portfolio.cash -= restored_position.quantity * restored_position.avg_entry_price
    engine = _engine(strategy, portfolio, max_positions=max_positions)
    first = poll_new_closed_candle(exchange, "ETH/USDT", "1h", last_ts)
    assert first is not None and first.close == closes[-1]  # la derniere cloture est decidee
    engine.process_candle(first)
    return portfolio


def _restored(price=100.0):
    return Position(quantity=1.0, avg_entry_price=price, entry_timestamp=0, lot_id=1, peak_price=price)


RSI = {"type": "rsi_range", "period": 3, "oversold": 30, "overbought": 70}
BOLLINGER = {"type": "mean_reversion", "window": 5, "num_std": 1.0}

FALLING = [100, 101, 102, 103, 102, 100, 97, 93, 88]  # survente des la 6e cloture, et jusqu'au bout
RISING = [100, 99, 100, 99, 100, 101, 102, 103, 105]  # jamais en survente, hausse finale


def test_buy_and_hold_buys_at_startup_when_the_bot_holds_nothing():
    """Son seul signal d'achat etait emis - puis ignore - a la 1re bougie du
    rechauffage : le bot ne detenait rien et n'achetait jamais."""
    portfolio = _start_bot({"type": "buy_and_hold"}, RISING)
    assert len(portfolio.positions) == 1


def test_buy_and_hold_does_not_buy_twice_when_a_position_is_restored():
    portfolio = _start_bot({"type": "buy_and_hold"}, RISING, restored_position=_restored(), max_positions=2)
    assert len(portfolio.positions) == 1


@pytest.mark.parametrize("config", [RSI, BOLLINGER], ids=["rsi", "bollinger"])
def test_oversold_strategy_buys_at_startup_after_a_signal_ignored_during_warm_up(config):
    """Le rechauffage finit en survente : l'achat emis pendant la chauffe a ete
    ignore, la strategie se croyait en position et attendait une vente."""
    portfolio = _start_bot(config, FALLING)
    assert len(portfolio.positions) == 1


@pytest.mark.parametrize("config", [RSI, BOLLINGER], ids=["rsi", "bollinger"])
def test_restored_position_is_sold_on_the_strategy_exit_signal(config):
    """Position restauree depuis la base : la strategie doit se savoir en
    position, sinon son signal de sortie n'est jamais emis."""
    portfolio = _start_bot(config, RISING, restored_position=_restored())
    assert portfolio.positions == []
    assert portfolio.trade_history[-1]["exit_price"] == RISING[-1]


@pytest.mark.parametrize("config", [RSI, BOLLINGER], ids=["rsi", "bollinger"])
def test_restored_position_blocks_a_new_entry(config):
    """Position restauree + survente : pas de 2e achat (meme quand le risque
    autoriserait deux positions)."""
    portfolio = _start_bot(config, FALLING, restored_position=_restored(80.0), max_positions=2)
    assert len(portfolio.positions) == 1


def test_alignment_happens_once_so_a_stop_loss_still_waits_for_the_strategy_exit():
    """L'alignement n'a lieu qu'avant la PREMIERE decision. Apres un stop-loss
    du moteur, RSI attend toujours son propre signal de sortie avant de
    racheter : c'est le comportement mesure par tous les backtests. Un
    alignement a chaque bougie (rachat aussitot en pleine chute) a ete essaye
    et mesure : il degradait 2025-2026 dans la plupart des cas (STC §3.89)."""
    strategy = build_strategy({"strategy": RSI})
    portfolio = Portfolio(starting_capital=1000.0, fee_pct=0.0)
    engine = _engine(strategy, portfolio, stop_loss_pct=0.02)
    for row in _rows(FALLING)[:-1]:
        engine.process_candle(_row_to_candle(row))
    assert [t["reason"] for t in portfolio.trade_history] == ["stop_loss"]
    assert portfolio.positions == []  # pas de rachat : la survente continue, mais RSI n'est pas remonte a 70
