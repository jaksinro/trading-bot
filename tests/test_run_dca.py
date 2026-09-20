"""Tests du lanceur du bot d'investissement regulier (EF-67) - aucun appel
reseau, aucune connexion TWS : executor et prix factices injectes."""
import sqlite3

import pytest

from tradingbot.execution.ib_multi_symbol_executor import Fill, to_ib_contract_spec
from datetime import datetime, timezone

from tradingbot.run_dca import (
    DcaConfig,
    read_price_history,
    reset_state,
    run_once,
    sell_lines,
    set_monthly_contribution,
)

WEIGHTS = {"TTE.PA": 0.5, "ORA.PA": 0.5}
PRICES = {"TTE.PA": 50.0, "ORA.PA": 10.0}


def make_config(**overrides) -> DcaConfig:
    base = dict(
        name="test_dca", weights=WEIGHTS, monthly_contribution=200.0, rebalance_band_pct=5.0,
        min_order_value=20.0, fee_pct=0.001, fee_fixed=1.25,
        follow_drift_on_contribution=False,
    )
    base.update(overrides)
    return DcaConfig(**base)


class FakeExecutor:
    """Executor factice : remplit tous les ordres au prix de reference, et
    tient ses propres positions pour que la reconciliation soit testable."""

    def __init__(self, prices=None, positions=None, fill_price_offset=0.0, reject=False):
        self.prices = dict(prices or PRICES)
        self._positions = dict(positions or {})
        self.fill_price_offset = fill_price_offset
        self.reject = reject
        self.orders_sent = []

    def latest_prices(self):
        return dict(self.prices)

    def positions(self):
        return dict(self._positions)

    def place_order(self, symbol, side, quantity, reason=""):
        self.orders_sent.append((symbol, side, quantity, reason))
        if self.reject:
            return Fill(symbol, side, 0, 0.0, "rejected", reason)
        price = self.prices[symbol] + self.fill_price_offset
        signed = quantity if side == "buy" else -quantity
        self._positions[symbol] = self._positions.get(symbol, 0.0) + signed
        return Fill(symbol, side, quantity, price, "filled", reason)


def read_table(db_path, table):
    connection = sqlite3.connect(db_path)
    try:
        return connection.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        connection.close()


def test_dry_run_places_no_order_and_writes_nothing(tmp_path):
    """Propriete de surete la plus importante du dry-run : il ne doit RIEN
    consommer - ni le versement du mois, ni l'intervalle de rééquilibrage -
    sinon lancer une simulation empecherait le vrai versement ensuite.

    Verifie ici sur un bot AYANT DEJA TOURNE, donc avec un etat reel a
    preserver ; le cas du bot vierge (ou meme le fichier ne doit pas
    apparaitre) est couvert par le test suivant."""
    db_path = tmp_path / "dca.db"
    # Le MEME executor d'un appel a l'autre : un vrai courtier se souvient de
    # ses positions, et un executor neuf declencherait l'ecart de
    # reconciliation au lieu de tester ce qu'on veut tester ici.
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-02-02")
    before = {
        table: read_table(db_path, table)
        for table in ("contributions", "orders", "holdings", "ledger")
    }
    executor.orders_sent.clear()

    report = run_once(make_config(), db_path, executor=executor, dry_run=True, today="2026-03-02")

    assert report.planned, "le dry-run doit tout de meme montrer ce qu'il ferait"
    assert executor.orders_sent == []
    for table, rows in before.items():
        assert read_table(db_path, table) == rows, f"{table} a ete modifiee par une simulation"


def test_dry_run_does_not_even_create_the_database_file(tmp_path):
    """EF-78 - le dry-run creait le FICHIER de base, vide. Le bot passait
    alors pour "a deja tourne" dans le dashboard, qui cessait d'afficher son
    message de premier demarrage. Simuler ne doit rien laisser derriere,
    pas meme un fichier vide."""
    db_path = tmp_path / "dca.db"

    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=True, today="2026-03-02")

    assert not db_path.exists()


def test_dry_run_on_an_existing_bot_still_reads_its_state(tmp_path):
    """Le repli en memoire ne doit s'appliquer qu'a un bot VIERGE : sur un
    bot qui a deja tourne, la simulation doit voir ses vraies positions."""
    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")

    report = run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=True, today="2026-03-09")

    assert report.holdings_before, "la simulation doit partir des positions reelles"
    assert report.contribution == 0.0, "le versement du mois est deja consomme"



