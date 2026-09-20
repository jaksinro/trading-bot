"""Tests des fonctions IBKR ajoutees a run_paper.py (EF-65) - equivalents
`ib_*` des fonctions ccxt existantes (`poll_new_closed_candle`,
`warm_up_strategy`), avec un client `ib_async` factice (meme esprit que
`FakeCandleExchange`/`FakeIB` dans les autres suites de tests)."""
import datetime

import pytest

from tradingbot.run_paper import (
    _derive_ib_client_id,
    ib_fetch_last_price,
    ib_poll_new_closed_candle,
    ib_warm_up_strategy,
)


class FakeBar:
    def __init__(self, date, open_, high, low, close, volume=1000):
        self.date = date
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


class FakeContract:
    symbol = "RNO.PA"


class FakeIB:
    def __init__(self, bars):
        self.bars = bars
        self.calls: list[dict] = []

    def reqHistoricalData(self, contract, endDateTime, durationStr, barSizeSetting, whatToShow, useRTH):
        self.calls.append({"durationStr": durationStr, "barSizeSetting": barSizeSetting})
        return self.bars


def _dated_bars(n, start=datetime.date(2026, 1, 1)):
    return [FakeBar(start + datetime.timedelta(days=i), 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(n)]


def test_ib_poll_new_closed_candle_excludes_the_still_forming_bar():
    """EF-75 - ce test attendait auparavant la DERNIERE bougie (index 2).
    Refute en seance reelle : `reqHistoricalData` inclut bien la bougie du
    JOUR, encore en formation (volume et cloture observes en train de bouger
    entre trois lectures). Rendre cette bougie ferait agir le bot sur une
    cloture incomplete. On renvoie donc l'avant-derniere, seule reellement
    close - meme convention que `ib_warm_up_strategy`, qui avait raison."""
    fake = FakeIB(_dated_bars(3))
    candle = ib_poll_new_closed_candle(fake, FakeContract(), last_seen_ts=None)
    assert candle is not None
    assert candle.close == 101.5  # avant-derniere (index 1), pas 102.5


def test_ib_poll_new_closed_candle_returns_none_when_already_seen():
    bars = _dated_bars(3)
    fake = FakeIB(bars)
    last_ts = int(datetime.datetime.combine(bars[-2].date, datetime.time(tzinfo=datetime.timezone.utc)).timestamp() * 1000)
    candle = ib_poll_new_closed_candle(fake, FakeContract(), last_seen_ts=last_ts)
    assert candle is None


def test_ib_poll_new_closed_candle_returns_none_on_empty_history():
    fake = FakeIB([])
    assert ib_poll_new_closed_candle(fake, FakeContract(), last_seen_ts=None) is None


def test_ib_poll_new_closed_candle_returns_none_on_a_single_forming_bar():
    """Une seule bougie renvoyee = seulement celle du jour, en formation :
    rien de close a traiter, et surtout pas elle."""
    fake = FakeIB(_dated_bars(1))
    assert ib_poll_new_closed_candle(fake, FakeContract(), last_seen_ts=None) is None


def test_ib_warm_up_strategy_feeds_strategy_and_price_history_excluding_last_bar():
    """Meme convention que la version ccxt : la DERNIERE bougie renvoyee est
    exclue (bougie du jour, potentiellement pas encore cloturee au moment du
    demarrage du bot)."""
    fake = FakeIB(_dated_bars(6))
    seen_closes = []

    class DummyStrategy:
        def on_candle(self, candle):
            seen_closes.append(candle.close)

    from collections import deque
    price_history = deque()
    last_ts = ib_warm_up_strategy(fake, FakeContract(), DummyStrategy(), warmup_candles=3, price_history=price_history)

    assert len(seen_closes) == 3  # warmup_candles=3, derniere bougie exclue
    assert len(price_history) == 3
    assert last_ts is not None


def test_ib_warm_up_strategy_raises_on_empty_history():
    """EF-75 - ce test attendait auparavant `None`, c'est-a-dire qu'il
    VERROUILLAIT le defaut comme comportement voulu : un historique vide
    passait sans bruit, et le bot demarrait sur une strategie non rechauffee.
    Constate en branchant une vraie session IBKR, ou le contrat n'etait pas
    qualifie : le rechauffement s'est declare termine sur zero bougie, et
    l'echec n'est apparu que deux etapes plus loin, sur un message sans
    rapport avec la cause. Zero bougie journaliere n'est jamais un demarrage
    normal pour une action - il faut echouer tout de suite, et le dire."""
    fake = FakeIB([])

    class DummyStrategy:
        def on_candle(self, candle):
            pass

    with pytest.raises(ValueError, match="aucune bougie journaliere"):
        ib_warm_up_strategy(fake, FakeContract(), DummyStrategy(), warmup_candles=5)


def test_ib_fetch_last_price_returns_last_bar_close():
    fake = FakeIB(_dated_bars(2))
    assert ib_fetch_last_price(fake, FakeContract()) == 101.5


def test_ib_fetch_last_price_raises_on_empty_history():
    fake = FakeIB([])
    try:
        ib_fetch_last_price(fake, FakeContract())
        assert False, "devrait lever ValueError"
    except ValueError:
        pass


def test_derive_ib_client_id_is_deterministic_and_in_range():
    id_a = _derive_ib_client_id("RNO_SWING_PAPER")
    id_b = _derive_ib_client_id("RNO_SWING_PAPER")
    assert id_a == id_b
    assert 100 <= id_a < 9100


def test_derive_ib_client_id_differs_for_different_names():
    """Pas une garantie absolue (collision mathematiquement possible), mais
    doit distinguer des noms de bots usuels du projet."""
    ids = {_derive_ib_client_id(name) for name in ["RNO_SWING_PAPER", "AF_SWING_PAPER", "TTE_SWING_PAPER"]}
    assert len(ids) == 3
