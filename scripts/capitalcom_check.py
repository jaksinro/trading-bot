"""Verifie la connexion au compte DEMO Capital.com et affiche les couts reels
d'un instrument (EF-101) : le spread et le financement de nuit, a reporter dans
l'atelier de backtest (champs "Spread" et "Financement par nuit").

Prealable (a faire soi-meme) : creer une cle API sur Capital.com (Parametres >
Integrations API, compte demo) puis remplir dans .env :
  CAPITALCOM_API_KEY=...  CAPITALCOM_IDENTIFIER=...  CAPITALCOM_PASSWORD=...

Usage : python scripts/capitalcom_check.py [terme de recherche, defaut : Ethereum]
Lecture seule : aucun ordre n'est passe.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

from tradingbot.brokers.capitalcom import CapitalComClient, CapitalComError  # noqa: E402


def main() -> None:
    load_dotenv()
    term = sys.argv[1] if len(sys.argv) > 1 else "Ethereum"
    try:
        client = CapitalComClient.from_env()
        for acc in client.accounts():
            bal = acc.get("balance") or {}
            print(f"Compte demo {acc.get('currency')} : solde {bal.get('balance')}, disponible {bal.get('available')}")
        markets = client.search_markets(term)
        if not markets:
            print(f"Aucun instrument trouve pour '{term}'.")
            return
        print(f"\nInstruments '{term}' :")
        for m in markets[:8]:
            print(f"  {m.get('epic'):<14} {m.get('instrumentName')} ({m.get('instrumentType')}, {m.get('marketStatus')})")
        epic = markets[0]["epic"]
        q = client.quote(epic)
        print(f"\n{epic} : achat {q.offer}, vente {q.bid} -> spread {q.spread_pct * 100:.3f} % du prix")
        fee = (client.market(epic).get("instrument") or {}).get("overnightFee")
        if fee:
            print(f"Financement de nuit (tel que publie par Capital.com) : {fee}")
        print("\nA reporter dans l'atelier : Spread = "
              f"{q.spread_pct * 100:.3f} %, et le taux de nuit d'une position acheteuse (converti en % par jour).")
    except CapitalComError as e:
        print(f"Erreur : {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