def test_execute_places_orders_and_persists_state(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()

    report = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    assert executor.orders_sent, "des ordres devaient partir"
    assert all(side == "buy" for _, side, _, _ in executor.orders_sent)
    assert len(read_table(db_path, "contributions")) == 1
    assert len(read_table(db_path, "orders")) == len(executor.orders_sent)
    assert read_table(db_path, "holdings"), "les positions doivent etre enregistrees"
    assert report.cash_after < 200.0


def test_running_twice_in_the_same_month_never_contributes_twice(tmp_path):
    """Idempotence : relancer le bot (planificateur declenche deux fois,
    reprise apres plantage, double clic) ne doit jamais verser deux fois -
    un double versement fausserait silencieusement tout le suivi."""
    db_path = tmp_path / "dca.db"
    config = make_config()

    first = run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")
    second = run_once(config, db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-09")

    assert first.contribution == 200.0
    assert second.contribution == 0.0
    assert len(read_table(db_path, "contributions")) == 1


def test_a_new_month_contributes_again(tmp_path):
    db_path = tmp_path / "dca.db"
    # Le MEME executor d'un mois sur l'autre : un vrai courtier se souvient
    # des positions, et le registre local doit rester d'accord avec lui.
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")
    second = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-04-01")

    assert second.contribution == 200.0
    assert len(read_table(db_path, "contributions")) == 2
    assert not any("Ecart" in w for w in second.warnings), (
        "le registre local doit rester reconcilie avec le courtier d'un mois sur l'autre"
    )


def test_position_mismatch_blocks_all_orders_by_default(tmp_path):
    """Le registre local et le courtier doivent concorder avant d'engager
    quoi que ce soit : en cas d'ecart, on prefere ne rien faire et le dire."""
    db_path = tmp_path / "dca.db"
    # Le courtier detient deja quelque chose que le registre local ignore.
    executor = FakeExecutor(positions={"TTE.PA": 7.0})

    report = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    assert executor.orders_sent == []
    assert read_table(db_path, "contributions") == []
    assert any("Ecart entre les positions" in w for w in report.warnings)


def test_position_mismatch_can_be_overridden_explicitly(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor(positions={"TTE.PA": 7.0})

    report = run_once(
        make_config(), db_path, executor=executor, dry_run=False,
        ignore_position_mismatch=True, today="2026-03-02",
    )

    assert executor.orders_sent
    assert any("Ignore sur demande explicite" in w for w in report.warnings)


def test_real_fill_price_is_recorded_not_the_planned_price(tmp_path):
    """Un ordre au marche ne s'execute jamais exactement au dernier cours
    connu : c'est le prix REEL qui doit etre enregistre, sinon le suivi de
    performance derive de la realite."""
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor(fill_price_offset=1.5)

    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    recorded_prices = {row[2]: row[5] for row in read_table(db_path, "orders")}
    for symbol, price in recorded_prices.items():
        assert price == PRICES[symbol] + 1.5


def test_rejected_orders_are_recorded_and_do_not_change_holdings(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor(reject=True)

    report = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    assert read_table(db_path, "holdings") == []
    assert all(row[7] == "rejected" for row in read_table(db_path, "orders"))
    assert any("non execute" in w for w in report.warnings)
    # Le cash n'a pas ete depense, il reste disponible pour le mois suivant.
    assert report.cash_after == pytest.approx(200.0)


def test_missing_prices_are_reported_and_that_line_is_skipped(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor(prices={"TTE.PA": 50.0})  # ORA.PA absent (place fermee)

    report = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    assert any("ORA.PA" in w for w in report.warnings)
    assert all(symbol == "TTE.PA" for symbol, _, _, _ in executor.orders_sent)


def test_executing_without_an_executor_is_refused(tmp_path):
    with pytest.raises(ValueError, match="exige un executor"):
        run_once(make_config(), tmp_path / "dca.db", executor=None, dry_run=False, today="2026-03-02")


def test_config_from_yaml_normalises_weights(tmp_path):
    config_path = tmp_path / "bot.yml"
    config_path.write_text(
        "name: mon_bot\nweights: 'TTE.PA:30,ORA.PA:70'\nmonthly_contribution: 150\n",
        encoding="utf-8",
    )
    config = DcaConfig.from_yaml(config_path)

    assert config.name == "mon_bot"
    assert config.weights == {"TTE.PA": 0.3, "ORA.PA": 0.7}
    assert config.monthly_contribution == 150


def test_config_from_yaml_accepts_a_weight_mapping(tmp_path):
    config_path = tmp_path / "bot.yml"
    config_path.write_text("weights:\n  TTE.PA: 1\n  ORA.PA: 3\n", encoding="utf-8")
    config = DcaConfig.from_yaml(config_path)

    assert config.weights == {"TTE.PA": 0.25, "ORA.PA": 0.75}


def test_yahoo_tickers_are_translated_to_ibkr_contracts():
    """Sans cette traduction, aucun contrat IBKR ne se qualifierait : les
    tickers Yahoo du backtest ne sont pas les symboles IBKR."""
    assert to_ib_contract_spec("TTE.PA") == ("TTE", "SBF", "EUR")
    assert to_ib_contract_spec("MT.AS") == ("MT", "AEB", "EUR")
    assert to_ib_contract_spec("AAPL") == ("AAPL", None, "USD")


def test_a_ticker_whose_ibkr_symbol_differs_is_overridden():
    """Constate contre une vraie session paper (EF-73) : retirer le suffixe
    donne "SAN", qui chez IBKR designe **Banco Santander** et non Sanofi.
    Sanofi sur Euronext Paris est `SAN1`."""
    assert to_ib_contract_spec("SAN.PA") == ("SAN1", "SBF", "EUR")


def test_the_primary_exchange_is_always_forced_for_a_known_suffix():
    """C'est ce forcage qui transforme une confusion d'entreprise en simple
    echec de qualification : sans place principale, "SAN" se qualifierait
    silencieusement sur Banco Santander a Madrid."""
    for ticker in ("SAN.PA", "TTE.PA", "MT.AS", "MC.PA"):
        _, exchange, _ = to_ib_contract_spec(ticker)
        assert exchange, f"{ticker} doit forcer une place principale"


def test_live_port_is_refused():
    """Garde-fou dur : les ports 7496/4001 sont ceux du compte REEL."""
    from tradingbot.execution.ib_multi_symbol_executor import IBMultiSymbolExecutor

    with pytest.raises(ValueError, match="argent reel"):
        IBMultiSymbolExecutor(symbols=["TTE.PA"], port=7496, ib_client=object())


# --- Decouverte des configs et resume d'etat (utilises par le dashboard) ---


def write_dca_config(directory, name, extra=""):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.yml").write_text(
        f"name: {name}\nweights:\n  TTE.PA: 1\n  ORA.PA: 1\n{extra}", encoding="utf-8",
    )


def test_list_dca_configs_reads_its_own_directory(tmp_path):
    from tradingbot.run_dca import list_dca_configs

    write_dca_config(tmp_path, "un")
    write_dca_config(tmp_path, "deux", extra="monthly_contribution: 500\n")
    (tmp_path / "casse.yml").write_text("ceci: n'est pas une config dca\n", encoding="utf-8")

    configs = list_dca_configs(tmp_path)

    assert [c.name for c in configs] == ["deux", "un"]  # tri alphabetique par fichier
    assert next(c for c in configs if c.name == "deux").monthly_contribution == 500


def test_list_dca_configs_on_a_missing_directory_is_empty(tmp_path):
    from tradingbot.run_dca import list_dca_configs

    assert list_dca_configs(tmp_path / "inexistant") == []


def test_dca_configs_are_not_listed_as_regular_bots(tmp_path, monkeypatch):
    """Regression : une config d'investissement regulier posee dans config/
    etait listee comme un bot classique, et la Supervision proposait de la
    lancer via run_paper.py - qui plante (ni `symbol` ni `strategy`)."""
    import tradingbot.control_server as control_server

    (tmp_path / "vrai_bot.yml").write_text(
        "name: vrai_bot\nsymbol: BTC/USDT\ntimeframe: 1h\nstrategy:\n  type: sma_cross\n",
        encoding="utf-8",
    )
    write_dca_config(tmp_path, "bot_investissement")
    monkeypatch.setattr(control_server, "CONFIG_DIR", tmp_path)
    # `list_known_configs` exprime les chemins relativement a ROOT : sans ce
    # patch, un repertoire temporaire hors du projet leve une ValueError.
    monkeypatch.setattr(control_server, "ROOT", tmp_path)
    monkeypatch.setattr(control_server, "is_bot_running", lambda name: False)

    names = [c["name"] for c in control_server.list_known_configs()]

    assert names == ["vrai_bot"]


def test_state_summary_of_a_bot_that_never_ran(tmp_path):
    from tradingbot.run_dca import read_state_summary

    summary = read_state_summary(make_config(), tmp_path / "absent.db")

    assert summary["exists"] is False
    assert summary["total_invested"] == 0.0
    assert summary["value"] == 0.0


def test_state_summary_reports_holdings_allocation_and_fees(tmp_path):
    """Le resume alimente directement le dashboard : il doit refleter les
    versements, la valorisation aux derniers cours connus, et l'ecart entre
    allocation reelle et cible."""
    from tradingbot.run_dca import read_state_summary

    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-04-01")

    summary = read_state_summary(make_config(), db_path)

    assert summary["exists"] is True
    assert summary["total_invested"] == 400.0
    assert summary["contributions"] == 2
    assert summary["orders"] > 0
    assert summary["total_fees"] > 0
    assert summary["prices_as_of"] == "2026-04-01"
    assert summary["value"] > 0
    assert {line["symbol"] for line in summary["lines"]} == set(WEIGHTS)
    assert sum(line["actual_pct"] for line in summary["lines"]) <= 100.0001
    for line in summary["lines"]:
        assert line["target_pct"] == 50.0


def test_state_summary_prices_are_only_written_on_real_runs(tmp_path):
    """Le dry-run ne doit rien persister, y compris les prix."""
    from tradingbot.run_dca import read_state_summary

    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=True, today="2026-03-02")

    summary = read_state_summary(make_config(), db_path)
    assert summary["prices_as_of"] is None
    assert summary["total_invested"] == 0.0


def test_config_round_trips_through_a_dict_like_the_dashboard_form_sends():
    """Le formulaire du dashboard passe par `from_yaml_dict`, comme la
    lecture d'un fichier : une seule validation, donc pas de config acceptee
    par l'interface et refusee au lancement."""
    config = DcaConfig.from_yaml_dict({
        "name": "depuis_le_formulaire",
        "weights": {"TTE.PA": 2, "ORA.PA": 2},
        "monthly_contribution": 250,
        "follow_drift_on_contribution": True,
    })

    assert config.weights == {"TTE.PA": 0.5, "ORA.PA": 0.5}
    assert config.monthly_contribution == 250
    assert config.follow_drift_on_contribution is True


def test_config_without_weights_is_refused():
    with pytest.raises(ValueError, match="weights"):
        DcaConfig.from_yaml_dict({"name": "sans_allocation"})


# --- EF-77 : defauts du chemin d'ordre, constates sur le VRAI bot ---
#
# Noms prefixes `Dca` : `FakeExecutor` est deja pris en haut du module, et le
# redefinir l'ecraserait pour tous les tests du fichier.


class DcaExecution:
    def __init__(self, shares, price):
        self.shares = shares
        self.price = price


class DcaFill:
    def __init__(self, shares, price):
        self.execution = DcaExecution(shares, price)


class DcaLogEntry:
    def __init__(self, message):
        self.message = message


class DcaStatus:
    def __init__(self, status):
        self.status = status
        self.filled = 0.0
        self.avgFillPrice = 0.0


class DcaTrade:
    def __init__(self, status, fills=(), log=()):
        self.orderStatus = DcaStatus(status)
        self.fills = list(fills)
        self.log = [DcaLogEntry(m) for m in log]

    def isDone(self):
        return self.orderStatus.status in ("Filled", "Cancelled", "ApiCancelled", "Inactive")


class DcaIB:
    def __init__(self, trade):
        self.trade = trade
        self.cancelled = []
        self.placed_order = None

    def placeOrder(self, contract, order):
        self.placed_order = order
        return self.trade

    def waitOnUpdate(self, timeout=None):
        pass

    def cancelOrder(self, order):
        self.cancelled.append(order)
        self.trade.orderStatus.status = "Cancelled"


def _multi_executor_with(trade):
    from tradingbot.execution.ib_multi_symbol_executor import IBMultiSymbolExecutor

    executor = IBMultiSymbolExecutor(["TTE.PA"], ib_client=DcaIB(trade))
    executor.ib = DcaIB(trade)
    return executor


def test_a_fill_reported_as_rejected_is_still_treated_as_a_fill():
    """CE DEFAUT S'EST PRODUIT SUR LE VRAI BOT le 2026-09-18 : deux ordres
    (TTE, GLE) enregistres 'rejected' avec un registre local reste VIDE,
    alors que le journal du courtier montre les deux achats effectues. Le bot
    se croyait donc avec 200 EUR et aucune position tout en detenant 2
    actions payees ~158 EUR - et le versement du mois etant marque comme
    fait, il n'allait jamais s'en apercevoir."""
    trade = DcaTrade("Cancelled", fills=[DcaFill(1, 79.46)],
                     log=["Error 10349: Order TIF was set to DAY based on order preset"])
    executor = _multi_executor_with(trade)

    fill = executor.place_order("TTE.PA", "buy", 1, reason="contribution")

    assert fill.is_filled, "une execution reelle doit primer sur le statut annonce"
    assert fill.quantity == 1
    assert fill.price == 79.46
    assert "ATTENTION" in fill.reason


def test_a_genuine_rejection_records_the_ibkr_reason():
    trade = DcaTrade("Cancelled", log=["Error 10349: Order TIF was set to DAY based on order preset"])
    executor = _multi_executor_with(trade)

    fill = executor.place_order("TTE.PA", "buy", 1, reason="contribution")

    assert not fill.is_filled
    assert "10349" in fill.reason


def test_the_dca_order_declares_its_time_in_force():
    """Sans TIF explicite, le prereglage d'IB Gateway annule l'ordre."""
    trade = DcaTrade("Filled", fills=[DcaFill(1, 79.46)])
    executor = _multi_executor_with(trade)

    executor.place_order("TTE.PA", "buy", 1)

    assert executor.ib.placed_order.tif == "DAY"


def test_a_pending_dca_order_is_cancelled_instead_of_hanging():
    trade = DcaTrade("PreSubmitted")
    executor = _multi_executor_with(trade)
    executor.order_timeout_seconds = 0.05

    fill = executor.place_order("TTE.PA", "buy", 1)

    assert not fill.is_filled
    assert executor.ib.cancelled, "l'ordre doit etre annule chez le courtier"


# --- EF-78 : actions manuelles depuis le dashboard ---


def test_selling_a_line_reduces_holdings_and_credits_cash(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")
    before = {s: q for s, q in read_table(db_path, "holdings")}

    report = sell_lines(make_config(), db_path, {"TTE.PA": 1}, executor, today="2026-03-10")

    after = {s: q for s, q in read_table(db_path, "holdings")}
    assert after["TTE.PA"] == before["TTE.PA"] - 1
    assert report.cash_after > report.cash_before, "le produit de la vente doit revenir en liquidites"


def test_selling_everything_never_goes_short(tmp_path):
    """Une quantite demandee superieure a la position est PLAFONNEE : une
    faute de frappe ne doit jamais ouvrir une vente a decouvert."""
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")
    held = {s: q for s, q in read_table(db_path, "holdings")}["TTE.PA"]

    sell_lines(make_config(), db_path, {"TTE.PA": held + 999}, executor, today="2026-03-10")

    after = {s: q for s, q in read_table(db_path, "holdings")}
    assert after["TTE.PA"] == 0
    sold = [o for o in executor.orders_sent if o[1] == "sell"]
    assert sold[-1][2] == int(held), "on ne vend que ce qui est reellement detenu"


def test_selling_does_not_free_the_month_contribution(tmp_path):
    """Vendre n'annule pas le versement du mois : sinon on pourrait verser
    deux fois en vendant entre les deux."""
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")

    sell_lines(make_config(), db_path, {"TTE.PA": 1}, executor, today="2026-03-10")
    again = run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-20")

    assert again.contribution == 0.0
    assert len(read_table(db_path, "contributions")) == 1


def test_selling_is_blocked_when_the_broker_disagrees(tmp_path):
    """Meme garde-fou que le passage mensuel : un ecart de positions signifie
    qu'on ne sait pas ce qu'on detient. Voir STC 3.60 - cet ecart s'est deja
    produit en production."""
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()
    run_once(make_config(), db_path, executor=executor, dry_run=False, today="2026-03-02")
    executor._positions["TTE.PA"] = 99.0  # le courtier n'est plus d'accord
    executor.orders_sent.clear()

    report = sell_lines(make_config(), db_path, {"TTE.PA": 1}, executor, today="2026-03-10")

    assert executor.orders_sent == [], "aucune vente ne doit partir sur un ecart"
    assert any("Ecart entre les positions" in w for w in report.warnings)


def test_selling_without_an_executor_is_refused(tmp_path):
    with pytest.raises(ValueError, match="exige un executor"):
        sell_lines(make_config(), tmp_path / "dca.db", {"TTE.PA": 1}, None)


def test_selling_a_line_that_is_not_held_is_reported_not_crashed(tmp_path):
    db_path = tmp_path / "dca.db"
    executor = FakeExecutor()

    report = sell_lines(make_config(), db_path, {"TTE.PA": 1}, executor, today="2026-03-10")

    assert any("aucune position" in w for w in report.warnings)


def test_reset_backs_up_instead_of_deleting(tmp_path):
    """La seule operation destructrice du module : l'annuler doit rester
    possible, donc l'historique est deplace, jamais supprime."""
    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")

    backup = reset_state(db_path)

    assert not db_path.exists(), "le bot doit repartir de zero"
    assert backup is not None and backup.exists(), "l'historique doit etre conserve"


def test_reset_on_a_bot_that_never_ran_is_harmless(tmp_path):
    assert reset_state(tmp_path / "jamais.db") is None


def test_reset_frees_the_month_contribution(tmp_path):
    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")

    reset_state(db_path)
    again = run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-09")

    assert again.contribution == 200.0


def test_reset_twice_keeps_both_backups(tmp_path):
    """Deux remises a zero le meme jour ne doivent pas ecraser la premiere
    sauvegarde - ce serait perdre l'historique qu'on pretend conserver."""
    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")
    first = reset_state(db_path)
    run_once(make_config(), db_path, executor=FakeExecutor(), dry_run=False, today="2026-03-02")
    second = reset_state(db_path)

    assert first != second
    assert first.exists() and second.exists()


def test_changing_the_contribution_keeps_comments_and_other_fields(tmp_path):
    """Un aller-retour yaml.safe_load/safe_dump effacerait les commentaires -
    constate en testant le bouton. Ils portent le POURQUOI des reglages."""
    path = tmp_path / "bot.yml"
    path.write_text(
        "name: X\n"
        "# Reequilibrage desactive : mesure perdant sur 4 fenetres\n"
        "rebalance_band_pct: null\n"
        "monthly_contribution: 200.0\n"
        "fee_fixed: 3.0\n",
        encoding="utf-8",
    )

    written = set_monthly_contribution(path, 500)

    text = path.read_text(encoding="utf-8")
    assert written == 500.0
    assert "monthly_contribution: 500.0" in text
    assert "# Reequilibrage desactive" in text, "les commentaires doivent survivre"
    assert "fee_fixed: 3.0" in text
    assert "rebalance_band_pct: null" in text


def test_a_negative_contribution_is_refused(tmp_path):
    path = tmp_path / "bot.yml"
    path.write_text("monthly_contribution: 200.0\n", encoding="utf-8")

    for bad in (0, -50):
        with pytest.raises(ValueError):
            set_monthly_contribution(path, bad)
    assert "200.0" in path.read_text(encoding="utf-8"), "le fichier ne doit pas bouger"


def test_price_history_is_limited_to_the_requested_window(tmp_path, monkeypatch):
    """`fetch_historical_candles` sert un cache et renvoie TOUT l'historique
    connu sans egard pour `since_iso` : sans filtrage explicite on expedierait
    des milliers de points au navigateur. Meme piege deja corrige ailleurs."""
    import tradingbot.run_dca as module
    from tradingbot.types import Candle

    day_ms = 86_400_000
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    # 400 jours d'historique, alors que l'appelant n'en demande que 30.
    candles = [
        Candle(timestamp=now - i * day_ms, open=10, high=11, low=9, close=10 + i % 5, volume=1)
        for i in range(400, 0, -1)
    ]
    monkeypatch.setattr(module, "fetch_historical_candles", lambda **kw: candles)

    history = read_price_history(make_config(), tmp_path / "absent.db", days=30)

    for symbol, serie in history["series"].items():
        assert 0 < len(serie["points"]) <= 32, f"{symbol}: {len(serie['points'])} points pour 30 jours"


def test_price_history_reports_the_real_cost_basis(tmp_path, monkeypatch):
    """Un cours de 79 EUR ne dit rien tant qu'on ignore qu'on a paye 82 : le
    prix de revient vient des ordres REELLEMENT executes, frais inclus."""
    import tradingbot.run_dca as module
    module_prices = {"TTE.PA": 50.0, "ORA.PA": 10.0}
    monkeypatch.setattr(module, "fetch_historical_candles", lambda **kw: [])

    db_path = tmp_path / "dca.db"
    run_once(make_config(), db_path, executor=FakeExecutor(prices=module_prices),
             dry_run=False, today="2026-03-02")

    basis = read_price_history(make_config(), db_path, days=30)["cost_basis"]

    assert basis, "des achats ont eu lieu, le prix de revient doit exister"
    for symbol, info in basis.items():
        # Frais inclus : le revient est forcement AU-DESSUS du prix paye.
        assert info["avg_price"] >= module_prices[symbol]
