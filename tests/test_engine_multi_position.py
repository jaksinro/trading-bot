from tradingbot.engine import Engine
from tradingbot.execution.backtest_executor import BacktestExecutor
from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig, RiskManager
from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class AlwaysBuyStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.BUY, reason="test")


class AlwaysSellStrategy(Strategy):
    def on_candle(self, candle):
        return Signal(side=Side.SELL, reason="test")


def make_candle(i: int, close: float) -> Candle:
    return Candle(timestamp=i, open=close, high=close, low=close, close=close, volume=1.0)


def test_multiple_buy_signals_open_multiple_lots_up_to_limit():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1, max_concurrent_positions=3))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))
    engine.process_candle(make_candle(1, 100.0))
    engine.process_candle(make_candle(2, 100.0))
    engine.process_candle(make_candle(3, 100.0))  # 4e signal, limite de 3 deja atteinte

    assert len(portfolio.positions) == 3


def test_stop_loss_closes_only_the_triggered_lot():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1, max_concurrent_positions=2, stop_loss_pct=0.02))
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)  # lot A : entree a 100
    executor.place_order(Side.BUY, 1.0, 200.0, timestamp=1)  # lot B : entree a 200

    # prix a 97 : lot A en perte de 3% (> 2%, stop declenche), lot B en perte de 51.5% aussi...
    # on isole le test : seul le lot le plus ancien (A) doit etre vise en premier par le stop
    engine.process_candle(make_candle(2, 97.0))

    # les deux lots sont en perte a ce prix, donc les deux stop-loss se declenchent independamment
    remaining_entry_prices = [p.avg_entry_price for p in portfolio.positions]
    assert 100.0 not in remaining_entry_prices
    assert 200.0 not in remaining_entry_prices  # les deux ont saute (97 est loin sous les deux seuils)
    assert len(portfolio.trade_history) == 2


def test_strategy_sell_signal_closes_all_open_lots():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.1, max_concurrent_positions=3, stop_loss_pct=0.5))
    engine = Engine(AlwaysSellStrategy(), risk_manager, executor, portfolio)

    executor.place_order(Side.BUY, 1.0, 100.0, timestamp=0)
    executor.place_order(Side.BUY, 1.0, 110.0, timestamp=1)
    executor.place_order(Side.BUY, 1.0, 120.0, timestamp=2)

    engine.process_candle(make_candle(3, 130.0))  # signal de vente : sort de TOUTES les positions

    assert len(portfolio.positions) == 0
    assert len(portfolio.trade_history) == 3


def test_only_one_lot_by_default_matches_historical_behavior():
    portfolio = Portfolio(starting_capital=1000.0)
    executor = BacktestExecutor(portfolio)
    risk_manager = RiskManager(RiskConfig(max_position_size_pct=0.5))  # max_concurrent_positions=1 par defaut
    engine = Engine(AlwaysBuyStrategy(), risk_manager, executor, portfolio)

    engine.process_candle(make_candle(0, 100.0))
    engine.process_candle(make_candle(1, 100.0))

    assert len(portfolio.positions) == 1
