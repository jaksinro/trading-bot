"""EF-83 - trois bots `trend_regime` en regime haussier franc n'ont passe AUCUN
ordre pendant six jours. Cause : ils se rechauffaient sur le TESTNET Binance,
qui ne conserve que ~14 jours de bougies (339 en 1h). La strategie recevait
338 bougies au lieu de 500/1000/2000, n'atteignait jamais sa maturite, et
restait muette ; le PC redemarrant chaque jour, le compteur repartait de zero.

Aucun test ne pouvait le voir : tous les echanges factices renvoyaient
exactement ce qu'on leur demandait."""
import ccxt

from tradingbot.run_paper import _fetch_ohlcv_paginated, build_market_data_exchange, warm_up_strategy
from tradingbot.strategies.trend_regime import TrendRegimeStrategy
from tradingbot.types import Side

HOUR = 3_600_000


class ShortHistoryExchange:
    """Imite le testnet : ne renvoie jamais plus de `depth` bougies, quelle
    que soit la demande - c'est la propriete qui a mis les bots en panne."""

    def __init__(self, depth: int, price_fn=lambda i: 100.0 + i):
        self.depth = depth
        self.price_fn = price_fn
        self.now = 1_790_000_000_000

    def milliseconds(self):
        return self.now

    def parse_timeframe(self, tf):
        return 3600

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=500):
        start = self.now - self.depth * HOUR
        rows = [[start + i * HOUR, self.price_fn(i), self.price_fn(i), self.price_fn(i), self.price_fn(i), 1.0]
                for i in range(self.depth)]
        if since is not None:
            rows = [r for r in rows if r[0] >= since]
        return rows[:limit]


def test_a_short_history_leaves_the_strategy_immature():
    """Le mecanisme exact de la panne, fige : 339 bougies disponibles pour un
    besoin de 500 -> strategie muette malgre une hausse franche."""
    exchange = ShortHistoryExchange(depth=339)
    strategy = TrendRegimeStrategy(ema_period=500, entry_buffer_pct=0.03)

    warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, 500)

    assert strategy._seen < strategy.warmup_candles
    rows = exchange.fetch_ohlcv("ETH/USDT", "1h")
    from tradingbot.run_paper import _row_to_candle
    assert strategy.on_candle(_row_to_candle(rows[-1])) is None, "muette tant qu'immature"


def test_a_deep_enough_history_lets_the_strategy_buy_in_an_uptrend():
    exchange = ShortHistoryExchange(depth=3000)
    strategy = TrendRegimeStrategy(ema_period=500, entry_buffer_pct=0.03)

    warm_up_strategy(exchange, "ETH/USDT", "1h", strategy, 500)

    assert strategy._seen >= strategy.warmup_candles
    from tradingbot.types import Candle
    signal = strategy.on_candle(Candle(timestamp=exchange.now, open=5000, high=5000, low=5000, close=5000, volume=1))
    assert signal is not None and signal.side == Side.BUY


def test_market_data_comes_from_the_public_exchange_not_the_testnet():
    """Les ordres restent sur le testnet, mais les DONNEES viennent du marche
    public, qui a tout l'historique."""
    testnet = object()
    client = build_market_data_exchange("binance", fallback=testnet)

    assert client is not testnet
    assert isinstance(client, ccxt.binance)
    assert not client.apiKey, "client de donnees sans cle : incapable de passer un ordre"
    assert "testnet" not in str(client.urls.get("api", "")).lower()


def test_market_data_falls_back_rather_than_preventing_start():
    fallback = object()
    assert build_market_data_exchange("echange_qui_n_existe_pas", fallback=fallback) is fallback


def test_paginated_fetch_reports_what_it_really_got():
    """Le decompte reel doit etre visible : l'ancien message annoncait le
    nombre DEMANDE ("500 bougies") pendant que la strategie en avait 338."""
    rows = _fetch_ohlcv_paginated(ShortHistoryExchange(depth=339), "ETH/USDT", "1h", 2001)
    assert len(rows) == 339
