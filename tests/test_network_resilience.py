"""EF-85 - le 2026-09-25 a 02h09, une seule coupure reseau ("connexion fermee
par l'hote distant", ccxt.NetworkError sur fetch_ticker) a tue le bot ETH,
reste six heures a l'arret avec une position ouverte. La boucle rattrape
desormais les erreurs de reseau PASSAGERES a la lecture des donnees ; toute
autre erreur doit continuer a arreter le bot."""
import ccxt
import pytest
import requests

from tradingbot.run_paper import is_transient_network_error


def test_the_exact_error_of_the_crash_is_transient():
    error = ccxt.NetworkError("binance GET https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT")
    assert is_transient_network_error(error)


@pytest.mark.parametrize("error", [
    ccxt.RequestTimeout("delai"),
    ccxt.ExchangeNotAvailable("maintenance"),
    ccxt.DDoSProtection("trop de requetes"),
    requests.exceptions.ConnectionError("reset"),
    requests.exceptions.Timeout("delai"),
    ConnectionResetError(10054, "fermee par l'hote distant"),
    TimeoutError(),
])
def test_network_failures_are_retried(error):
    assert is_transient_network_error(error)


@pytest.mark.parametrize("error", [
    ccxt.AuthenticationError("cle invalide"),
    ccxt.BadSymbol("paire inconnue"),
    ccxt.InsufficientFunds("solde"),
    ValueError("bug de logique"),
    KeyError("last"),
])
def test_other_errors_still_stop_the_bot(error):
    """Reessayer sans fin une cle invalide ou un bug masquerait le probleme :
    ces erreurs doivent continuer a arreter le bot."""
    assert not is_transient_network_error(error)
