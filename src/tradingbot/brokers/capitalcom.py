"""Connecteur Capital.com, compte DEMO seulement (EF-101).

L'utilisateur vise des courtiers sans commission (2026-10-09). Capital.com
publie une API REST officielle (https://open-api.capital.com/) avec un
environnement de demonstration. Ce module couvre ce que le projet en attend :
- le SPREAD reel d'un instrument (offre - demande), a renseigner dans l'atelier
  de backtest a la place d'une commission ;
- l'historique des prix (bougies achat et vente) ;
- les comptes, positions, ouverture et fermeture de position, sur le compte
  de demonstration.

Garde-fou : le compte reel est REFUSE dans ce module. Passer en argent reel est
une decision de l'utilisateur, a prendre explicitement et plus tard - pas un
parametre qu'on bascule par erreur.

Identifiants : lus dans l'environnement (`.env`), jamais ecrits dans le code ni
dans un journal. L'utilisateur cree lui-meme sa cle API (Capital.com >
Parametres > Integrations API) et la saisit dans `.env` :
  CAPITALCOM_API_KEY, CAPITALCOM_IDENTIFIER (identifiant de connexion),
  CAPITALCOM_PASSWORD (mot de passe propre a la cle API).

Limites de l'API (doc officielle) : session de 10 minutes d'inactivite ;
1 creation de session par seconde ; 10 requetes par seconde ; 1000 ouvertures
de position par heure en demo.
"""
from __future__ import annotations

import calendar
import os
import time
from dataclasses import dataclass

import requests

from tradingbot.types import Candle

DEMO_URL = "https://demo-api-capital.backend-capital.com/api/v1"
LIVE_URL = "https://api-capital.backend-capital.com/api/v1"
SESSION_IDLE_S = 9 * 60          # la session expire apres 10 min d'inactivite : marge d'une minute
RESOLUTIONS = {"1m": "MINUTE", "5m": "MINUTE_5", "15m": "MINUTE_15", "30m": "MINUTE_30",
               "1h": "HOUR", "4h": "HOUR_4", "1d": "DAY", "1w": "WEEK"}


class CapitalComError(RuntimeError):
    pass


@dataclass(frozen=True)
class Quote:
    epic: str
    bid: float
    offer: float

    @property
    def mid(self) -> float:
        return (self.bid + self.offer) / 2

    @property
    def spread_pct(self) -> float:
        """Spread en part du prix milieu : le cout d'un aller-retour au marche."""
        return (self.offer - self.bid) / self.mid if self.mid else 0.0


