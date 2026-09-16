"""Calcul des metriques de performance (STC section 3.2, EF-07 de la STB)."""

from dataclasses import dataclass

from tradingbot.portfolio import Portfolio
from tradingbot.risk.risk_manager import RiskConfig
from tradingbot.types import Candle


@dataclass
class PerformanceReport:
    starting_capital: float
    ending_equity: float
    total_return_pct: float
    max_drawdown_pct: float
    realized_pnl: float


def compute_report(portfolio: Portfolio) -> PerformanceReport:
    equity_values = [equity for _, equity in portfolio.equity_curve]
    ending_equity = equity_values[-1] if equity_values else portfolio.starting_capital

    peak = float("-inf")
    max_drawdown_pct = 0.0
    for equity in equity_values:
        peak = max(peak, equity)
        if peak > 0:
            drawdown_pct = (peak - equity) / peak
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

    total_return_pct = (
        (ending_equity - portfolio.starting_capital) / portfolio.starting_capital
        if portfolio.starting_capital
        else 0.0
    )

    return PerformanceReport(
        starting_capital=portfolio.starting_capital,
        ending_equity=ending_equity,
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        realized_pnl=portfolio.realized_pnl,
    )


def compute_buy_and_hold_return_pct(candles: list[Candle]) -> float | None:
    """Rendement qu'aurait donne un simple achat au debut de la periode,
    conserve sans y toucher jusqu'a la fin - la reference minimale qu'une
    strategie active doit battre pour avoir un edge reel (etape 6 de la
    feuille de route performance : sans ce point de comparaison, un bon
    rendement peut n'etre que le marche qui monte, pas la strategie qui
    fonctionne). None si l'intervalle est trop court pour etre mesure."""
    if len(candles) < 2:
        return None
    first_price = candles[0].close
    if first_price == 0:
        return None
    return (candles[-1].close - first_price) / first_price


def _target_prices(entry_price: float, risk_config: RiskConfig) -> tuple[float | None, float | None]:
    take_profit = entry_price * (1 + risk_config.take_profit_pct) if risk_config.take_profit_pct else None
    stop_loss = entry_price * (1 - risk_config.stop_loss_pct) if risk_config.stop_loss_pct is not None else None
    return take_profit, stop_loss


def build_orders_table(portfolio: Portfolio, risk_config: RiskConfig) -> list[dict]:
    """Liste des ordres pour le dashboard (STC ext.) : chaque position
    achetee, ouverte ou deja revendue, avec le prix reel d'achat, le prix de
    vente cible calcule a partir de la config de risque (take-profit /
    stop-loss), et - si elle est fermee - le prix de vente reel et la
    raison (stop_loss, take_profit, ou le signal de la strategie)."""
    rows = []
    for trade in portfolio.trade_history:
        take_profit, stop_loss = _target_prices(trade["entry_price"], risk_config)
        rows.append({
            "status": "vendu",
            "buy_price": trade["entry_price"],
            "quantity": trade["quantity"],
            "target_take_profit": take_profit,
            "target_stop_loss": stop_loss,
            "sell_price": trade["exit_price"],
            "reason": trade["reason"] or "signal",
            "pnl": trade["pnl"],
            "entry_timestamp": trade["entry_timestamp"],
            "exit_timestamp": trade["timestamp"],
            "lot_id": trade.get("lot_id"),
        })

    for position in portfolio.positions:
        take_profit, stop_loss = _target_prices(position.avg_entry_price, risk_config)
        rows.append({
            "status": "ouvert",
            "buy_price": position.avg_entry_price,
            "quantity": position.quantity,
            "target_take_profit": take_profit,
            "target_stop_loss": stop_loss,
            "sell_price": None,
            "reason": "",
            "pnl": None,
            "entry_timestamp": position.entry_timestamp,
            "exit_timestamp": None,
            "lot_id": position.lot_id,
        })

    rows.sort(key=lambda r: r["entry_timestamp"], reverse=True)
    return rows
