"""Le dashboard s'ouvre souvent comme FICHIER local (file:///.../dashboard.html :
c'est ainsi que les bots l'ouvrent au demarrage). Un lien commencant par "/"
y designe alors la racine du disque (file:///C:/trading.html) - constate le
2026-09-26 avec le lien vers l'Espace Trading. Tout lien vers le serveur doit
passer par CONTROL_SERVER, qui retombe sur http://localhost:8765 hors serveur."""
import re

from tradingbot.reporting.dashboard import _MASTER_DASHBOARD_HTML


def test_no_root_relative_link_in_the_dashboard():
    root_relative = re.findall(r'href="/[^/"][^"]*"', _MASTER_DASHBOARD_HTML)
    assert root_relative == [], f"liens casses en ouverture locale : {root_relative}"


def test_the_trading_page_link_goes_through_the_server():
    assert "${CONTROL_SERVER}/trading.html" in _MASTER_DASHBOARD_HTML
