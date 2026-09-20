"""Tests du scanner multi-actions (EF-66) - donnees synthetiques uniquement,
aucun appel reseau (comme toutes les suites existantes)."""
from collections import deque

import tradingbot.multi_symbol_scanner as scanner_module
from tradingbot.multi_symbol_scanner import (
    ScannerResult,
    run_multi_symbol_backtest,
    scan_and_rank,
)
from tradingbot.strategies.dip_bounce import DipBounceStrategy
from tradingbot.types import Candle, Side


def make_candle(day_offset: int, close: float, symbol_hour: int = 0) -> Candle:
    # espace les bougies d'un jour (86_400_000 ms), toutes a minuit UTC pour simplifier _day_key.
    ts = day_offset * 86_400_000
    return Candle(timestamp=ts, open=close, high=close, low=close, close=close, volume=1.0)


def test_scan_and_rank_orders_by_deepest_dip_first():
    strategies = {
        "A": DipBounceStrategy(trend_ma_period=3, dip_threshold_pct=0.5),
        "B": DipBounceStrategy(trend_ma_period=3, dip_threshold_pct=0.5),
    }
    windows = {"A": deque(maxlen=3), "B": deque(maxlen=3)}
    # rechauffe les 2 strategies identiquement (2 bougies stables), la 3e bougie declenche le signal.
    for day, (close_a, close_b) in enumerate([(100, 100), (100, 100)]):
        scan_and_rank({"A": make_candle(day, close_a), "B": make_candle(day, close_b)}, strategies, windows, set())

    # A chute plus fort (creux plus profond) que B, les 2 declenchent un signal.
    ranked = scan_and_rank(
        {"A": make_candle(2, 50.0), "B": make_candle(2, 90.0)}, strategies, windows, set(),
    )
    assert [symbol for symbol, _ in ranked] == ["A", "B"]


def test_scan_and_rank_skips_held_symbols():
    strategies = {"A": DipBounceStrategy(trend_ma_period=2, dip_threshold_pct=0.5)}
    windows = {"A": deque(maxlen=2)}
    scan_and_rank({"A": make_candle(0, 100)}, strategies, windows, set())
    ranked = scan_and_rank({"A": make_candle(1, 50.0)}, strategies, windows, held_symbols={"A"})
    assert ranked == []


def _fake_fetch_historical_candles_factory(candles_by_symbol: dict[str, list[Candle]]):
    def fake(exchange_id, symbol, timeframe, since_iso, **kwargs):
        return candles_by_symbol.get(symbol, [])
    return fake


def test_backtest_buys_the_deepest_dip_when_two_symbols_signal_the_same_day(monkeypatch):
    """Coeur de la demande de l'utilisateur : "la plus forte l'emporte"."""
    # A et B stables puis chutent le meme jour (day=3) - A chute plus fort.
    candles_a = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 60])]
    candles_b = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 90])]
    monkeypatch.setattr(
        scanner_module, "fetch_historical_candles",
        _fake_fetch_historical_candles_factory({"A": candles_a, "B": candles_b}),
    )

    result = run_multi_symbol_backtest(
        universe=["A", "B"], since_iso="2024-01-01T00:00:00Z", capital=1000.0,
        strategy_params={"trend_ma_period": 3, "dip_threshold_pct": 0.5},
        risk_params={
            "max_position_size_pct": 0.5, "stop_loss_pct": None, "max_concurrent_positions": 1,
            "trailing_stop_pct": None, "fee_pct": 0.0, "block_buy_if_any_position_losing": True,
        },
    )

    assert len(result.open_lots) == 1
    assert result.open_lots[0].symbol == "A"  # le creux le plus profond, malgre max_concurrent_positions=1


def test_backtest_respects_max_concurrent_positions(monkeypatch):
    candles_a = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 60])]
    candles_b = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 90])]
    monkeypatch.setattr(
        scanner_module, "fetch_historical_candles",
        _fake_fetch_historical_candles_factory({"A": candles_a, "B": candles_b}),
    )

    result = run_multi_symbol_backtest(
        universe=["A", "B"], since_iso="2024-01-01T00:00:00Z", capital=1000.0,
        strategy_params={"trend_ma_period": 3, "dip_threshold_pct": 0.5},
        risk_params={
            "max_position_size_pct": 0.5, "stop_loss_pct": None, "max_concurrent_positions": 2,
            "trailing_stop_pct": None, "fee_pct": 0.0, "block_buy_if_any_position_losing": False,
        },
    )

    assert len(result.open_lots) == 2  # les 2 signaux acceptes, dans les 2 positions autorisees


