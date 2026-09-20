"""Tests du mode de validation (EF-70) - aucun appel reseau : les bougies
sont fournies, la base SQLite est construite dans un repertoire temporaire."""
import sqlite3

from tradingbot.types import Candle
from tradingbot.validate_paper import (
    ExpectedSignal,
    RealOrder,
    pair_orders_with_signals,
    read_orders,
    validate,
)

HOUR = 3_600_000
T0 = 1_700_000_000_000


def make_db(tmp_path, orders=(), equity=()):
    path = tmp_path / "bot.db"
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE orders (id INTEGER PRIMARY KEY, timestamp INTEGER, side TEXT,
            quantity REAL, price REAL, mode TEXT, status TEXT);
        CREATE TABLE equity_curve (id INTEGER PRIMARY KEY, timestamp INTEGER, equity REAL);
        """
    )
    c.executemany("INSERT INTO orders (timestamp, side, quantity, price, mode, status) VALUES (?,?,?,?,?,?)",
                  [(t, s, q, p, "paper", st) for t, s, q, p, st in orders])
    c.executemany("INSERT INTO equity_curve (timestamp, equity) VALUES (?,?)", list(equity))
    c.commit()
    c.close()
    return path


def candles(closes, start=T0):
    return [Candle(timestamp=start + i * HOUR, open=c, high=c, low=c, close=c, volume=1.0)
            for i, c in enumerate(closes)]


CONFIG = {
    "name": "bot", "symbol": "ETH/USDT", "exchange": "binance", "timeframe": "1h",
    "warmup_candles": 0,
    "strategy": {"type": "trend_regime", "ema_period": 5, "entry_buffer_pct": 0.0,
                 "exit_buffer_pct": 0.0},
}


# --- lecture des ordres ---


def test_only_executed_orders_are_read(tmp_path):
    """Un ordre rejete n'a pas modifie le portefeuille : le compter comme une
    divergence serait un faux positif."""
    db = make_db(tmp_path, orders=[
        (T0, "buy", 1.0, 100.0, "filled"),
        (T0 + HOUR, "buy", 1.0, 100.0, "rejected"),
    ])
    assert [o.status for o in read_orders(db)] == ["filled"]


def test_a_missing_database_reads_as_no_orders(tmp_path):
    assert read_orders(tmp_path / "absent.db") == []


# --- appariement ---


def test_repeated_signals_count_as_one_honoured_order():
    """`trend_regime` reemet BUY a chaque bougie tant que le regime est
    haussier (anti-doublon delegue au RiskManager). Sans regle, on compterait
    des dizaines de faux "signaux manques" pour un seul achat legitime."""
    orders = [RealOrder(T0, "buy", 1.0, 100.0, "filled")]
    signals = [ExpectedSignal(T0 + i * HOUR, "buy", 100.0) for i in range(5)]

    matches, missed, unexpected = pair_orders_with_signals(orders, signals, HOUR)

    assert len(matches) == 1
    assert missed == [], f"aucun signal manque attendu, obtenu {len(missed)}"
    assert unexpected == []


def test_a_signal_with_no_order_is_reported_as_missed():
    """Le defaut le plus grave et le plus silencieux : le bot semble en bonne
    sante mais n'a pas agi."""
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, missed, unexpected = pair_orders_with_signals([], signals, HOUR)

    assert matches == []
    assert len(missed) == 1
    assert unexpected == []


def test_an_order_with_no_signal_is_reported_as_unexpected():
    orders = [RealOrder(T0, "buy", 1.0, 100.0, "filled")]

    matches, missed, unexpected = pair_orders_with_signals(orders, [], HOUR)

    assert matches == []
    assert len(unexpected) == 1


def test_an_order_of_the_opposite_side_is_never_matched():
    orders = [RealOrder(T0, "sell", 1.0, 100.0, "filled")]
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, missed, unexpected = pair_orders_with_signals(orders, signals, HOUR)

    assert matches == []
    assert len(unexpected) == 1
    assert len(missed) == 1


def test_an_order_outside_the_tolerance_is_not_matched():
    orders = [RealOrder(T0 + 5 * HOUR, "buy", 1.0, 100.0, "filled")]
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, missed, unexpected = pair_orders_with_signals(orders, signals, HOUR)

    assert matches == []
    assert len(unexpected) == 1


# --- glissement de prix ---


def test_paying_more_on_a_buy_is_a_negative_slippage():
    """Convention : un chiffre negatif signifie TOUJOURS que le reel a coute."""
    orders = [RealOrder(T0, "buy", 1.0, 101.0, "filled")]
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, _, _ = pair_orders_with_signals(orders, signals, HOUR)

    assert matches[0].slippage_pct == -1.0


