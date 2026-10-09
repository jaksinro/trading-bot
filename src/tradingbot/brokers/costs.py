"""Couts des courtiers pour l'atelier de backtest (EF-106).

Demande de l'utilisateur (2026-10-09) : choisir un courtier existant plutot
que saisir commission, spread et financement, et que l'atelier remplisse les
champs tout seul.

Les valeurs viennent des pages publiques des courtiers, relevees le
2026-10-09 (`CHECKED`). Les spreads crypto des CFD ne sont presque jamais
publies : seul le Bitcoin l'est (Capital.com "a partir de 50 points", Trade
Nation 60 fixes selon un comparatif). Les autres cryptos reprennent le meme
spread en % que le Bitcoin, et chaque valeur estimee le dit dans `notes`.
Capital.com se lit EN DIRECT (spread du moment, taux de nuit) quand la cle API
demo est renseignee dans .env : c'est la seule source exacte.

Conventions (celles de l'atelier, `backtest_view.COST_FIELDS`) : fractions,
spread = ecart achat / vente complet (la moitie est payee a chaque ordre),
financement de nuit = cout par jour sur la valeur de la position (negatif =
credit recu).
"""
from __future__ import annotations

import os
from typing import Callable

CHECKED = "2026-10-09"
CAPITAL_FEES = "https://capital.com/en-int/ways-to-trade/fees-and-charges"
BINANCE_FEES = "https://www.binance.com/en/fee/schedule"
IBKR_FEES = "https://www.interactivebrokers.com/en/pricing/commissions-cryptocurrencies.php"
NINJA_FEES = "https://ninjatrader.com/pricing/"
TN_CRYPTO = "https://investinglive.com/directory/brokers/trade-nation-1/review/"

# Spread : ("pct", fraction) ou ("points", ecart en dollars par unite de l'actif).
# Une crypto absente de `spread` prend le meme % que "BTC" (estimation signalee).
BROKERS: dict[str, dict] = {
    "capitalcom": {
        "label": "Capital.com - CFD sans levier",
        "fee": 0.0, "spread": {"BTC": ("points", 50.0)}, "overnight": (0.0, 0.0), "shorts": True, "live": True,
        "notes": ["Sans commission ; spread BTC publie \"a partir de 50 points\" (minimum : souvent plus large).",
                  "Sans levier (1:1) : pas de financement de nuit sur les crypto depuis 2024."],
        "sources": [CAPITAL_FEES],
    },
    "capitalcom_2x": {
        "label": "Capital.com - CFD avec levier (financement de nuit)",
        "fee": 0.0, "spread": {"BTC": ("points", 50.0)}, "overnight": (0.0006164, -0.000137), "shorts": True,
        "live": True,
        "notes": ["Financement crypto publie : achat -0,06164 %/jour (22,5 %/an), vente +0,0137 %/jour recu.",
                  "Le levier lui-meme n'est pas simule : seul son cout de nuit l'est."],
        "sources": [CAPITAL_FEES],
    },
    "tradenation": {
        "label": "Trade Nation - CFD a spread fixe",
        "fee": 0.0, "spread": {"BTC": ("points", 60.0)}, "overnight": (0.0, 0.0), "shorts": True,
        "notes": ["Spread BTC 60 (comparatif, unite non confirmee) ; financement de nuit non publie, compte a 0 : "
                  "resultat optimiste.",
                  "Crypto proposee par les entites hors UE (Bahamas, Seychelles) : acces a verifier depuis la France."],
        "sources": [TN_CRYPTO],
    },
    "ninjatrader": {
        "label": "NinjaTrader - micro-futures CME (offre gratuite)",
        # 0,39 $ de commission + ~0,40 $ de frais bourse / compensation / NFA, par contrat et par ordre.
        "fee": ("contract", 0.79, {"BTC": 0.1, "ETH": 0.1}),
        "spread": {"BTC": ("points", 5.0), "ETH": ("points", 0.5)}, "overnight": (0.0, 0.0), "shorts": True,
        "only": ("BTC", "ETH"),
        "notes": ["Commission 0,39 $ + ~0,40 $ de frais par contrat et par ordre (contrat de 0,1 BTC ou 0,1 ETH) ; "
                  "spread d'un cran de cotation.",
                  "Futures : pas de financement de nuit, mais un roulement trimestriel non compte ; "
                  "la taille arrondie au contrat n'est pas simulee."],
        "sources": [NINJA_FEES],
    },
    "binance": {
        "label": "Binance - au comptant (frais standard)",
        "fee": 0.001, "spread": {"*": ("pct", 0.0001)}, "overnight": (0.0, 0.0), "shorts": False,
        "notes": ["Commission 0,1 % par ordre ; spread d'environ un cran de cotation, negligeable.",
                  "Pas de vente a decouvert au comptant."],
        "sources": [BINANCE_FEES],
    },
    "binance_bnb": {
        "label": "Binance - au comptant, frais payes en BNB",
        "fee": 0.00075, "spread": {"*": ("pct", 0.0001)}, "overnight": (0.0, 0.0), "shorts": False,
        "notes": ["Commission 0,075 % par ordre (remise de 25 % en payant en BNB).",
                  "Pas de vente a decouvert au comptant."],
        "sources": [BINANCE_FEES],
    },
    "ibkr": {
        "label": "Interactive Brokers - crypto (Paxos)",
        "fee": 0.0018, "spread": {"*": ("pct", 0.0002)}, "overnight": (0.0, 0.0), "shorts": False,
        "notes": ["Commission 0,18 % (moins de 100 000 $ par mois), minimum 1,75 $ par ordre non simule.",
                  "Spread non publie (\"spreads exclus\") : 0,02 % estime. Liste des cryptos proposees a verifier."],
        "sources": [IBKR_FEES],
    },
}
DEFAULT_BROKER = "capitalcom"