def test_stop_loss_on_one_symbol_never_triggered_by_another_symbols_price(monkeypatch):
    """Regression directe contre le risque identifie lors de l'exploration :
    une sortie doit toujours utiliser le prix DU MEME symbole que la
    position, jamais celui d'un autre."""
    # A achete puis reste PARFAITEMENT stable (jamais plus de 10% sous son
    # entree, donc jamais de stop-loss) ; B achete puis CHUTE fort (stop-loss
    # attendu). Si le bug existait (prix d'un symbole applique a un autre),
    # A se ferait sortir a tort par la chute de B.
    candles_a = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 100, 100, 100, 100])]
    candles_b = [make_candle(d, c) for d, c in enumerate([50, 50, 50, 40, 40, 40, 10])]
    monkeypatch.setattr(
        scanner_module, "fetch_historical_candles",
        _fake_fetch_historical_candles_factory({"A": candles_a, "B": candles_b}),
    )

    result = run_multi_symbol_backtest(
        universe=["A", "B"], since_iso="2024-01-01T00:00:00Z", capital=1000.0,
        strategy_params={"trend_ma_period": 3, "dip_threshold_pct": 0.5},
        risk_params={
            "max_position_size_pct": 0.3, "stop_loss_pct": 0.1, "max_concurrent_positions": 2,
            "trailing_stop_pct": None, "fee_pct": 0.0, "block_buy_if_any_position_losing": False,
        },
    )

    # B a chute de 40 a 10 (-75%), largement au-dela du stop-loss de 10% - doit etre cloture
    # (peut se re-racheter le meme jour si le prix reste dans la zone de creux ensuite - pas
    # le sujet teste ici, seul compte qu'au moins une sortie stop_loss a bien eu lieu sur B).
    b_closed = [t for t in result.closed_trades if t.symbol == "B"]
    assert len(b_closed) >= 1
    assert all(t.reason == "stop_loss" for t in b_closed)
    # A n'a jamais chute de plus de 10% depuis son entree a 90 - ne doit JAMAIS avoir ete sorti.
    a_closed = [t for t in result.closed_trades if t.symbol == "A"]
    assert a_closed == []
    assert any(lot.symbol == "A" for lot in result.open_lots)


def test_benchmark_is_computed_per_symbol(monkeypatch):
    candles_a = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 200])]  # +100%
    candles_b = [make_candle(d, c) for d, c in enumerate([100, 100, 100, 50])]  # -50%
    monkeypatch.setattr(
        scanner_module, "fetch_historical_candles",
        _fake_fetch_historical_candles_factory({"A": candles_a, "B": candles_b}),
    )

    result = run_multi_symbol_backtest(
        universe=["A", "B"], since_iso="2024-01-01T00:00:00Z", capital=1000.0,
        strategy_params={"trend_ma_period": 10, "dip_threshold_pct": 0.5},  # fenetre jamais pleine, aucun trade
        risk_params={
            "max_position_size_pct": 0.5, "stop_loss_pct": None, "max_concurrent_positions": 1,
            "trailing_stop_pct": None, "fee_pct": 0.0, "block_buy_if_any_position_losing": False,
        },
    )

    assert result.per_symbol_benchmark_pct["A"] == 100.0
    assert result.per_symbol_benchmark_pct["B"] == -50.0
    assert result.closed_trades == []  # fenetre de tendance jamais remplie (10 > 4 bougies fournies)


# --- Couts reels mesures contre une vraie session IBKR (EF-74) ---


def test_commission_never_falls_below_the_broker_floor():
    """Mesure le 2026-09-18 sur le compte paper reel : la commission IBKR ne
    descend jamais sous 3,00 EUR par ordre sur Euronext Paris. C'est ce
    plancher, et non le pourcentage, qui decide de la viabilite d'une
    strategie a petites positions."""
    from tradingbot.multi_symbol_scanner import order_commission

    assert order_commission(200.0, 0.001) == 3.0, "0,20 EUR modelise vs 3,00 EUR reel"
    assert order_commission(100.0, 0.001) == 3.0
    # Au-dela du plancher, le pourcentage reprend la main.
    assert order_commission(10_000.0, 0.001) == 10.0


def test_the_purchase_tax_applies_to_french_buys_only():
    """La taxe sur les transactions financieres (0,4 % depuis le 2025-04-01)
    frappe l'ACHAT de titres francais. Une vente n'en paie pas, et Amsterdam
    n'est pas concerne : c'est ce qui rend le cout d'un aller-retour
    asymetrique."""
    from tradingbot.multi_symbol_scanner import purchase_tax

    assert purchase_tax("TTE.PA", 1000.0) == 4.0
    assert purchase_tax("MT.AS", 1000.0) == 0.0
    assert purchase_tax("AAPL", 1000.0) == 0.0


def test_a_small_round_trip_costs_more_than_three_percent():
    """Le chiffre qui condamne le scanner a petit capital : sur une position
    de 200 EUR, l'aller-retour coute plus de 3 % AVANT tout mouvement de
    cours - a absorber sur chacun des ~229 trades du backtest."""
    from tradingbot.multi_symbol_scanner import order_commission, purchase_tax

    position = 200.0
    buy = order_commission(position, 0.001) + purchase_tax("TTE.PA", position)
    sell = order_commission(position, 0.001)

    assert (buy + sell) / position > 0.03
