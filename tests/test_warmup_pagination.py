"""Regression : le rechauffement au-dela de 1000 bougies etait tronque en
silence (EF-70).

Binance plafonne a 1000 bougies par requete - verifie empiriquement :
demander 2001 en renvoie 1000. L'ancienne version faisait une requete unique,
donc toute config avec `warmup_candles` > 999 demarrait avec une strategie
sous-rechauffee, sans erreur ni avertissement.
"""
from tradingbot.run_paper import EXCHANGE_OHLCV_PAGE_LIMIT, _fetch_ohlcv_paginated

HOUR_MS = 3_600_000
NOW = 1_700_000_000_000


class CappedExchange:
    """Exchange factice qui se comporte comme Binance : jamais plus de
    `cap` bougies par requete, quoi qu'on demande."""

    def __init__(self, available=5000, cap=EXCHANGE_OHLCV_PAGE_LIMIT):
        self.cap = cap
        # Historique continu se terminant a NOW.
        self.history = [
            [NOW - (available - i) * HOUR_MS, 1.0, 1.0, 1.0, 100.0 + i, 1.0]
            for i in range(available)
        ]
        self.calls = []

    def milliseconds(self):
        return NOW

    def parse_timeframe(self, timeframe):
        return 3600

    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        self.calls.append({"since": since, "limit": limit})
        rows = self.history if since is None else [r for r in self.history if r[0] >= since]
        if since is None:
            rows = rows[-(limit or len(rows)):]
        return rows[: min(limit or self.cap, self.cap)]


def test_a_small_warmup_still_uses_a_single_request():
    """Les bots existants (100 a 500 bougies) ne doivent PAS changer de
    comportement : meme chemin a une seule requete qu'avant."""
    exchange = CappedExchange()

    rows = _fetch_ohlcv_paginated(exchange, "ETH/USDT", "1h", 501)

    assert len(exchange.calls) == 1
    assert exchange.calls[0]["since"] is None
    assert len(rows) == 501


def test_a_large_warmup_is_no_longer_truncated():
    """Le coeur de la regression : 2001 bougies demandees doivent bien
    arriver, via plusieurs requetes."""
    exchange = CappedExchange()

    rows = _fetch_ohlcv_paginated(exchange, "ETH/USDT", "1h", 2001)

    assert len(rows) == 2001, f"tronque a {len(rows)} bougies"
    assert len(exchange.calls) >= 3, "plusieurs requetes etaient necessaires"


def test_the_returned_candles_are_the_most_recent_ones():
    exchange = CappedExchange()

    rows = _fetch_ohlcv_paginated(exchange, "ETH/USDT", "1h", 2001)

    assert rows[-1][0] == exchange.history[-1][0], "la derniere bougie doit etre la plus recente"
    assert rows == sorted(rows, key=lambda r: r[0]), "les bougies doivent rester ordonnees"
    assert len({r[0] for r in rows}) == len(rows), "aucun doublon"


def test_it_stops_when_the_exchange_has_no_more_history():
    """Un actif plus jeune que le rechauffement demande ne doit pas faire
    boucler indefiniment - on prend ce qui existe."""
    exchange = CappedExchange(available=1500)

    rows = _fetch_ohlcv_paginated(exchange, "ETH/USDT", "1h", 4000)

    assert len(rows) == 1500
    assert len(exchange.calls) < 20, "pas de boucle infinie"


def test_the_old_behaviour_would_have_truncated():
    """Documente le bug : une requete unique, meme en demandant 2001,
    n'aurait ramene que 1000 bougies."""
    exchange = CappedExchange()

    single = exchange.fetch_ohlcv("ETH/USDT", timeframe="1h", limit=2001)

    assert len(single) == EXCHANGE_OHLCV_PAGE_LIMIT