def test_receiving_less_on_a_sell_is_also_a_negative_slippage():
    orders = [RealOrder(T0, "sell", 1.0, 99.0, "filled")]
    signals = [ExpectedSignal(T0, "sell", 100.0)]

    matches, _, _ = pair_orders_with_signals(orders, signals, HOUR)

    assert matches[0].slippage_pct == -1.0


def test_a_favourable_fill_is_a_positive_slippage():
    orders = [RealOrder(T0, "buy", 1.0, 99.0, "filled")]
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, _, _ = pair_orders_with_signals(orders, signals, HOUR)

    assert matches[0].slippage_pct == 1.0


def test_execution_lag_is_measured():
    orders = [RealOrder(T0 + 1_800_000, "buy", 1.0, 100.0, "filled")]  # +30 min
    signals = [ExpectedSignal(T0, "buy", 100.0)]

    matches, _, _ = pair_orders_with_signals(orders, signals, HOUR)

    assert matches[0].lag_ms == 1_800_000


# --- bout en bout ---


def test_repeated_sell_signals_with_no_position_are_not_missed(tmp_path):
    """Defaut REEL trouve en ecrivant ce test : `trend_regime` reemet SELL a
    chaque bougie baissiere et le bot les ignore a juste titre quand il n'a
    rien a vendre. Sans filtre sur les signaux actionnables, l'outil
    rapportait des centaines de faux "signaux manques"."""
    db = make_db(tmp_path, orders=[], equity=[(T0 + i * HOUR, 200.0) for i in range(8)])
    # Prix a plat : avec exit_buffer=0, la strategie emet SELL en continu.
    flat = candles([100.0] * 8)

    report = validate(CONFIG, db, candles=flat)

    assert report.orders == []
    assert all(s.side != "sell" for s in report.missed_signals), (
        "une vente sans position a vendre n'est pas un signal manque"
    )


def test_a_bot_legitimately_in_cash_is_not_flagged(tmp_path):
    """Comportement NORMAL des bots deployes (marge d'entree a 3 %) : le
    cours reste dans la zone neutre, rien ne doit etre signale."""
    config = {**CONFIG, "strategy": {**CONFIG["strategy"],
                                     "entry_buffer_pct": 0.03, "exit_buffer_pct": 0.03}}
    db = make_db(tmp_path, orders=[], equity=[(T0 + i * HOUR, 200.0) for i in range(8)])
    flat = candles([100.0] * 8)

    report = validate(config, db, candles=flat)

    assert report.signals == [], "la zone neutre ne doit produire aucun signal"
    assert report.missed_signals == []
    assert report.unexpected_orders == []


DEPLOYED = {**CONFIG, "strategy": {**CONFIG["strategy"],
                                   "entry_buffer_pct": 0.03, "exit_buffer_pct": 0.03}}


def test_end_to_end_detects_slippage_on_a_real_order(tmp_path):
    """Config des bots deployes : a plat rien ne se passe, et le saut de 20 %
    declenche l'achat sur SA bougie - c'est sa cloture qui sert de reference."""
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 120.0, 121.0]
    series = candles(prices)
    buy_ts = series[5].timestamp
    db = make_db(
        tmp_path,
        orders=[(buy_ts, "buy", 1.0, 120.6, "filled")],  # paye 0,5 % plus cher
        equity=[(c.timestamp, 200.0) for c in series],
    )

    report = validate(DEPLOYED, db, candles=series)

    assert len(report.matches) == 1, f"apparie {len(report.matches)}, manques {len(report.missed_signals)}"
    assert report.matches[0].signal.reference_price == 120.0
    assert report.mean_slippage_pct < 0
    assert abs(report.mean_slippage_pct - (-0.5)) < 0.01


def test_end_to_end_flags_a_missed_signal(tmp_path):
    """Le bot aurait du acheter et n'a rien fait : c'est ce que l'outil
    existe pour attraper."""
    prices = [100.0, 100.0, 100.0, 100.0, 100.0, 120.0, 121.0]
    series = candles(prices)
    db = make_db(tmp_path, orders=[], equity=[(c.timestamp, 200.0) for c in series])

    report = validate(DEPLOYED, db, candles=series)

    assert report.signals, "la strategie devait produire au moins un signal"
    assert report.missed_signals, "un signal sans ordre doit etre signale"


def test_report_on_a_bot_with_no_data_at_all(tmp_path):
    from tradingbot.validate_paper import format_report

    report = validate(CONFIG, tmp_path / "jamais_lance.db", candles=candles([100.0] * 3))

    assert report.period is None
    assert "n'a encore rien enregistre" in format_report(report)
