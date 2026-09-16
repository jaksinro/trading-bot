# Trading Bot (MVP crypto)

Projet developpe en cycle en V — voir [docs/STB.md](docs/STB.md) (besoin),
[docs/STC.md](docs/STC.md) (conception) et [docs/MANUEL_UTILISATEUR.md](docs/MANUEL_UTILISATEUR.md)
(guide du dashboard, non technique).

## Installation

```bash
python -m venv .venv
# Windows :
.venv/Scripts/python -m pip install -e ".[dev]"
# Linux / macOS / Raspberry Pi :
.venv/bin/python -m pip install -e ".[dev]"
```

Les commandes ci-dessous utilisent la syntaxe Windows (`.venv/Scripts/python`) ;
remplace par `.venv/bin/python` sur Linux/Raspberry Pi/macOS.

## Lancer les tests

```bash
.venv/Scripts/python -m pytest -v
```

## Lancer un backtest

```bash
.venv/Scripts/python -m tradingbot.run_backtest config/BTC_SWING_V2.yml
```

## Lancer le mode paper (testnet Binance, aucun argent reel)

1. Creer un compte testnet sur https://testnet.binance.vision/ et generer une cle API
2. Copier `.env.example` en `.env` et renseigner `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`
3. Lancer :

```bash
.venv/Scripts/python -m tradingbot.run_paper config/BTC_SWING_V2.yml
```

Le bot tourne en continu (Ctrl+C pour arreter), journalise chaque ordre et l'evolution du capital dans `data/{name}.db` (SQLite).

## Dashboard

Ouvre `dashboard.html` dans un navigateur (mis a jour automatiquement par les
bots en cours d'execution). Un onglet par bot, un onglet "Analyse (BI)" pour
comparer toutes les instances (utile pour des tests A/B de strategies), et un
onglet "⚙ Gerer les bots" pour creer, demarrer, arreter, modifier ou supprimer
un bot depuis un formulaire. Guide complet : [docs/MANUEL_UTILISATEUR.md](docs/MANUEL_UTILISATEUR.md).

Le formulaire necessite un petit serveur local (aucun argent reel, aucune
exposition reseau — localhost uniquement) :

```bash
.venv/Scripts/python -m tradingbot.control_server
```

Sous Windows, une tache planifiee peut le relancer automatiquement (avec
tous les bots connus) a l'ouverture de session - voir `scripts/autostart_bots.ps1`.

## Trouver une crypto tendance a tester

```bash
.venv/Scripts/python -m tradingbot.find_trending
```

Liste les plus fortes hausses/baisses/volumes du moment sur Binance et
propose un squelette de config pret a copier (ou a soumettre via le
formulaire "+ Nouveau bot").

## Rechercher les meilleurs parametres (backtest sur 3 ans)

```bash
.venv/Scripts/python -m tradingbot.optimize
.venv/Scripts/python -m tradingbot.optimize --symbols BTC/USDT,ETH/USDT
```

Teste ~960 combinaisons de parametres par paire (sma_cross et scalp_dip,
avec ou sans filtre de tendance, avec ou sans sizing ATR) sur 3 ans
d'historique 1h, decoupes chronologiquement en 70% entrainement / 30% test.
Le classement et la config ecrite se basent sur la performance
**out-of-sample** (test), pas sur l'entrainement — voir STB EF-26/CT-09 et
STC §3.17. Exemple reel : +23,06% en entrainement contre +0,15% en test sur
le meme candidat DOGE/USDT, demonstration concrete du risque de
surapprentissage que cette validation detecte. Meme valide, un resultat
historique reste a confirmer en paper trading avant d'etre pris au serieux.

## Reoptimisation periodique d'un bot existant

```bash
.venv/Scripts/python -m tradingbot.reoptimizer --name mon_bot
.venv/Scripts/python -m tradingbot.reoptimizer --all
```

Compare la config ACTUELLEMENT deployee d'un bot a la meilleure trouvee par
la meme recherche que `optimize`, sur sa performance out-of-sample. `--all`
(ou le bouton dashboard "Lancer la reoptimisation de tous les bots") traite
tous les bots connus en une fois, en arriere-plan. Chaque bot est assigne a
un groupe stable "auto" ou "control" (test A/B, `proposals/ab_test_groups.json`) :
le groupe "control" recoit une proposition actionnable (Appliquer/Rejeter)
dans l'onglet "Gerer les bots" du dashboard ; le groupe "auto" applique la
proposition immediatement, sans validation humaine (acceptable uniquement
parce que tout tourne en paper trading). Ne revoit un meme bot qu'une fois
par semaine, et jamais s'il a une position ouverte.

## Etat actuel (MVP)

- [x] Backtest sur donnees historiques reelles (Binance, strategies SMA cross et scalp sur creux)
- [x] Risk manager (taille de position, stop-loss, take-profit, perte max journaliere, anti-accumulation de pertes, trailing stop)
- [x] Simulation des frais de transaction (0,1% par defaut, configurable)
- [x] Mode paper (testnet Binance) avec journalisation SQLite et persistance complete entre redemarrages (historique clos + positions encore ouvertes, ex: extinction du PC)
- [x] Multi-instance isolees (capital virtuel dedie par bot) avec verrou anti-doublon
- [x] Support optionnel de plusieurs positions simultanees par instance (desactive par defaut)
- [x] Dashboard unique avec onglets, statut en direct, journal des decisions, alerte d'arret, analyse BI, graphique du cours reel avec achats/ventes superposes (barres vertes/rouges par position), axes gradues, selecteur de periode (heure/jour/mois/an/5 ans/10 ans)
- [x] Creation/modification/suppression de bot via formulaire (serveur de controle local)
- [x] Validation stricte des parametres + conformite aux regles de l'exchange (evite les plantages silencieux)
- [x] Outil de decouverte de cryptos tendance
- [x] Filtre optionnel de probabilite de hausse (Monte Carlo, 3 ans d'historique)
- [x] Outil de recherche des meilleurs parametres par backtest sur grille, avec validation out-of-sample (3 ans, 2 strategies, 3 paires)
- [x] Tests unitaires + integration (480 tests)
- [x] Filtre de tendance optionnel (EMA) pour eviter les achats a contre-courant, integre a l'optimizer — voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md
- [x] Sizing optionnel par volatilite (ATR) — resultat mitige, desormais inclus dans la grille de `optimize`/`reoptimizer`
- [x] Sortie partielle optionnelle (scale-out) — compromis risque/rendement, desactive par defaut sur tous les bots
- [x] Bot d'auto-reoptimisation periodique (`reoptimizer.py`, `--name`/`--all`), bouton dashboard "tout reoptimiser", frequence hebdomadaire, test A/B groupe auto (applique automatiquement) vs control (jamais) pour mesurer l'efficacite reelle
- [ ] Mode live — a venir, hors perimetre tant que le paper n'est pas valide sur plusieurs jours
