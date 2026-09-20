"""Tests du diagnostic IBKR (EF-72) - client IB toujours factice : aucun test
ne peut atteindre une vraie session, reelle ou paper."""
import pytest

from tradingbot.diagnose_ibkr import diagnose, format_diagnosis


class FakeContract:
    def __init__(self, symbol, exchange="SMART", currency="EUR"):
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.primaryExchange = ""
        self.conId = None


class FakeBar:
    def __init__(self, close, date="2026-09-17"):
        self.close = close
        self.date = date


class FakeIB:
    def __init__(self, accounts=("DU1234567",), unknown_symbols=(), no_data_symbols=(),
                 qualify_raises=False):
        self._accounts = list(accounts)
        self.unknown = set(unknown_symbols)
        self.no_data = set(no_data_symbols)
        self.qualify_raises = qualify_raises
        self.disconnected = False

    def managedAccounts(self):
        return list(self._accounts)

    def qualifyContracts(self, *contracts):
        if self.qualify_raises:
            raise RuntimeError("pas de connexion aux donnees de contrat")
        out = []
        for c in contracts:
            if c.symbol in self.unknown:
                continue  # IBKR ne renvoie rien pour un contrat introuvable
            c.conId = 1000 + len(c.symbol)
            c.primaryExchange = getattr(c, "primaryExchange", "") or "SBF"
            out.append(c)
        return out

    def reqHistoricalData(self, contract, **kwargs):
        if contract.symbol in self.no_data:
            return []
        return [FakeBar(100.0 + i) for i in range(5)]

    def disconnect(self):
        self.disconnected = True


def run(ib=None, port=4002, symbols=("TTE.PA",)):
    return diagnose("127.0.0.1", port, 99, list(symbols), ib=ib or FakeIB())


def find(diagnosis, prefix):
    return next(c for c in diagnosis.checks if c.name.startswith(prefix))


# --- le port ---


@pytest.mark.parametrize("port,platform", [(7496, "TWS"), (4001, "IB Gateway")])
def test_a_live_port_blocks_immediately(port, platform):
    """Meme garde-fou que dans les executeurs : les ports du compte reel ne
    doivent jamais etre atteints, meme par un simple diagnostic."""
    diagnosis = run(port=port)

    assert diagnosis.blocked is True
    assert "REEL" in find(diagnosis, "Port").detail
    assert len(diagnosis.checks) == 1, "on s'arrete avant meme de se connecter"


@pytest.mark.parametrize("port", [7497, 4002])
def test_a_paper_port_is_accepted(port):
    diagnosis = run(port=port)

    assert diagnosis.blocked is False
    assert find(diagnosis, "Port").ok is True
    assert "paper" in find(diagnosis, "Port").detail


def test_an_unknown_port_passes_with_a_warning():
    diagnosis = run(port=5555)

    assert diagnosis.blocked is False
    assert "personnalise" in find(diagnosis, "Port").detail


# --- le compte ---


def test_a_paper_account_is_recognised():
    diagnosis = run(FakeIB(accounts=("DU9876543",)))

    assert find(diagnosis, "Comptes").ok is True
    assert "DU9876543" in find(diagnosis, "Comptes").detail


def test_a_live_account_blocks_everything():
    """LE garde-fou qui compte : se connecter par erreur a une session reelle
    doit tout arreter, pas seulement avertir."""
    diagnosis = run(FakeIB(accounts=("U1234567",)))

    assert diagnosis.blocked is True
    assert "NON-paper" in find(diagnosis, "Comptes").detail
    assert not any(c.name.startswith("Ticker") for c in diagnosis.checks), (
        "aucun ticker ne doit etre teste sur une session reelle"
    )


def test_a_mixed_account_list_also_blocks():
    diagnosis = run(FakeIB(accounts=("DU111", "U222")))

    assert diagnosis.blocked is True


def test_no_account_at_all_is_reported():
    diagnosis = run(FakeIB(accounts=()))

    assert find(diagnosis, "Comptes").ok is False


# --- les tickers ---


def test_a_qualified_ticker_reports_what_ibkr_returned():
    """On affiche ce qu'IBKR a REELLEMENT retenu : c'est la seule facon de
    corriger la table de traduction sur des faits plutot que des suppositions."""
    diagnosis = run(symbols=("TTE.PA",))

    check = find(diagnosis, "Ticker TTE.PA")
    assert check.ok is True
    assert "TTE / SBF / EUR" in check.detail
    assert "conId" in check.detail


def test_an_unknown_ticker_points_at_the_translation_table():
    diagnosis = run(FakeIB(unknown_symbols={"XXX"}), symbols=("XXX.PA",))

    check = find(diagnosis, "Ticker XXX.PA")
    assert check.ok is False
    assert "YAHOO_SUFFIX_TO_IB_EXCHANGE" in check.detail


def test_a_failed_ticker_does_not_stop_the_others():
    diagnosis = run(FakeIB(unknown_symbols={"XXX"}), symbols=("XXX.PA", "TTE.PA"))

    assert find(diagnosis, "Ticker XXX.PA").ok is False
    assert find(diagnosis, "Ticker TTE.PA").ok is True
    assert diagnosis.blocked is False, "un ticker inconnu n'est pas un blocage global"


def test_an_error_while_qualifying_is_reported_not_raised():
    diagnosis = run(FakeIB(qualify_raises=True), symbols=("TTE.PA",))

    assert find(diagnosis, "Ticker TTE.PA").ok is False
    assert "erreur" in find(diagnosis, "Ticker TTE.PA").detail


# --- les donnees de marche ---


def test_market_data_is_reported_per_symbol():
    diagnosis = run(symbols=("TTE.PA",))

    check = find(diagnosis, "Donnees TTE.PA")
    assert check.ok is True
    assert "5 bougies" in check.detail


def test_missing_market_data_mentions_the_subscription():
    """Un compte paper herite des abonnements du compte reel : sans
    abonnement, pas de donnees - il faut que le message le dise."""
    diagnosis = run(FakeIB(no_data_symbols={"TTE"}), symbols=("TTE.PA",))

    check = find(diagnosis, "Donnees TTE.PA")
    assert check.ok is False
    assert "abonnement" in check.detail


def test_data_is_only_requested_for_qualified_symbols():
    diagnosis = run(FakeIB(unknown_symbols={"XXX"}), symbols=("XXX.PA",))

    assert not any(c.name.startswith("Donnees") for c in diagnosis.checks)


# --- le rapport ---


def test_the_report_always_warns_about_read_only_mode():
    """Le mode lecture seule est actif par defaut et indetectable ici : le
    diagnostic peut etre tout vert alors qu'aucun ordre ne passera. Le
    rappel doit donc apparaitre meme quand tout va bien."""
    report = format_diagnosis(run())

    assert "Read-Only API" in report
    assert "Tout est vert" in report


def test_the_report_marks_a_blocked_diagnosis():
    report = format_diagnosis(run(port=7496))

    assert "BLOQUE" in report


def test_the_report_counts_partial_failures():
    report = format_diagnosis(run(FakeIB(unknown_symbols={"XXX"}), symbols=("XXX.PA", "TTE.PA")))

    assert "en echec" in report