def broker_list() -> list[dict]:
    return [{"id": k, "label": b["label"], "shorts": b["shorts"]} for k, b in BROKERS.items()]


def costs_for(broker_id: str, symbol: str, price_of: Callable[[str], float | None],
              live_reader: Callable[[str, str], dict] | None = None) -> dict:
    """Couts du courtier pour une paire. `price_of(base)` : dernier cours connu
    (pour convertir points et frais par contrat en %). `live_reader(broker, base)` :
    lecture en direct (Capital.com), qui leve une exception si impossible."""
    if broker_id not in BROKERS:
        raise ValueError(f"courtier inconnu : {broker_id}")
    b = BROKERS[broker_id]
    base = symbol.split("/")[0].upper()
    out = {"broker": broker_id, "label": b["label"], "shorts": b["shorts"], "available": True, "live": False,
           "notes": list(b["notes"]), "sources": list(b["sources"]), "checked": CHECKED}
    if b.get("only") and base not in b["only"]:
        out["available"] = False
        out["notes"].insert(0, f"{base} n'est pas proposee par ce courtier (seulement {', '.join(b['only'])}).")
        return out

    long_night, short_night = b["overnight"]
    out.update({"overnight_pct": long_night, "overnight_short_pct": short_night})
    spread = _spread(b["spread"], base, price_of, out["notes"])
    fee = b["fee"]
    if isinstance(fee, tuple):           # frais en dollars par contrat
        _, usd, sizes = fee
        price = price_of(base)
        fee = usd / (sizes[base] * price) if price else 0.0
    out.update({"fee_pct": fee, "spread_pct": spread})

    if b.get("live") and live_reader is not None and os.environ.get("CAPITALCOM_API_KEY"):
        try:
            live = live_reader(broker_id, base)
        except Exception as e:  # noqa: BLE001 - lecture en direct facultative : les valeurs publiees restent
            out["notes"].insert(0, f"Lecture en direct impossible ({type(e).__name__}) : valeurs publiees.")
        else:
            out["spread_pct"] = live["spread_pct"]
            if broker_id == "capitalcom_2x" and live.get("overnight_pct") is not None:
                out["overnight_pct"], out["overnight_short_pct"] = live["overnight_pct"], live["overnight_short_pct"]
            out["live"] = True
            out["notes"].insert(0, f"Lu en direct sur le compte demo Capital.com ({live['epic']}) : "
                                   f"spread du moment {live['spread_pct'] * 100:.3f} %.")
    elif b.get("live"):
        out["notes"].append("Cle API demo absente de .env : valeurs publiees, pas lues en direct.")
    return out


def _spread(table: dict, base: str, price_of, notes: list[str]) -> float:
    rule = table.get(base) or table.get("*")
    estimated = rule is None
    if estimated:                       # pas de spread publie : meme % que le Bitcoin
        rule, base_for_rule = table["BTC"], "BTC"
    else:
        base_for_rule = base
    kind, value = rule
    if kind == "pct":
        pct = value
    else:
        price = price_of(base_for_rule)
        pct = value / price if price else 0.0
        if price:
            shown = f"{price:,.0f}".replace(",", " ")
            notes.append(f"Spread {base_for_rule} : {value:g} $ pour un cours de {shown} $, soit {pct * 100:.3f} %.")
    if estimated:
        notes.insert(0, f"Spread {base} non publie : estime au meme % que le Bitcoin ({pct * 100:.3f} %).")
    return pct


def capitalcom_reader(client_factory=None) -> Callable[[str, str], dict]:
    """Lecture en direct sur le compte DEMO (lecture seule, aucun ordre)."""
    def read(broker_id: str, base: str) -> dict:
        from tradingbot.brokers.capitalcom import CapitalComClient

        client = (client_factory or CapitalComClient.from_env)()
        epic = f"{base}USD"
        details = client.market(epic)
        snap = details.get("snapshot") or {}
        bid, offer = float(snap["bid"]), float(snap["offer"])
        fee = (details.get("instrument") or {}).get("overnightFee") or {}
        # Capital.com : taux en %/jour, negatif = paye. Atelier : cout positif, credit negatif.
        night = ({"overnight_pct": -float(fee["longRate"]) / 100, "overnight_short_pct": -float(fee["shortRate"]) / 100}
                 if fee.get("longRate") is not None and fee.get("shortRate") is not None else {})
        return {"epic": epic, "spread_pct": (offer - bid) / ((offer + bid) / 2), **night}
    return read
