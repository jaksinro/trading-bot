"""Strategie de scalping (gains rapides et faibles - PO-2 etendu).

Contrairement au SMA cross qui vise des tendances larges, cette strategie
cherche des petits creux de prix (dip) par rapport a une moyenne courte et
achete dessus. La sortie ne se fait volontairement PAS ici : elle est geree
par le RiskManager via take_profit_pct/stop_loss_pct (une prise de gain de
quelques dixiemes de %, typique du scalping "au centime pres").
"""

from collections import deque

from tradingbot.strategies.base import Strategy
from tradingbot.types import Candle, Side, Signal


class ScalpDipStrategy(Strategy):
    def __init__(self, lookback: int = 20, dip_threshold_pct: float = 0.003):
        if lookback < 2:
            raise ValueError("lookback doit etre >= 2")
        self.lookback = lookback
        self.dip_threshold_pct = dip_threshold_pct
        self._closes: deque[float] = deque(maxlen=lookback)

    def on_candle(self, candle: Candle) -> Signal | None:
        self._closes.append(candle.close)
        if len(self._closes) < self.lookback:
            return None

        reference_sma = sum(self._closes) / len(self._closes)
        drop_pct = (reference_sma - candle.close) / reference_sma

        if drop_pct >= self.dip_threshold_pct:
            return Signal(side=Side.BUY, reason=f"dip_{drop_pct:.4f}")
        return None