class CapitalComClient:
    def __init__(self, api_key: str, identifier: str, password: str, demo: bool = True,
                 http=None, clock=time.monotonic):
        if not demo:
            raise CapitalComError("compte reel refuse : ce connecteur ne travaille que sur le compte de demonstration")
        if not (api_key and identifier and password):
            raise CapitalComError("identifiants Capital.com manquants (CAPITALCOM_API_KEY, CAPITALCOM_IDENTIFIER, "
                                  "CAPITALCOM_PASSWORD dans .env)")
        self.base_url = DEMO_URL
        self._api_key, self._identifier, self._password = api_key, identifier, password
        self._http = http or requests.Session()
        self._clock = clock
        self._tokens: dict[str, str] | None = None
        self._last_call = 0.0

    @classmethod
    def from_env(cls, **kw) -> "CapitalComClient":
        return cls(os.environ.get("CAPITALCOM_API_KEY", ""), os.environ.get("CAPITALCOM_IDENTIFIER", ""),
                   os.environ.get("CAPITALCOM_PASSWORD", ""), **kw)

    # ------------------------------------------------------------------ session
    def _login(self) -> None:
        resp = self._http.request("POST", f"{self.base_url}/session", timeout=15,
                                  headers={"X-CAP-API-KEY": self._api_key, "Content-Type": "application/json"},
                                  json={"identifier": self._identifier, "password": self._password,
                                        "encryptedPassword": False})
        if resp.status_code != 200:
            # Jamais le corps de la requete dans le message : il contient le mot de passe.
            raise CapitalComError(f"connexion refusee par Capital.com (HTTP {resp.status_code}) : "
                                  f"{_error_code(resp)}")
        cst, token = resp.headers.get("CST"), resp.headers.get("X-SECURITY-TOKEN")
        if not cst or not token:
            raise CapitalComError("connexion acceptee mais jetons de session absents de la reponse")
        self._tokens = {"CST": cst, "X-SECURITY-TOKEN": token}
        self._last_call = self._clock()

    def _call(self, method: str, path: str, *, params=None, body=None, retry=True) -> dict:
        if self._tokens is None or self._clock() - self._last_call > SESSION_IDLE_S:
            self._login()
        resp = self._http.request(method, f"{self.base_url}{path}", params=params, json=body, timeout=15,
                                  headers={**self._tokens, "Content-Type": "application/json"})
        self._last_call = self._clock()
        if resp.status_code == 401 and retry:   # session expiree cote serveur : une reconnexion, une seule
            self._tokens = None
            return self._call(method, path, params=params, body=body, retry=False)
        if resp.status_code >= 400:
            raise CapitalComError(f"{method} {path} : HTTP {resp.status_code} {_error_code(resp)}")
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------ donnees
    def accounts(self) -> list[dict]:
        return self._call("GET", "/accounts").get("accounts", [])

    def search_markets(self, term: str) -> list[dict]:
        return self._call("GET", "/markets", params={"searchTerm": term}).get("markets", [])

    def market(self, epic: str) -> dict:
        """Details complets d'un instrument (snapshot, regles de trading, financement)."""
        return self._call("GET", f"/markets/{epic}")

    def quote(self, epic: str) -> Quote:
        snap = self.market(epic).get("snapshot") or {}
        if snap.get("bid") is None or snap.get("offer") is None:
            raise CapitalComError(f"pas de cotation pour {epic} (marche ferme ?)")
        return Quote(epic=epic, bid=float(snap["bid"]), offer=float(snap["offer"]))

    def candles(self, epic: str, timeframe: str = "1h", max_bars: int = 1000) -> list[Candle]:
        """Bougies au prix MILIEU (moyenne achat / vente), comme les cours Binance
        utilises ailleurs ; le spread se compte a part (voir `quote`)."""
        if timeframe not in RESOLUTIONS:
            raise ValueError(f"unite de temps non geree : {timeframe}")
        data = self._call("GET", f"/prices/{epic}", params={"resolution": RESOLUTIONS[timeframe], "max": max_bars})
        out = []
        for p in data.get("prices", []):
            mid = {k: (p[k]["bid"] + p[k]["ask"]) / 2 for k in ("openPrice", "highPrice", "lowPrice", "closePrice")}
            ts = calendar.timegm(time.strptime(p["snapshotTimeUTC"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
            out.append(Candle(timestamp=ts, open=mid["openPrice"], high=mid["highPrice"], low=mid["lowPrice"],
                              close=mid["closePrice"], volume=float(p.get("lastTradedVolume") or 0)))
        return out

    # ------------------------------------------------------------------ positions (demo)
    def positions(self) -> list[dict]:
        return self._call("GET", "/positions").get("positions", [])

    def open_position(self, epic: str, direction: str, size: float, stop_level: float | None = None,
                      profit_level: float | None = None) -> dict:
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction : BUY ou SELL")
        if size <= 0:
            raise ValueError("taille positive attendue")
        body = {"epic": epic, "direction": direction, "size": size}
        if stop_level is not None:
            body["stopLevel"] = stop_level
        if profit_level is not None:
            body["profitLevel"] = profit_level
        ref = self._call("POST", "/positions", body=body).get("dealReference")
        if not ref:
            raise CapitalComError("ouverture sans reference d'ordre")
        return self.confirm(ref)

    def confirm(self, deal_reference: str) -> dict:
        return self._call("GET", f"/confirms/{deal_reference}")

    def close_position(self, deal_id: str) -> dict:
        return self._call("DELETE", f"/positions/{deal_id}")


def _error_code(resp) -> str:
    try:
        return str(resp.json().get("errorCode", ""))[:120]
    except ValueError:
        return ""
