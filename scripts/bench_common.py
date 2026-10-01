"""Outils communs aux bancs de mesure.

`CashEngine` : le moteur reel, mais la taille de chaque achat se calcule sur le
CASH DISPONIBLE au lieu du capital de depart. Constate le 2026-10-01 : sans
panier commun, `Engine` dimensionne sur `portfolio.starting_capital` et
`BacktestExecutor` ne verifie pas le cash ; avec 99 % de taille, un banc
continuait d'acheter ~990 USDT apres des pertes, cash negatif - un compte a
credit. Les rendements devenaient une somme de trades a mise fixe (pertes
au-dela de -100 % possibles) et non l'evolution d'un vrai compte. Ici : les
gains se reinvestissent, une perte reduit la mise suivante, jamais de credit.
"""
from tradingbot.engine import Engine


class CashEngine(Engine):
    def _buy_capital_reference(self) -> float:
        return max(self.portfolio.cash, 0.0)
