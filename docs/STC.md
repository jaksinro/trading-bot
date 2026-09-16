# Spécification Technique de Conception (STC)
## Projet : Bot de Trading Automatisé — Marché Crypto

| | |
|---|---|
| **Version** | 0.42 |
| **Date** | 2026-09-15 |
| **Auteur** | jaksinro |
| **Statut** | Réalisé (au-delà du MVP initial) |
| **Étape du cycle en V** | Conception / Réalisation |
| **Document parent** | [STB.md](./STB.md) |

**Historique des versions**

| Version | Changement |
|---|---|
| 0.1 | Conception initiale du MVP (mono-algo, backtest + paper) |
| 0.2 | Multi-algo réalisé, ajout du pilotage web (dashboard + serveur de contrôle), 2e stratégie (scalping), garde-fous de validation et de conformité exchange |
| 0.3 | Filtre de probabilité de hausse (Monte Carlo, EF-18) : composant `ProbabilityGate`, décision GPU vs CPU documentée (§3.8) |
| 0.4 | Correction de deux bugs de gestion des bots : verrou anti-doublon non atomique (§3.9), fichier de config dupliqué lors d'une modification (§3.9) |
| 0.5 | Ajout de l'outil `optimize` : recherche des meilleurs paramètres par backtest systématique sur grille, 3 ans d'historique, 3 paires (§3.10) |
| 0.6 | Ajout du tableau des ordres detailles (EF-20) : `OrderResult.reason`, enrichissement de `trade_history`, `build_orders_table()`, affichage a cote de la courbe de capital (§3.11) |
| 0.7 | Ajout du support multi-positions (EF-21) : `Portfolio` passe d'une position unique a une liste de lots identifies (`lot_id`), `RiskManager.max_concurrent_positions`, `Engine` gere des sorties independantes par lot (§3.12) |
| 0.8 | Ajout de 5 ameliorations suite a l'analyse multi-positions : frais de transaction (EF-22, §3.13), garde-fou anti-accumulation de pertes (EF-23, §3.14), stop suiveur (EF-24, §3.15), persistance de l'historique entre redemarrages (EF-25, §3.16), validation out-of-sample de l'optimizer (EF-26, §3.17) |
| 0.9 | Extension de la persistance aux positions OUVERTES (EF-27, §3.18) : table `open_positions`, reconstruction du cash a partir du capital de depart et du capital immobilise, plus de liquidation automatique au redemarrage a partir de la 2e session |
| 0.10 | Remplacement de la courbe de capital par un graphique du cours reel avec les achats/ventes superposes (EF-28, §3.19) : la courbe de capital (montant en devise) etait jugee peu lisible, remplacee par le cours du marche avec des barres horizontales vertes/rouges par position |
| 0.11 | Ajout des graduations (prix/dates) sur les axes du graphique et d'un selecteur de periode (Live, 1h, 1j, 1mois, 1an, 5ans, 10ans) charge depuis l'historique reel du marche spot (EF-29, §3.19) : nouvelle route `GET /api/price-history` sur le Control Server |
| 0.12 | Etape 1 de la feuille de route performance (docs/FEUILLE_DE_ROUTE_PERFORMANCE.md) : filtre de tendance optionnel `TrendFilter` (EF-30, §3.20), backtest comparatif chiffre, limite du sizing decouverte au passage (CT-11 de la STB) |
| 0.13 | `optimize.py` inclut le filtre de tendance comme dimension de recherche (§3.10, §3.20) - premier resultat out-of-sample positif obtenu (CT-12 de la STB) |
| 0.14 | Etape 2 de la feuille de route performance : sizing optionnel par volatilite `AtrSizer` (EF-31, §3.21), resultat mitige (CT-13 de la STB). Etape 4 : consolidation des bots de test (decision de portefeuille, voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md) |
| 0.15 | Etape 3 de la feuille de route performance : sortie partielle optionnelle (EF-32, §3.22) - `Portfolio.apply_fill` gere desormais une vente partielle d'un lot, compromis risque/rendement documente (CT-14 de la STB) |
| 0.16 | Etape 5 de la feuille de route performance : bot d'auto-reoptimisation periodique semi-automatique `reoptimizer.py` (EF-33, §3.23) - nouvelles routes `GET /api/list-proposals`, `POST /api/apply-proposal`, `POST /api/dismiss-proposal`. Feuille de route complete (etapes 1 a 5) |
| 0.17 | Extension etape 5 (EF-34, EF-35, §3.23) : bouton "tout reoptimiser" (`POST /api/reoptimize-all`), sizing ATR ajoute a la grille de `optimize.py` (480->960 combinaisons/paire), frequence 30->7 jours, test A/B groupe auto/control (`assign_groups`, `run_all`) - garde-fou "validation humaine" leve pour le groupe auto (CT-16 de la STB, paper trading uniquement) |
| 0.18 | Remplacement du capital isole par instance par un panier de capital commun avec allocation dynamique par performance (EF-36, EF-37, §3.5 revisee) : nouveau module `shared_pool.py` (SQLite partage, transactions atomiques), `Engine` reserve/regle/credite le panier autour de chaque ordre reel, script `migrate_to_shared_pool.py` pour la bascule des 8 bots existants |
| 0.19 | Flotte reconstruite en 1 bot par cryptomonnaie du top 10 par capitalisation (hors stablecoins), chaque config generee par `optimize.py` (grille sma_cross/scalp_dip, validation out-of-sample 3 ans) - 6/10 paires avec edge positif valide, 4/10 sans edge demontre (deployees quand meme avec plafond/sizing reduits, voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md etape 4ter) |
| 0.20 | Tache planifiee Windows hebdomadaire pour le reoptimiseur (§3.23, resout la limite "pas de cron" documentee depuis la v0.16). Correction d'un bug reel (CT-19 de la STB) : `merge_proposal_into_config` ne remplace plus tout le bloc `risk` d'une proposition, seulement `stop_loss_pct`/`take_profit_pct` - le sizing de position (`max_position_size_pct`/`max_concurrent_positions`) reste celui deja choisi pour l'instance |
| 0.21 | Etape 6 (robustesse) : `compute_buy_and_hold_return_pct` (reporting/stats.py, EF-39) et marge minimale `MIN_IMPROVEMENT_MARGIN` (reoptimizer.py, EF-38) pour reduire le "config-shopping" demontre empiriquement (CT-20 de la STB) |
| 0.22 | Etape 6 poursuivie (§3.25) : confirmation sur 2 checks (EF-40), selection ajustee au risque (EF-41), consistance multi-fenetres (EF-42), nouvelle strategie `MeanReversionStrategy` (EF-43) - n'a pas demontre de benefice empirique sur les 4 paires sans edge a ce jour. Tous les bots repasses en groupe "control" (plus d'application automatique). CT-21 : bug d'ecrasement de config decouvert et corrige |
| 0.23 | Etape 7 (§3.26) : nouvelle famille de strategie a edge structurel `MarketMakingStrategy` + moteur dedie `MarketMakingEngine` (EF-44), inspiree du concept de market making de Hummingbot sans en importer le code (abstractions incompatibles). Simulation par approximation OHLC (limite assumee, pas de carnet d'ordres historique). CT-22 : bug reel de comptabilite multi-lots decouvert et corrige pendant la validation empirique. Resultat empirique negatif sur les 4 paires sans edge (BNB/SOL/LINK/AVAX) - aucun bot cree |
| 0.24 | Etape 8 (§3.27) : pipeline de donnees funding rate (`fetch_funding_rate_history`) + module `funding_arb.py`, backtest de validation du funding rate arbitrage (EF-45) - **Phase A uniquement**, aucune execution live (limite deliberee, chantier separe si un edge etait confirme). Nuance de garde-fou documentee : le critere "battre un buy & hold" ne s'applique pas a une strategie delta-neutre. Resultat empirique NON CONCLUANT sur BTC/ETH/SOL : le risque de base domine largement le funding collecte sur BTC, ETH ne passe que sur un signal statistiquement faible - aucune Phase B engagee |
| 0.25 | Etape 9 (§3.28), strategie proposee par l'utilisateur : `DipBounceStrategy` (EF-46, rebond de creux + verrou de gain a deux seuils, `RiskManager.should_profit_lock` nouveau) et `BuyAndHoldStrategy` (EF-47). `RiskConfig.stop_loss_pct` rendu optionnel (`None` = pas de stop-loss reel, decision assumee). **Nouveaute de perimetre** : ces 2 strategies (3 presets - dip_bounce horaire/minute + buy_and_hold) sont creables directement depuis le formulaire du dashboard, contrairement a mean_reversion/market_making/funding_arb (YAML uniquement) - `timeframe` et `warmup_candles` forces cote serveur selon le preset. Bug de rechauffement pour `buy_and_hold` prevenu avant qu'il n'existe (achat unique qui aurait ete "grille" pendant le warmup). Validation empirique horaire : resultat mitige (5/10 symboles passent le filtre, mais artefact partiel d'un marche baissier sur la periode) ; risque "pas de stop-loss" concretement observe (pire trade -3,2% du capital de test). Variante minute non testee (cout annonce, non lance) |
| 0.26 | Outil de test unifie `backtest_lab.py` (EF-48, §3.29) : les scripts scratchpad ad hoc accumules pendant les etapes 6 a 9 (parametres improvises, non traces) sont remplaces par un point d'entree unique, scriptable et interactif, pour tester UN bot sur UNE periode/devise/jeu de parametres choisis explicitement, avec un rapport de performance simple genere a la fin (console + fichier) |
| 0.27 | Refonte de la navigation du dashboard (§3.6) : 4 onglets principaux avec sous-onglets (Accueil, Bot, Configuration, Test) remplacent la barre plate ; integration de `backtest_lab.py` au dashboard via 2 nouvelles routes (`GET /api/backtest-strategies`, `POST /api/run-backtest`), nouvel onglet Test -> Backtest (EF-49) |
| 0.28 | Bouton "Redemarrer tous les bots" (EF-50, §3.6) dans le sous-onglet Supervision : nouvelle route `POST /api/restart-all-bots`, arrete puis relance chaque bot actuellement en cours depuis sa config sur disque (positions ouvertes restaurees a l'identique, EF-27), puis recharge la page - pour propager une mise a jour du logiciel (code de strategie, dashboard) aux bots deja lances sans les redemarrer un par un |
| 0.29 | CT-23 (§3.30) : bug reel decouvert via l'onglet Test/Backtest (0 bougie renvoyee alors que des donnees existaient) - `ccxt.parse8601` ignore les dates sans heure, et le cache local ne verifiait jamais qu'il couvrait la periode demandee. Corriges le jour meme dans `backtest_lab.py`/`data_feed.py`, `exchange` devient injectable pour les tests |
| 0.30 | Correction de comportement de `DipBounceStrategy` (EF-46, §3.28) suite a une relecture de l'utilisateur : retrait de la sortie sur "nouveau plus haut de la fenetre" (pouvait vendre pour un gain minuscule avant que le verrou de gain n'ait la moindre chance de s'armer) - la seule sortie possible est desormais le verrou de gain. `_in_position`/`rolling_max` retires de la strategie, le double-achat est desormais entierement gere par `RiskManager.max_concurrent_positions` |
| 0.31 | Deuxieme correction de `DipBounceStrategy` (EF-46, §3.28) le meme jour : l'entree n'exige plus de regime haussier (`close > sma` retire) - achete simplement des que le prix est proche de son plus bas recent sur la fenetre, quelle que soit la tendance |
| 0.32 | `backtest_lab.py`/onglet Test -> Backtest (§3.29) : `max_concurrent_positions` devient un parametre testable (CLI `--max-concurrent-positions`, formulaire dashboard) - jusque-la fige a 1 (defaut de `RiskConfig`), ce qui bloquait totalement une strategie coincee dans une position (constate sur `dip_bounce`, EF-46) |
| 0.33 | Deux idees proposees par l'utilisateur (§3.31) : nouveau composant `analysis/price_level_sizer.py::PriceLevelSizer` (sizing selon l'ecart au prix moyen du mois calendaire, wired dans `Engine`/`run_paper.py`/`control_server.py`/dashboard comme un 5e filtre avance, aux cotes de ATR/tendance/probabilite) ; nouveau parametre optionnel `DipBounceStrategy(force_trade_after_hours=...)` qui assouplit progressivement le seuil de creux si aucun achat n'a eu lieu depuis N heures |
| 0.34 | Les deux ajouts de la v0.33 deviennent testables via `backtest_lab.py`/l'onglet Test -> Backtest (§3.29), demande explicite de l'utilisateur : `run_one_period` accepte desormais un `PriceLevelSizer` optionnel frais par (sous-)periode, nouveau CLI `--price-level-sizing`/`--price-level-min-multiplier`/`--price-level-max-multiplier`, nouveau `ParamSpec` `force_trade_after_hours` sur les presets `dip_bounce_*` (0 = desactive, converti en `None` cote strategie) |
| 0.35 | EF-53 (§3.32) : surveillance des sorties sur un timeframe plus fin que les entrees (`Engine.check_lot_exits`/`process_price_update`, `backtest_lab.py::merge_dual_timeframe`), demande de l'utilisateur. CT-24 : bug reel decouvert et corrige pendant l'implementation (tri par instant de cloture reel, pas par timestamp d'ouverture) |
| 0.36 | EF-53 etendu aux vrais bots (§3.32), demande explicite de l'utilisateur : nouveau champ config/formulaire `exit_check_timeframe`, cable dans `run_paper.py` (reutilise le ticker deja recupere a chaque cycle, aucun appel reseau supplementaire) et valide dans `control_server.py` (doit etre plus fin que le timeframe du bot) |
| 0.37 | Volet repliable "Configuration de ce bot" dans l'onglet Bot (§3.6), demande de l'utilisateur - affiche la config sans quitter l'onglet, reutilise `GET /api/config` et `editBot` existants, aucune nouvelle route |
| 0.38 | CT-25 : bug reel corrige (`_target_prices` plantait sur `stop_loss_pct=None`, a fait tomber `ETHSWING`/`XRP_SWING` en prod). Symbole du formulaire de creation/Test devient une liste deroulante top 10 (§3.33). Onglet Test/Backtest mis en parite avec la config de bot reel (§3.34), demande explicite de l'utilisateur : `backtest_lab.py` gagne timeframe libre, reglages de risque generiques, sortie partielle, filtre de tendance EMA et sizing ATR - filtre de probabilite explicitement exclu (biais de preconnaissance). CT-26 : deux instances de `control_server.py` decouvertes tournant simultanement (aucun verrou anti-doublon dessus, contrairement aux bots) - servait des reponses avec du code perime |
| 0.39 | CT-26 corrige : `control_server.py` acquiert desormais le meme verrou atomique que les bots (§3.34). EF-55 (§3.35) : le stop-loss de `dip_bounce` (les 2 presets "Rebond de creux") redevient reglable, sur demande explicite de l'utilisateur suite a l'analyse empirique d'un backtest reel (100% de trades fermes gagnants mais -18% de rendement total a cause des positions jamais fermees) - reste vide/desactive par defaut, comportement historique inchange pour tout bot existant |
| 0.40 | Ajout du bouton "Exporter ces parametres vers un nouveau bot" sous le rapport de l'onglet Test → Backtest, demande de l'utilisateur - reprend les reglages actuels du formulaire de test et les reporte dans le formulaire de Creation (§3.36), pour ne pas avoir a retaper une config qui a donne un bon resultat en test |
| 0.41 | CT-27 : bug reel corrige - `flatten_existing_position` creditait a tort le produit de la liquidation d'un solde de test exchange (jamais achete via notre capital) sur le cash du bot, gonflant l'equity de +272/+101 des le premier demarrage sur `BTC_SWING_V2`/`ETH_SWING_V2` (§3.37). Constate suite a une demande de l'utilisateur ("nettoyer les trades en cours, ca fausse mes chiffres") apres un nettoyage de sa flotte de bots |
| 0.42 | EF-56 (§3.38) : barre de progression pendant l'execution d'un backtest (onglet Test/Backtest), demandee par l'utilisateur - animee pendant le telechargement/une simulation unique, pourcentage reel par sous-periode en mode `--repeat` |

---

## 1. Objet du document

Ce document décrit **comment** répondre aux besoins exprimés dans la STB. Chaque choix technique est relié aux exigences (EF-xx, ENF-xx) qu'il satisfait. Il servira de base :
- au développement,
- aux tests unitaires/d'intégration (qui vérifient cette STC),
- à la revue avant de démarrer le code.

---

## 2. Choix technologiques

| Choix | Décision | Justification |
|---|---|---|
| Langage | **Python 3.12+** | Écosystème mature pour la data/finance (pandas, ccxt), rapide à développer, bon pour un projet solo |
| Librairie d'accès exchange | **ccxt** | Librairie standard multi-exchange (Binance, Kraken...), gère REST + normalise les données ; facilite un changement d'exchange plus tard |
| Exchange pilote | **Binance** (via testnet pour le paper trading) | Le plus grand exchange, testnet officiel disponible, bonne documentation, gratuit |
| Stockage des trades/logs | **SQLite** (fichier local) | Suffisant pour un algo solo, pas de serveur à gérer, migrable vers PostgreSQL plus tard si multi-algo (§3.2 STB) |
| Cache données historiques | **Fichiers Parquet** (via pandas) | Rapide à lire/écrire, compact, standard pour séries temporelles |
| Configuration par instance | **Fichiers YAML** | Lisible, versionnable (sauf secrets), un fichier = une instance d'algo (répond à EF-12, réalisé) |
| Secrets (clés API) | **Variables d'environnement / fichier `.env` non versionné** | Répond à ENF-01 |
| Gestionnaire de dépendances | **pip + venv** | Simple, reproductible |
| Tests | **pytest** | Standard Python, répond à ENF-07 |
| Exécution en continu | **Process long-lived** par instance (un process Python par bot, lancé manuellement ou via le serveur de contrôle) | Répond à ENF-06 |
| Pilotage à distance | **Dashboard HTML statique + petit serveur de contrôle HTTP local** (`http.server` de la bibliothèque standard, aucun framework) | Répond à EF-14, sans dépendance supplémentaire ni exposition réseau (localhost uniquement) |

---

## 3. Architecture générale

### 3.1 Principe : un "moteur" générique, instancié plusieurs fois

L'architecture est découpée en **composants indépendants reliés par des interfaces claires**. Chaque "instance d'algo" (STB §3.2, EF-12/EF-13, **réalisé**) est un **process Python séparé**, une nouvelle exécution du même moteur avec sa propre configuration, son propre état en mémoire (Portfolio, Strategy), et son propre fichier de log/DB. Aucune coordination inter-algos n'est nécessaire : chaque instance est isolée par construction car les instances ne partagent aucun état en mémoire — seul le compte testnet réel sous-jacent est physiquement partagé (voir §3.5, capital virtuel).

```
                         ┌───────────────────────┐
                         │   Configuration        │
                         │  (config/instance.yml) │
                         └───────────┬────────────┘
                                     │
                                     ▼
┌───────────────┐   candles   ┌──────────────┐   signal   ┌──────────────┐
│  Data Feed     │───────────▶│  Strategy     │───────────▶│ Risk Manager │
│ (historique/   │             │ (règles       │            │ (valide/     │
│  temps réel)   │             │  entrée-sortie)│            │  ajuste la   │
└───────────────┘             └──────────────┘            │  taille)     │
                                                            └──────┬───────┘
                                                                   │ ordre validé
                                                                   ▼
                                                          ┌──────────────────┐
                                                          │ Execution Adapter │
                                                          │ (Backtest / Paper)│
                                                          │  Live: non fait   │
                                                          └────────┬──────────┘
                                                                   │ fills
                                                                   ▼
                                                          ┌──────────────────┐
                                                          │ Portfolio /        │
                                                          │ Position Tracker   │
                                                          └────────┬──────────┘
                                                                   │
                                                                   ▼
                                                          ┌──────────────────┐
                                                          │ Logger / Reporter │
                                                          │ (SQLite + fichiers)│
                                                          └──────────────────┘
```

### 3.2 Description des composants

| Composant | Responsabilité | Exigences couvertes |
|---|---|---|
| **Data Feed** | Récupère les bougies (OHLCV) historiques (backtest) ou en continu (paper/live) via ccxt | EF-01 |
| **Strategy** | Interface commune (`on_candle(candle) -> Signal \| None`), deux implémentations : `SmaCrossStrategy` (suivi de tendance) et `ScalpDipStrategy` (scalping sur creux) | EF-02, EF-11 |
| **Risk Manager** | Vérifie chaque signal contre les règles de risque (taille max, stop-loss, take-profit, perte max journalière) avant transmission ; expose aussi `explain_rejection()` pour journaliser la raison d'un refus | EF-09, ENF-02 |
| **Execution Adapter** | Deux implémentations d'une même interface (`place_order`, `get_position`, `get_balance`) : `BacktestExecutor` (simulateur pur) et `PaperExecutor` (testnet Binance réel via ccxt). Le mode `live` (EF-05) n'est pas implémenté à ce jour | EF-03, EF-04, ENF-02 |
| **Portfolio Tracker** | Maintient l'état du capital (virtuel, voir §3.5), des positions ouvertes, l'historique des trades clôturés, calcule le P&L en continu | EF-07 |
| **Logger / Reporter** | Écrit chaque ordre en base (SQLite), génère les données du dashboard (voir §3.6), expose un résumé de performance (P&L, drawdown, win rate, nombre de trades) | EF-06, EF-07, ENF-04 |
| **Engine (orchestrateur)** | Boucle principale : lit une bougie → Risk Manager (stop-loss/take-profit) → Strategy → Risk Manager (validation) → Execution → Portfolio. Construit un message de décision détaillé (action + raison + écart de prix) à chaque cycle, via un callback `on_decision` | EF-08, EF-15, ENF-03 |
| **Process Lock** | Empêche deux process de la même instance de tourner en même temps (fichier `bot_{nom}.lock` contenant le PID, nettoyage automatique si le process référencé n'existe plus) | ENF-03 |
| **Control Server** | Serveur HTTP local (localhost uniquement) qui crée/lance/arrête/modifie/supprime des instances depuis le dashboard, et sert les fichiers du dashboard | EF-14 |
| **Dashboard** | Page HTML unique avec un onglet par instance + un onglet d'analyse globale (BI) + un onglet de gestion, rafraîchie automatiquement | EF-07, EF-14, EF-15, EF-16 |
| **Probability Gate** | Composant optionnel (désactivé par défaut) : simulation Monte Carlo sur 3 ans d'historique, bloque un achat si la probabilité estimée de hausse à 24h est sous un seuil configuré | EF-18 |
| **Optimizer** | Outil CLI (`optimize.py`) : teste une grille de paramètres pour les deux stratégies sur plusieurs paires et 3 ans d'historique via le moteur de backtest existant, classe les résultats par rendement, génère une config prête à l'emploi pour le meilleur résultat | EF-19 |
| **Orders Table** | `build_orders_table()` : pour chaque position (ouverte ou clôturée), calcule les prix cibles (take-profit/stop-loss) à partir du prix d'entrée réel et de la config de risque, et les compare au prix de vente réel si la position est fermée | EF-20 |
| **Multi-positions** | `Portfolio.positions` (liste de lots identifiés), `RiskConfig.max_concurrent_positions`, sorties indépendantes par lot dans l'Engine | EF-21 |

### 3.3 Interface commune Strategy (contrat)

Toute stratégie doit implémenter :
- `on_candle(candle) -> Signal | None` — appelé à chaque nouvelle bougie, retourne un signal d'achat/vente/rien
- pas d'accès direct à l'exécution ou au réseau : une stratégie est une fonction pure testable unitairement (ENF-07)

### 3.4 Interface commune ExecutionAdapter (contrat)

- `place_order(side, quantity, price) -> OrderResult`
- `get_position() -> Position`
- `get_balance() -> float`

Les implémentations (Backtest/Paper) respectent cette interface, ce qui garantit que la même Strategy et le même Risk Manager fonctionnent sans modification dans les deux modes (EF-03, EF-04).

### 3.5 Panier de capital commun avec allocation dynamique (EF-36, EF-37) — révisée v0.18

**Contexte historique** : jusqu'à v0.17, chaque instance `PaperExecutor` déclarait un `capital_allocated` fixe et **isolé** (voir historique STB v0.1-v0.17) — nécessaire à l'époque car toutes les instances se connectent au **même compte testnet réel** (mêmes clés API) et une isolation logique évitait qu'une instance voie son solde pollué par les trades des autres.

**Évolution demandée** : l'utilisateur a explicitement demandé le remplacement de cette isolation par un **panier de capital commun**, dans lequel tous les bots piochent pour investir, avec une allocation qui se déplace automatiquement vers les stratégies les plus performantes plutôt que de rester figée.

**Mécanisme retenu** : un panier SQLite partagé (`data/shared_pool.db`, module `shared_pool.py`), en mode WAL avec des transactions `BEGIN IMMEDIATE`. Chaque bot tournant dans son propre PROCESSUS OS (pas juste un thread), la coordination doit être inter-processus — SQLite est réutilisé ici (déjà la techno de confiance du projet, `reporting/logger.py`) car `BEGIN IMMEDIATE` sérialise nativement les écritures concurrentes entre bots, contrairement au pattern non protégé déjà présent ailleurs dans le projet (`reoptimizer.assign_groups`/`ab_test_groups.json`, lecture-modification-écriture sans verrou — acceptable là car un seul thread y écrit, pas transposable ici où 8 processus indépendants doivent pouvoir dépenser le même argent sans jamais le découvrir).

Schéma (`SharedPool`, `src/tradingbot/shared_pool.py`) :
- `pool` (ligne unique) : `total_cash` (disponible), `reserved_cash` (informationnel/contrôle).
- `reservations` : trace chaque réservation d'achat (`'open'`/`'settled'`/`'released'`).
- `ledger` : journal d'audit append-only (qui a dépensé/reçu quoi, quand, solde après coup) — utile pour diagnostiquer 8 bots concurrents.
- `bot_allocation` : `base_cap`, `multiplier`, `last_score`, `trade_count` par bot — l'allocation dynamique (voir plus bas).

**Flux d'achat en deux temps** (`Engine._handle_buy_signal`) : on doit choisir une quantité AVANT de connaître le coût exact du fill réel.
1. `reserve(instance_name, montant_estime)` — **avant** l'ordre réel, avec une marge de 1% contre le slippage du market order (`RESERVATION_SLIPPAGE_BUFFER`). Lève `InsufficientFunds` si le panier n'a pas assez de cash — l'achat est alors simplement ignoré ce cycle (traité comme un rejet classique, jamais une erreur fatale).
2. Ordre réel envoyé à l'exchange (`PaperExecutor.place_order`, inchangé).
3. `settle(reservation_id, cout_reel)` — après le fill, ajuste le panier du delta entre l'estimation réservée et le coût réel (recrédite le surplus, ou absorbe un petit dépassement rare si le slippage dépasse la marge — voir CT-17 de la STB).
4. `release(reservation_id)` si l'ordre est rejeté par l'exchange — rend intégralement le montant réservé.

**Flux de vente** (`Engine._place_order`, après un fill de vente) : `credit(instance_name, produit_net)` directement — pas de réservation nécessaire, quantité et prix sont déjà connus.

`reconcile_orphaned_reservations()` est appelé une fois au démarrage de chaque bot (`run_paper.main`) : libère les réservations `'open'` de CETTE instance trop anciennes (crash entre `reserve()` et `settle()`/`release()`), en vérifiant d'abord dans son propre journal d'ordres (`TradeLogger.load_recent_buy_orders`) si un fill correspondant existe déjà (règle alors via `settle()` rétroactif plutôt que `release()`, pour ne jamais créditer deux fois un achat qui a réellement eu lieu).

**`capital_allocated` reste déclaré par config, mais change de sens** : ce n'est plus un budget exclusif, c'est le **plafond de mise de base** (`base_cap`) de cette instance dans le panier commun — la référence passée à `RiskManager.size_for_signal` devient `min(effective_cap, panier.available_cash())` (`Engine._buy_capital_reference`), où `effective_cap = base_cap × multiplier`. Ce plafond empêche un bot agressif de monopoliser le panier au détriment des 7 autres ; le `min()` avec le cash réellement disponible garantit qu'aucun bot ne peut viser plus que ce qui existe globalement, même si son propre plafond est plus large.

**Allocation dynamique par performance (EF-37)** : `SharedPool.update_allocation_after_trade`, appelée après chaque trade clôturé (`Engine._place_order`, côté vente). Avant que le bot ait clôturé 10 trades en live, `multiplier = 1.0` (comportement historique inchangé). Une fois ce seuil atteint, à chaque nouveau trade clôturé : `score = win_rate × rendement_moyen_par_trade` sur les 20 derniers trades ; si le score s'améliore par rapport à la dernière mesure, `multiplier *= 1.05`, s'il se dégrade, `multiplier *= 0.95` ; borné à `[0.5, 1.5]` pour qu'aucun bot ne soit ni totalement asphyxié ni en position de tout monopoliser après une seule série. Ce choix (ajustement incrémental, pas de redistribution proportionnelle globale entre bots) a été retenu explicitement par l'utilisateur pour rester simple à auditer.

**Restauration/redémarrage** : le cash de reporting de chaque instance (`Portfolio.cash`, affiché dans le dashboard) continue d'être reconstruit via `compute_restored_cash()` (formule inchangée, §3.18) — ce nombre garde son utilité pour le suivi de performance individuelle (P&L, win rate, comparaisons A/B) et pour la continuité du mode backtest (simulation isolée, sans panier commun). La disponibilité RÉELLE des fonds ne dépend en revanche plus de ce nombre : elle vit exclusivement dans `data/shared_pool.db`, une base durable et partagée qui survit indépendamment aux redémarrages de chaque bot.

**Migration** (`migrate_to_shared_pool.py`, à exécuter une seule fois, tous les bots arrêtés) : calcule le cash réel de chacun des 8 bots existants avec la même formule (`capital_allocated + realized_pnl - immobilisé_dans_positions_ouvertes`), initialise le panier à la SOMME de ces cash réels (pas à la somme brute des `capital_allocated` nominaux, puisque l'argent immobilisé dans une position ouverte n'est pas disponible tant qu'elle n'est pas revendue), et écrit une ligne de ledger `admin_adjust` par bot pour une traçabilité complète de l'origine du panier initial.

**Limites connues** : voir CT-17 (petit écart possible entre montant réservé et coût réel du fill) et CT-18 (équité de la paire A/B `btc_sma_cross_v1`/`btc_sma_cross_fast_v1` sensible à l'ordre d'exécution en cas de tension sur le panier, compromis accepté explicitement par l'utilisateur) dans la STB.

### 3.6 Pilotage web (dashboard + serveur de contrôle)

```
Navigateur                    dashboard.html (statique, régénéré par chaque bot)
    │                              │
    │  ouvre / rafraîchit (15s)    │ charge dynamiquement
    ▼                              ▼
dashboard.html  ───script tags───▶ dashboard_data/{instance}.js  (écrit par chaque bot)
    │
    │  fetch (creer/demarrer/arreter/modifier/supprimer)
    ▼
control_server.py (localhost:8765)
    │
    │  subprocess.Popen("python -m tradingbot.run_paper <config>.yml")
    ▼
Process du bot (indépendant, écrit son propre dashboard_data/{instance}.js)
```

- **Un seul fichier HTML statique** (`dashboard.html`) partagé par toutes les instances, régénéré à l'identique par chacune à chaque cycle — évite qu'une instance écrase le suivi d'une autre.
- Chaque instance écrit ses données dans un fichier JS séparé (`dashboard_data/{nom}.js`, chargé via balise `<script>` plutôt que `fetch` pour fonctionner même en ouverture fichier local, sans contrainte CORS).
- Le **Control Server** (`control_server.py`) est un serveur HTTP minimal (bibliothèque standard, sans framework) qui n'écoute que sur `localhost` : il ne fait rien d'autre que lire/écrire des fichiers de config YAML et lancer/arrêter des process Python. Aucune donnée n'est exposée au réseau.
- Toute création/modification passe par `build_config()`, qui valide les paramètres (voir §3.7) avant d'écrire quoi que ce soit.
- Un bot lancé via le Control Server tourne sans fenêtre visible, sortie redirigée vers `logs/{nom}.log` ; le serveur attend un court délai après le lancement et vérifie que le process n'a pas immédiatement planté, pour ne jamais laisser un plantage silencieux (cause du premier incident rencontré en usage réel).
- **Refonte visuelle (2026-09-12)** : palette sombre retravaillée (surfaces/bordures/accents dédiés, police Inter via Google Fonts), en-tête dédié séparé du contenu, onglets avec puce de statut par bot, cartes de statistiques avec bordures et hover, graphique de cours avec dégradé sous la courbe. Le formulaire de création/modification de bot (devenu volumineux au fil des étapes de la feuille de route performance) est réorganisé en 3 blocs : **Général**, **Gestion du risque** (toujours visibles) et **Filtres avancés** — 4 sections `<details>` repliables (sortie partielle, probabilité, tendance, ATR) qui s'ouvrent automatiquement en mode "Modifier" si le filtre correspondant est déjà actif sur le bot. Purement présentationnel : aucun champ, id, comportement JS ou route API n'a changé.
- **Refonte de la navigation (2026-09-14)** : la barre d'onglets plate (un onglet par bot + BI + "Gérer les bots") est remplacée par **4 onglets principaux avec sous-onglets** — `currentMainTab` (`"home" | "bot" | "config" | "test"`) remplace l'ancien `currentInstance` a sémantique double (nom de bot OU sentinelle `BI_TAB_ID`/`NEW_BOT_TAB_ID`), avec un state dédié par section (`currentBotName`, `currentConfigSubTab`, `currentTestSubTab`) : **Accueil** (ex-"Analyse (BI)", `renderHome`, affiché par défaut), **Bot** (`renderBotContent`, un sous-onglet par instance), **Configuration** (`renderConfigContent` dispatchant vers `renderSupervisionTab` (ex-liste des bots + propositions de réoptimisation) ou `renderCreationTab` (ex-formulaire, désormais scindé de la supervision)), **Test** (`renderTestContent`, nouveau). Chaque contenu structurel ne se reconstruit que s'il est absent du DOM (même garde qu'avant pour ne pas effacer un formulaire en cours de saisie à chaque rafraîchissement de 15s) ; `editBot` bascule désormais explicitement `currentMainTab`/`currentConfigSubTab` avant de peupler le formulaire.
- **Onglet Test → Backtest (2026-09-14, EF-48 suite)** : intègre `backtest_lab.py` (§3.29) au dashboard plutôt que de le laisser CLI-only. Deux nouvelles routes sur `control_server.py` : `GET /api/backtest-strategies` (renvoie `backtest_lab.presets_metadata()` — la même déclaration de `PRESETS` que le CLI, aucune duplication) pour construire dynamiquement le formulaire (champs par stratégie, verrou stop-loss), et `POST /api/run-backtest` qui construit un `argparse.Namespace` depuis le JSON (`backtest_lab.build_namespace_from_payload`) et appelle `run_backtest_job` — strictement le même code que la CLI, aucune logique de backtest dupliquée côté serveur web. Le formulaire envoie les paramètres en unités "pourcentage humain" (ex. `0.5` pour 0,5%), cohérent avec la convention déjà utilisée par `--param`/`--risk` en CLI.
- **Redémarrage groupé des bots (2026-09-14, EF-50)** : nouvelle route `POST /api/restart-all-bots` (`Handler._handle_restart_all`) — itère `list_known_configs()`, ne touche qu'aux bots avec `running == True`, et pour chacun reutilise exactement le meme enchainement que `_handle_update` quand un bot tournant est modifié (`_kill_by_name` puis `time.sleep(0.5)` puis `launch_process(config_path, name)`), sans dupliquer cette logique. Motivation : un process Python déjà lancé ne recharge jamais son propre code (ex. la refonte de navigation ci-dessus) — avant cette route, la seule façon de propager une mise à jour à un bot déjà en cours était de le redémarrer un par un depuis le sous-onglet Supervision. Bouton correspondant dans `reporting/dashboard.py` (sous-onglet Supervision, à côté de "Bots existants") : `confirm()` avant d'agir (action groupée sur des process réels), puis `window.location.reload()` après quelques secondes pour recharger `dashboard.html` lui-même (régénéré par les bots redémarrés avec le template le plus récent), pas seulement les données.
- **Volet "Configuration de ce bot" dans l'onglet Bot (2026-09-15)** : demande de l'utilisateur ("voir sa config sans aller dans l'onglet configuration"). Un `<details>` repliable (`renderBotContent`) appelle `loadBotConfigPanel(name)` a l'ouverture (evenement `ontoggle`, pas a chaque rafraichissement de 15s - l'etat ouvert/ferme est prealablement lu puis reapplique a la reconstruction du DOM pour ne pas se refermer tout seul) qui reutilise la route `GET /api/config` deja existante (celle utilisee par `editBot`) et l'affiche via `renderConfigSummary` (tableau cle/valeur generique sur tous les champs de la config, y compris les filtres avances actifs). Aucune nouvelle route serveur - le bouton "Modifier cette configuration" delegue integralement a `editBot(name)` deja existant (bascule vers Configuration -> Creation, formulaire pre-rempli, enregistrer relance le bot si necessaire) : aucune logique d'edition dupliquee.

### 3.7 Garde-fous de fiabilité (ENF-09, ENF-10)

Deux classes de garde-fous ajoutées suite à des incidents réels rencontrés pendant l'usage :

**a) Validation des paramètres avant tout lancement** (`build_config()`) :
- cohérence des fenêtres de stratégie (ex. moyenne courte < moyenne longue),
- bornes des pourcentages de risque (0 à 100 %),
- capital alloué strictement positif,
- bougies de réchauffement suffisantes pour la stratégie choisie,
- **le symbole doit exister réellement sur Binance** (pas seulement respecter le format `BASE/QUOTE`) — avec suggestion automatique de la paire la plus proche en cas de faute de frappe probable (ex. "DODGE/USDT" → suggestion "DOGE/USDT").

**b) Conformité aux règles de l'exchange au moment de l'ordre** (`PaperExecutor.place_order`) :
- la quantité est arrondie à la précision exacte de la paire (`exchange.amount_to_precision`) — certaines paires n'acceptent que des quantités entières (ex. DOGE sur Binance), contrairement à BTC/ETH qui acceptent des fractions,
- l'ordre est rejeté proprement (pas d'exception, pas de crash du process) si le montant ou la quantité arrondie tombe sous le minimum autorisé par l'exchange,
- ce rejet est visible dans le journal de décisions du dashboard ("rejeté par l'exchange (quantité/montant sous le minimum autorisé)").

Sans (b), une paire à quantité entière obligatoire (DOGE) aurait fait planter silencieusement le process au premier ordre — incident identifié et corrigé pendant la réalisation.

### 3.8 Filtre de probabilité de hausse (EF-18) — `ProbabilityGate`

**Méthode** : bootstrap Monte Carlo sur les rendements journaliers log des 3 dernières années (`fetch_historical_candles`, timeframe `1d`, réutilise le cache Parquet existant). Pour chaque simulation, un rendement journalier est tiré au hasard (avec remise) parmi l'historique observé, et la probabilité retournée est la proportion de tirages positifs sur `n_simulations` (200 000 par défaut). C'est un **bootstrap empirique**, pas un modèle paramétrique (ex. mouvement brownien géométrique) : il capture la distribution réelle des rendements (asymétrie, queues épaisses) sans supposer une loi normale.

**Ce que ça n'est PAS** : une prédiction fiable. C'est une extrapolation statistique de la volatilité et de la tendance passées (STB CT-06) — un marché peut toujours partir dans une direction jamais observée sur la période d'historique utilisée.

**Décision GPU vs CPU (benchmark réel effectué)** : la demande initiale visait à utiliser le GPU (RTX 3060, disponible sur la machine) pour accélérer le calcul. Un test avec CuPy/CUDA a été mené :
- le driver NVIDIA était présent, mais les bibliothèques CUDA runtime (curand, nvrtc) ne l'étaient pas — installées séparément via les paquets pip `nvidia-curand-cu12`, `nvidia-cuda-runtime-cu12`, `nvidia-cuda-nvrtc-cu12` (plus léger qu'un CUDA Toolkit complet),
- une fois fonctionnel, le GPU s'est avéré **3 fois plus lent** que le CPU (numpy) pour la taille de simulation nécessaire ici (~200 000 tirages) : le coût de lancement des kernels CUDA dépasse largement le gain de parallélisme à cette échelle (22ms en CPU contre plusieurs centaines de ms en GPU),
- **décision : calcul en CPU (numpy)**, sans dépendance GPU. Le gain de parallélisme du GPU ne devient intéressant qu'à partir de dizaines/centaines de millions d'éléments — hors de propos pour une estimation de probabilité qui n'a besoin que de quelques centaines de milliers de tirages pour être statistiquement stable.

**Intégration dans l'Engine** : le filtre n'est consulté que pour les signaux d'**achat**, après validation par le Risk Manager, jamais pour les ventes (une vente de protection — stop-loss/take-profit — ne doit jamais être bloquée par un filtre statistique). En cas d'échec du calcul (ex. API indisponible), le filtre **laisse passer l'achat** (fail-open) plutôt que de bloquer indéfiniment le trading sur un incident réseau temporaire — ce n'est pas une règle de risque critique comme le stop-loss, c'est une sécurité additionnelle optionnelle.

**Cache** : la probabilité est recalculée au maximum une fois toutes les 6h par instance (configurable), pas à chaque bougie — la distribution des rendements journaliers ne change pas de façon significative à l'échelle de la minute, et cela évite de retélécharger 3 ans d'historique en boucle.

**Configuration** (section optionnelle, absente = désactivé) :
```yaml
probability_filter:
  enabled: true
  min_probability: 0.55   # bloque l'achat si la probabilite estimee est sous ce seuil
  lookback_years: 3.0
  n_simulations: 200000
```

### 3.9 Bugs de gestion des bots identifiés et corriges

Deux incidents reels rencontres en usage, tous deux lies a la gestion multi-fichiers/multi-process des instances :

**a) Config dupliquee lors d'une modification.** `_handle_update` recalculait le chemin du fichier a partir du champ `name` (`CONFIG_DIR / f"{name}.yml"`) au lieu de reecrire le fichier d'origine. Pour une config dont le nom de fichier ne correspond pas a son champ `name` interne (ex. `doge_scalp.yml` contient `name: doge_scalp_v1`), modifier ce bot creait un **second** fichier (`doge_scalp_v1.yml`) au lieu de mettre a jour le premier — les deux fichiers portant le meme nom interne, l'instance apparaissait deux fois dans "Gerer les bots". **Correction** : `get_config_path_for_name()` localise le vrai fichier par son champ `name` (jamais par convention de nommage), et `_handle_launch`/`_handle_update` refusent desormais toute creation dont le nom existe deja ailleurs.

**b) Onglet fantome apres renommage.** Renommer un bot supprimait bien l'ancien fichier de config, mais ne nettoyait jamais son entree dans le registre du dashboard (`dashboard_data/registry.state`) ni son fichier de donnees (`dashboard_data/{ancien_nom}.js`) — l'ancien nom restait affiche indefiniment comme un onglet fige. **Correction** : `remove_from_dashboard_registry()`, deja utilisee par la suppression, est desormais aussi appelee lors d'un renommage.

**c) Verrou anti-doublon non atomique.** `process_lock.acquire_lock()` verifiait `lock_path.exists()` puis ecrivait le fichier en deux etapes separees (race condition classique, TOCTOU) : deux lancements survenant au meme instant (ex. double-clic sur "Demarrer" avant que le bouton ne soit desactive) pouvaient tous les deux passer la verification avant qu'aucun n'ait ecrit son PID, aboutissant a deux process actifs pour la meme instance. **Correction** : creation atomique du verrou (`os.open` avec `O_CREAT | O_EXCL`), qui garantit qu'un seul lancement peut reussir meme en cas de collision parfaite (verifie par un test de concurrence avec deux threads). Le formulaire du dashboard desactive aussi le bouton pendant une requete en cours, en defense supplementaire.

**Note distincte, non liee au code du projet** : sur cette machine, chaque process Python lance via `subprocess.Popen` apparait en double dans le gestionnaire de taches (memes ligne de commande, meme instant de creation). Verifie et confirme comme un artefact du systeme (probablement un logiciel de securite/anti-triche a hooks noyau actif sur la machine) : seul un des deux PID detient reellement le verrou applicatif et execute le code du bot ; l'autre est un process inerte qui n'interagit jamais avec l'exchange. Sans consequence fonctionnelle, mais peut surprendre en observant le gestionnaire de taches Windows.

### 3.10 Recherche de parametres par backtest systematique (EF-19) — `optimize.py`

**Principe** : reutilise integralement le moteur de backtest existant (Engine + BacktestExecutor + RiskManager + Portfolio, §3) — aucune nouvelle logique de simulation, seulement une boucle qui instancie une combinaison de parametres a la fois et lit le rapport de performance (`compute_report`).

**Grille testee** (3 paires par defaut - BTC/USDT, ETH/USDT, DOGE/USDT - 1h, 3 ans) :
- `sma_cross` : 5 fenetres courtes x 5 fenetres longues (paires valides uniquement, courte < longue) x 2 stop-loss x 4 options de filtre de tendance (desactive, EMA50, EMA100, EMA200 - §3.20) ≈ 192 combinaisons
- `scalp_dip` : 3 lookbacks x 4 seuils de creux x 2 stop-loss x 3 take-profit x 4 options de filtre de tendance = 288 combinaisons
- Total : 480 combinaisons x N paires, executes en quelques dizaines de secondes par paire (le moteur de backtest est une simple boucle Python sur des donnees deja en memoire, sans appel reseau).

**Filtre de significativite** : une combinaison generant moins de `MIN_TRADES_FOR_SIGNIFICANCE` (5) trades sur 3 ans est ecartee du classement — un resultat sur 1 ou 2 trades n'est pas statistiquement exploitable, meme s'il affiche un rendement impressionnant.

**Sortie** : classement top 10 par rendement total, et une config YAML prete a l'emploi ecrite pour le meilleur resultat (`config/optimized_{paire}_{strategie}.yml`) — **jamais lancee automatiquement**, l'utilisateur doit la revoir et la demarrer explicitement (dashboard ou CLI).

**Limite fondamentale (CT-07 de la STB), a ne jamais perdre de vue** : c'est une optimisation *in-sample* — les parametres gagnants sont choisis parce qu'ils ont le mieux fonctionne SUR CES MEMES donnees. Rien ne garantit une performance similaire sur les 3 prochaines annees (risque de surapprentissage/overfitting classique en trading algorithmique). L'outil sert a degrossir une recherche parmi de nombreuses combinaisons, pas a produire une certitude ; toute config gagnante doit etre validee en paper trading avant d'etre prise au serieux.

**Choix technique note** : le balayage tourne a la granularite 1h pour les deux familles de strategies (y compris `scalp_dip`, dont les instances de production tournent plutot en 1m/5m) — un compromis assume pour la tractabilite (3 ans en 1m represente ~1,5M bougies par paire contre ~26 000 en 1h) ; les ratios de parametres trouves (seuil de creux vs stop-loss/take-profit) restent indicatifs meme si le timeframe de production differe.

### 3.11 Tableau des ordres detailles (EF-20)

**Besoin** : voir, pour chaque instance, le prix reel d'achat de chaque position, le prix de vente **vise** par l'algo (calcule depuis la config de risque), et - si la position est fermee - le prix de vente **reel** obtenu, pour comparer directement l'intention et le resultat.

**Modifications necessaires pour tracer cette info** :
- `OrderResult` gagne un champ `reason` (`stop_loss`, `take_profit`, `flatten_on_start`, ou la raison du signal de strategie) - propage a travers `ExecutionAdapter.place_order()` (nouveau parametre `reason`, retro-compatible car par defaut `""`) jusqu'a la construction de l'ordre dans chaque executor.
- `Portfolio.trade_history` (deja utilise pour le win rate, §3.2) est enrichi : en plus de `pnl`, chaque trade cloture garde desormais `entry_price`, `entry_timestamp`, `exit_price`, `quantity`, `reason`.
- `Position` gagne `entry_timestamp`, mis a jour a chaque achat.

**Calcul des prix cibles** (`reporting/stats.py::build_orders_table()`) : pour une position ouverte OU un trade cloture, le prix cible de take-profit est `prix_entree * (1 + take_profit_pct)` et de stop-loss `prix_entree * (1 - stop_loss_pct)`, a partir de la config de risque de l'instance. Fonction pure, testee independamment (pas d'acces reseau).

**Limite assumee** : ces prix cibles sont recalcules a partir de la config de risque **actuelle** de l'instance. Si la config a change entre l'ouverture d'un trade historique et maintenant (via "Modifier"), le prix cible affiche pour ce trade passe reflete la config ACTUELLE, pas celle en vigueur au moment du trade — impact mineur en pratique car modifier une instance la redemarre et vide son historique en memoire (§3.7), donc aucun trade affiche n'a pu survivre a un changement de config au sein d'une meme execution.

**Affichage** : nouveau panneau tableau (colonnes : statut, achat, take-profit vise, stop-loss vise, vente reelle, raison, P&L) place a cote de la courbe de capital dans le dashboard, plutot qu'en dessous - disposition en deux colonnes flexibles.

### 3.12 Support multi-positions (EF-21)

**Avant** : `Portfolio` ne trackait qu'une seule `Position`. Le `RiskManager` bloquait tout signal d'achat des qu'une position etait ouverte (`max_concurrent_positions` implicite = 1).

**Changements** :
- `Position` gagne un `lot_id` (identifiant unique par lot ouvert).
- `Portfolio.position` (singulier) devient une **propriete de compatibilite** retournant le lot le plus ancien ; la vraie source de verite est `Portfolio.positions: list[Position]`.
- `Portfolio.apply_fill(order, lot_id=None)` : un achat cree toujours un nouveau lot ; une vente ferme le lot precis identifie par `lot_id`, ou le plus ancien (FIFO) si `lot_id` est omis - ce qui garantit que **tout code existant qui n'utilise jamais plus d'un lot continue de fonctionner sans modification**.
- `RiskConfig.max_concurrent_positions` (defaut `1`) : `RiskManager.validate()` autorise un achat tant que `open_positions_count < max_concurrent_positions`.
- `Engine._decide()` : verifie le stop-loss/take-profit **independamment pour chaque lot ouvert** (une bougie peut declencher la fermeture de plusieurs lots a la fois) ; un signal d'achat de la strategie ouvre un nouveau lot si la limite le permet ; un signal de **vente** de la strategie ferme **tous** les lots ouverts (sortie de tendance complete, pas une sortie partielle - coherent avec des strategies comme `sma_cross` qui raisonnent en tendance globale, pas par lot).
- `ExecutionAdapter` gagne `get_positions() -> list[Position]` et un parametre `lot_id` sur `place_order()`.
- Le dimensionnement (`size_for_signal`) utilise desormais le **capital alloue initial** de l'instance (`portfolio.starting_capital`) plutot que le cash courant - necessaire pour que chaque lot ait une taille coherente independamment du nombre de lots deja ouverts. **Effet de bord assume** : pour les instances a une seule position, ceci remplace un dimensionnement qui composait avec les gains/pertes (cash courant) par un dimensionnement fixe sur le capital de depart - les resultats de backtest chiffres avant cette version ne sont plus reproductibles a l'identique (ecart mineur observe : +2,55% -> +2,98% sur le meme backtest BTC/USDT).
- Garde-fou de validation (`control_server.build_config`) : `max_concurrent_positions * max_position_size_pct` ne doit jamais depasser 100% du capital.

**Resultat empirique (test reel effectue)** : sur DOGE/USDT, `scalp_dip`, meme configuration sauf `max_concurrent_positions` :

| max_concurrent_positions | Rendement | Drawdown max |
|---|---|---|
| 1 | +5,21 % | 11,25 % |
| 5 | **-34,68 %** | 54,17 % |

**Enseignement (CT-08 de la STB)** : plus de positions simultanees n'ameliore pas mecaniquement la performance. `scalp_dip` continue d'ouvrir de nouveaux lots a chaque creux detecte, sans tenir compte des lots deja perdants — pendant une tendance baissiere soutenue, ca accumule plusieurs pertes correlees (5 lots au stop-loss) plutot qu'une seule. Cette fonctionnalite est un outil d'experimentation pour explorer les capacites du systeme, pas une amelioration a activer par defaut.

Les 5 sections suivantes (§3.13 a §3.17) sont les ameliorations decidees en reponse directe a ce constat.

### 3.13 Simulation des frais de transaction (EF-22)

**Avant** : le P&L affiche ignorait les frais preleves par l'exchange sur chaque ordre — un backtest ou un paper trading pouvait donc afficher un resultat positif qui aurait ete negatif net de frais.

**Changements** :
- `Portfolio.fee_pct` (defaut `0.001`, soit 0,1% — taux taker Binance standard), configurable par instance via `RiskConfig.fee_pct` et le formulaire du dashboard (`f_fee_pct`).
- `Position.entry_fee` : le frais est deduit du cash **a l'achat** (ouverture de lot) et a nouveau **a la vente** (cloture de lot) ; le P&L d'un trade cloture est donc net des deux frais.
- `Portfolio.total_fees_paid` : cumul de tous les frais payes par l'instance, affiche dans le dashboard ("Frais payes (cumules)") et en fin de backtest CLI.
- Valide par `control_server.build_config` : `fee_pct` doit etre une fraction plausible (rejet si absurde).

### 3.14 Garde-fou anti-accumulation de pertes (EF-23)

**Contexte** : §3.12 a demontre que le multi-positions peut accumuler des pertes correlees (-34,68% avec 5 lots contre +5,21% avec 1 seul). Ce garde-fou attenue ce risque sans desactiver le multi-positions.

**Changements** :
- `RiskConfig.block_buy_if_any_position_losing` (defaut `True`) : si au moins une position ouverte de l'instance est actuellement en perte (prix courant < prix d'entree), tout nouveau signal d'achat est rejete, meme si `max_concurrent_positions` le permettrait.
- `RiskManager.validate()` et `explain_rejection()` prennent desormais `open_positions: list[Position] | None` et `current_price: float | None` en parametres nommes (**changement d'API cassant** par rapport a l'ancien `position=` unique — repercute dans tous les appelants et les tests).
- `Engine._decide()` transmet la liste des positions ouvertes et le prix courant a chaque appel de validation.

Ce garde-fou est actif par defaut (contrairement au multi-positions lui-meme) car il ne restreint que l'aggravation d'une situation deja perdante — le cout d'un faux positif (rater une opportunite pendant qu'une autre position est temporairement en perte) est juge acceptable face au risque demontre en §3.12.

### 3.15 Stop suiveur / trailing stop (EF-24)

**Changements** :
- `Position.peak_price` : le plus haut prix observe depuis l'ouverture du lot, mis a jour a chaque bougie par `Engine._decide()`.
- `RiskConfig.trailing_stop_pct` (optionnel, defaut `None` — desactive) : si defini, `RiskManager.should_trailing_stop(position, current_price)` retourne vrai des que le prix redescend de plus de `trailing_stop_pct` sous `peak_price`.
- Le stop suiveur est verifie **independamment** du stop-loss fixe et du take-profit, par lot, dans la meme boucle que §3.12 — le premier seuil atteint declenche la cloture.
- Valide par `control_server.build_config` : `trailing_stop_pct` doit etre une fraction entre 0 et 1 exclus si fourni.

### 3.16 Persistance de l'historique entre redemarrages (EF-25)

**Avant** : `Portfolio.trade_history`, `realized_pnl`, `total_fees_paid` et `equity_curve` n'existaient qu'en memoire — un redemarrage d'instance (mise a jour de config, crash, reboot machine) remettait ces compteurs a zero, alors que la base SQLite conservait deja les trades individuels sans les recharger dans l'objet `Portfolio` au demarrage.

**Changements** :
- `TradeLogger` gagne une table `closed_trades` et trois methodes : `log_closed_trade(trade)`, `load_closed_trades()`, `load_equity_curve(limit=500)`.
- `Portfolio.on_trade_closed` : callback invoque a chaque cloture de trade (branche sur `logger.log_closed_trade` dans `run_paper.py`), decouplant `Portfolio` de la persistance (le portefeuille reste testable sans base).
- Au demarrage (`run_paper.py`) : `trade_history`, `realized_pnl` et `total_fees_paid` sont reconstruits a partir de `load_closed_trades()` ; `_next_lot_id` reprend a `max(lot_id) + 1` pour eviter toute collision d'identifiant avec les lots d'avant redemarrage ; `equity_curve` est rechargee via `load_equity_curve()`.
- **Limite connue heritee de §7** : `flatten_on_start` continue de liquider toute position ouverte au demarrage, ce qui ajoute un trade de cloture "administratif" a l'historique desormais persistant — a garder en tete en lisant le win rate apres plusieurs redemarrages rapproches.

### 3.17 Validation out-of-sample de l'optimizer (EF-26)

**Avant (CT-07 de la STB)** : `optimize.py` cherchait la meilleure combinaison de parametres sur l'integralite des 3 ans d'historique, puis rapportait sa performance sur ces memes donnees — aucune garantie que le resultat se generalise a des donnees futures (surapprentissage non detecte).

**Changements** :
- `split_train_test(candles, train_ratio=0.7)` : decoupe **chronologique** (jamais un melange aleatoire, qui creerait une fuite d'information du futur vers le passe) — 70% entrainement, 30% test, sans chevauchement.
- La recherche sur grille (`build_sma_cross_candidates`, `build_scalp_dip_candidates`) s'execute uniquement sur la partie entrainement.
- Les `TOP_N_FOR_VALIDATION = 15` meilleurs candidats en entrainement sont ensuite rejoues sur la partie test seule, produisant un `ValidatedResult(symbol, candidate, train, test)`.
- Le classement final et la config ecrite en sortie sont bases sur la performance **test**, pas entrainement — un candidat excellent en entrainement mais mediocre en test est ecarte.
- Avertissement automatique si `test_return < train_return / 2` (signature typique de surapprentissage).

**Resultat empirique (test reel effectue)** : sur DOGE/USDT, le meilleur candidat en entrainement (`sma_cross`, court=20, long=100) :

| Periode | Rendement |
|---|---|
| Entrainement (in-sample) | **+23,06 %** |
| Test (out-of-sample) | **+0,15 %** |

**Enseignement (CT-09 de la STB)** : un rendement in-sample spectaculaire ne presage quasiment rien de la performance future — ce candidat aurait ete choisi par l'ancienne version de l'outil en croyant a un gain de +23%, pour finalement ne quasiment rien produire hors de la periode d'entrainement. La validation out-of-sample est donc une garde-fou indispensable, pas un raffinement optionnel.

### 3.18 Persistance des positions ouvertes (EF-27)

**Contexte** : §3.16 (EF-25) a rendu persistants l'historique des trades **clotures** et la courbe de capital, mais pas les positions **encore ouvertes** au moment d'un arret. Or `flatten_on_start` (§3.7) liquide systematiquement toute position au demarrage — ce qui etait initialement une protection utile (nettoyer un solde de test residuel), devient un probleme des que l'arret n'est pas volontaire : une extinction du PC ou un crash forcait la vente de la position en cours au redemarrage suivant, meme si rien ne le justifiait cote strategie.

**Changements** :
- Nouvelle table SQLite `open_positions` (`TradeLogger.save_open_positions()` / `load_open_positions()`) : `DELETE` + reinsertion complete a chaque appel — ce n'est pas un journal d'evenements comme `closed_trades`, mais un **snapshot** de l'ensemble exact des lots ouverts a l'instant T (quantite, prix d'entree, timestamp d'entree, frais d'entree, plus haut atteint pour le trailing stop).
- Le snapshot est sauvegarde apres chaque bougie traitee dans `run_paper.py` (meme frequence que `log_equity`), et une premiere fois juste apres l'initialisation — pour qu'une coupure survenant avant meme la premiere bougie ne laisse pas un etat `open_positions` perime d'une session precedente.
- `run_paper.restore_persisted_state(portfolio, logger)` (extrait de `main()` pour rester testable, ENF-07) recharge `trade_history`, `equity_curve` et les positions ouvertes, et retourne un booleen `is_first_ever_run` : `True` seulement si les trois sont vides (aucune trace d'une session anterieure). `flatten_existing_position()` (§3.7) n'est desormais appelee que si `is_first_ever_run` est vrai **et** `flatten_on_start` est active en config — a partir de la 2e session, la position restauree est conservee telle quelle.
- Comme pour le multi-positions (§3.12), la position "devinee" par `PaperExecutor._load_portfolio_from_exchange()` a partir du solde reel de l'exchange est **ignoree** des qu'un etat persiste existe : plusieurs bots partagent le meme compte testnet, cette estimation naive pourrait sinon attribuer a une instance le solde d'une autre. L'historique SQLite propre a l'instance reste l'unique source de verite.
- `run_paper.compute_restored_cash(capital_allocated, realized_pnl, positions)` : le cash n'est **pas** persiste directement en base (aucune table dediee), il est reconstruit a chaque demarrage a partir de trois valeurs deja disponibles : `capital_allocated + realized_pnl - immobilise`, ou `immobilise = somme(quantite x prix d'entree + frais d'entree)` sur les positions restaurees. Cette relation est exacte car `Portfolio.apply_fill()` calcule deja le P&L d'un trade cloture net des deux frais (entree et sortie) — voir §3.13 — donc `realized_pnl` capture integralement l'effet des trades termines sur le cash, et il ne reste qu'a soustraire ce qui est encore bloque dans les lots en cours.
- **Limite assumee (CT-10 de la STB)** : cette reconstruction suppose `capital_allocated` inchange depuis l'ouverture des positions restaurees. Modifier ce champ via le formulaire "Modifier un bot" pendant qu'une position est ouverte produirait un cash incoherent au prochain redemarrage — a eviter en pratique (modifier uniquement une instance a plat).

**Resultat verifie** : test d'integration relancant `restore_persisted_state` sur une instance ayant une position ouverte persistee — la position (quantite, prix d'entree, `peak_price`) est retrouvee a l'identique et le cash reconstruit correspond exactement au calcul attendu (voir `tests/test_restore_persisted_state.py`).

### 3.19 Graphique du cours reel avec achats/ventes superposes (EF-28)

**Avant** : le dashboard affichait une "courbe de capital" (`equity_curve`, en devise du capital alloue). Retour utilisateur : peu lisible et peu utile au quotidien — elle mele l'effet du prix du marche et l'effet des decisions de la strategie (taille de position, frais), sans montrer OU se sont faits les achats/ventes par rapport au marche reel.

**Changements** :
- Nouveau suivi `price_history` (paires `[timestamp, close]`, les ~200 dernieres bougies) tenu en memoire dans `run_paper.py`, alimente par `warm_up_strategy()` (pour ne pas partir d'un graphique vide au demarrage, comme pour l'historique de la strategie) puis a chaque bougie traitee dans la boucle principale. **Non persiste en base** (contrairement a `equity_curve`/`open_positions`) : c'est un contexte visuel de confort, reconstitue en quelques minutes apres un redemarrage, pas une donnee de gestion du risque.
- `write_dashboard()` expose desormais `price_history` au lieu de `equity_curve` dans le JSON envoye au navigateur (le champ backend `Portfolio.equity_curve` continue d'exister et d'etre persiste - §3.16 - il sert toujours au calcul du drawdown et a la detection de reprise de session, §3.18 ; seul l'affichage change).
- Cote dashboard (JS), `priceChartSvg(points, orders)` remplace `equitySparklineSvg()` : trace la courbe du prix reel, puis superpose pour chaque position (ouverte ou fermee, issue de la meme table `orders` que le tableau detaille du §3.11) une barre horizontale allant du moment de l'achat au moment de la vente (ou "maintenant" si encore ouverte), au niveau du prix d'achat - verte si la position est gagnante, rouge si perdante (pour une position encore ouverte, le signe est calcule par rapport au dernier prix connu). Un point vert marque l'achat, un point rouge la vente.
- **Piege evite** : le domaine temporel du graphique est cale UNIQUEMENT sur `price_history` (fenetre recente), pas sur les timestamps des trades. Une position clue bien avant cette fenetre etirerait sinon l'axe des temps et ecraserait la courbe de prix reelle dans un coin du graphique (bug observe et corrige avant mise en production, voir le commentaire dans `priceChartSvg`) ; les trades qui debordent de la fenetre visible sont rognes a ses bornes plutot qu'exclus, pour ne pas perdre l'information qu'une position etait deja ouverte.

**Extension (EF-29) : axes gradues et selecteur de periode.**

- `priceChartSvg` trace desormais 5 graduations verticales (prix) et 6 horizontales (temps) avec valeurs formatees : le prix s'adapte a l'ordre de grandeur de la crypto (`formatAxisPrice` : 0 decimale au-dessus de 1000, jusqu'a 6 en dessous de 0.01 - une paire comme DOGE/USDT et une comme BTC/USDT n'ont pas du tout la meme echelle de prix) ; le temps s'adapte a l'etendue couverte (`formatAxisTime` : heure:minute sous 2 jours, jour/mois sous 3 mois, mois/annee sous 3 ans, sinon l'annee seule).
- Un selecteur (`Live`, `1h`, `1j`, `1mois`, `1an`, `5ans`, `10ans`) permet de changer la fenetre affichee. `Live` reste le comportement du §3.19 initial (donnees en memoire du bot, granularite native de son timeframe de trading). Les autres periodes appellent une nouvelle route `GET /api/price-history?symbol=...&range=...` sur le Control Server (§3.6, §10), qui traduit chaque periode en `(timeframe, limite)` ccxt (ex. `5ans` -> bougies hebdomadaires x260) et retourne des paires `[timestamp, close]`.
- **Choix de source** : cette route interroge le marche **SPOT reel** de Binance (`ccxt.binance()`, endpoints publics, sans cle API), pas le testnet utilise pour le trading - l'historique du testnet est trop court pour couvrir "5 ans"/"10 ans". C'est une donnee de contexte visuel uniquement (comparer les decisions du bot au marche reel), elle n'influence jamais une decision de trading (qui reste basee sur le testnet, coherent avec EF-04/ENF-02).
- Resultat mis en cache serveur (`_price_history_cache`, 60s par `(symbole, periode)`) pour eviter de re-interroger l'exchange a chaque clic ou a chaque bot ouvert sur la meme paire ; mis en cache aussi cote navigateur (`historicalPriceCache`, meme duree) pour survivre au rafraichissement automatique du dashboard (15s) sans reclencher un fetch a chaque fois.
- Fonction pure et testable : `fetch_price_history(symbol, range_key, exchange=None)` accepte un exchange injecte (tests) au lieu du client ccxt reel, meme pattern que `PaperExecutor` (STC §3.4).

### 3.20 Filtre de tendance (EF-30) — étape 1 de la feuille de route performance

**Contexte** : suite a l'analyse de la performance des bots (voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md), premier axe d'amelioration identifie : `sma_cross` peut whipsaw en marche plat, `scalp_dip` peut acheter des creux pendant une chute continue ("catching a falling knife"). Un filtre de regime de marche vise a limiter ces achats a contre-courant.

**Changements** :
- Nouveau composant `analysis/trend_filter.py` : `TrendFilter(ema_period=200)` calcule une moyenne mobile exponentielle en O(1) par bougie (`update(price)`), et expose `is_bullish(current_price)` (vrai si le prix est au-dessus de l'EMA). **Fail-open** avant que l'EMA n'ait recu sa premiere bougie (ne bloque rien tant qu'elle n'est pas formee), comme `ProbabilityGate`.
- Contrairement a `ProbabilityGate` (qui a besoin d'un fetch reseau + simulation Monte Carlo), `TrendFilter` ne consomme que les bougies deja recues par le moteur - il fonctionne donc **aussi bien en backtest qu'en paper trading**, ce qui a permis le backtest comparatif chiffre exige par la feuille de route (contrairement au filtre de probabilite, jamais backteste a ce jour).
- `Engine` gagne un parametre optionnel `trend_filter` : mis a jour a **chaque** bougie (`process_candle`, avant `_decide`), qu'il y ait un signal ou non - necessaire pour que l'EMA reste a jour meme sans achat. Le blocage est verifie dans `_handle_buy_signal`, avant meme le filtre de probabilite.
- Configuration YAML optionnelle `trend_filter: {enabled: bool, ema_period: int}`, meme structure que `probability_filter` (§EF-18). Desactive par defaut - aucune instance existante n'est affectee tant qu'elle n'active pas explicitement le filtre.
- `warm_up_strategy()` alimente aussi le `TrendFilter` (si fourni) pendant le rechauffement, et **etend automatiquement le nombre de bougies recuperees** au maximum entre `warmup_candles` et `ema_period` - sans ca, l'EMA serait "a froid" (aucun historique) au tout premier signal d'achat possible d'une instance fraichement lancee.
- `control_server.build_config()` : nouveaux champs formulaire `trend_filter_enabled` / `trend_filter_ema_period` (valide >= 2), meme pattern que le filtre de probabilite. Dashboard : nouvelle statistique "Regime de tendance (EMAxxx)" (Haussier/Baissier/en formation).
- `run_backtest.py` gagne `build_trend_filter(config)` pour permettre le backtest comparatif (le filtre de probabilite n'a pas cet equivalent a ce jour - limite connue, hors perimetre de cette etape).

**Resultat empirique (backtest comparatif, 2024-01-01 -> aujourd'hui, donnees Binance reelles)** :

| Scenario | Sans filtre | Avec filtre EMA50 |
|---|---|---|
| BTC/USDT `sma_cross` (config `btc_sma_cross_v1`) | -6,45 % (DD 10,21%, 471 trades) | -1,45 % (DD 6,33%, 324 trades) |
| DOGE/USDT `scalp_dip`, 5 positions simultanees (config `doge_scalp_v1`, cas CT-08) | -434,58 % (DD 434%, 10310 trades) | -65,98 % (DD 68,29%, 1683 trades) |
| DOGE/USDT `scalp_dip`, 1 position | -222,69 % (DD 222,77%, 5508 trades) | -41,92 % (DD 43,22%, 1028 trades) |

**Enseignement (CT-11 de la STB)** : le filtre reduit systematiquement le nombre de trades (÷4 a ÷6) et le drawdown dans les 3 scenarios, mais ne transforme pas automatiquement une strategie sans edge en strategie gagnante - avec des parametres par defaut arbitraires, `sma_cross` et `scalp_dip` restaient negatifs sur cette periode reelle, filtre ou non. Le backtest a aussi revele une limite preexistante et non liee au filtre : `size_for_signal` dimensionne chaque achat sur le capital de depart FIXE (choix assume du multi-positions, §3.12), pas sur le cash reellement disponible - sur un test tres long avec une strategie durablement perdante, le cash simule peut devenir tres negatif (rendements DOGE au-dela de -100%), ce qu'un exchange reel empecherait par rejet d'ordre. La comparaison RELATIVE avec/sans filtre reste valide malgre cette limite ; les pourcentages absolus des scenarios DOGE ne doivent pas etre pris au pied de la lettre.

**Suite : integration a l'optimizer (§3.10) - premier edge positif mesure (CT-12 de la STB).** Plutot que de s'arreter sur des parametres par defaut, `optimize.py` a ete etendu pour tester le filtre de tendance (EMA50/100/200 ou desactive) comme dimension supplementaire de sa grille, avec la meme methodologie out-of-sample (§3.10, EF-26). Resultat sur BTC/USDT + DOGE/USDT (3 ans, 480 combinaisons par paire) : les 4 meilleures configs classees par performance de VALIDATION utilisent toutes le filtre de tendance (EMA100 ou EMA200), et pour la premiere fois le rendement de validation est **positif** (DOGE/USDT sma_cross(20,100)+EMA200 : +1,83% en validation ; BTC/USDT sma_cross(15,100)+EMA200 : +0,14% en validation). Modeste, et l'ecart entrainement/validation (+25% vs +1,83%) reste un signal de surapprentissage a surveiller - mais c'est la premiere fois que la methodologie out-of-sample de ce projet produit un edge mesure plutot qu'une simple reduction de perte.

### 3.21 Sizing par volatilite (EF-31) — étape 2 de la feuille de route performance

**Objectif** : une taille de position fixe (`max_position_size_pct` du capital) prend le meme risque EN VALEUR quel que soit l'etat du marche. Reduire la taille quand la volatilite recente est elevee vise a prendre un risque plus constant, sans jamais depasser le plafond configure.

**Changements** :
- Nouveau composant `analysis/atr_sizer.py` : `AtrSizer(atr_period=14, baseline_period=100, min_size_multiplier=0.2)`. Calcule le True Range (`max(high-low, |high-close_precedent|, |low-close_precedent|)`) a chaque bougie, lisse en deux EMA imbriquees : une reactive (`atr`, periode courte) et une de reference (`baseline`, periode longue) qui represente le niveau de volatilite "habituel". `size_multiplier()` retourne `baseline/atr` borne a `[min_size_multiplier, 1.0]` - **ne peut jamais depasser 1.0** (jamais plus que le plafond normal), seulement le reduire quand la volatilite courante depasse sa reference.
- `RiskManager.size_for_signal()` gagne un parametre optionnel `size_multiplier` (defaut `1.0`, comportement historique inchange). `Engine` calcule `atr_sizer.size_multiplier()` avant chaque achat et le transmet.
- Meme integration que `TrendFilter` (§3.20) : mis a jour a chaque bougie (`process_candle`), fail-open avant formation, warmup etendu (`warm_up_strategy` couvre aussi `baseline_period`), configuration YAML optionnelle `atr_sizing: {enabled, atr_period, baseline_period, min_size_multiplier}`, formulaire dashboard, validation `control_server`. Fonctionne en backtest ET paper trading (pas de dependance reseau), comme `TrendFilter` et contrairement a `ProbabilityGate`.

**Resultat empirique (backtest comparatif, memes configs que l'etape 1 + une config a risque connu)** :

| Scenario | Sizing fixe | Sizing ATR |
|---|---|---|
| DOGE/USDT sma_cross(20,100)+EMA200 (meilleure config etape 1) | +26,89 % (DD 6,86%) | +24,22 % (DD 6,87%) |
| BTC/USDT sma_cross(15,100)+EMA200 (meilleure config etape 1) | +9,23 % (DD 2,65%) | +7,23 % (DD 2,47%) |
| DOGE/USDT scalp_dip, 5 positions (config `doge_scalp_v1`, cas CT-08) | -434,58 % (DD 434,03%) | **-378,48 % (DD 378,70%)** |

**Enseignement (CT-13 de la STB), different de l'etape 1** : contrairement au filtre de tendance (gain net dans tous les scenarios testes), le sizing ATR a un effet MITIGE. Sur les 2 configs deja rentables de l'etape 1, il reduit legerement le rendement sans reduire significativement le drawdown - il freine la taille pendant TOUTE periode volatile, y compris les mouvements profitables, pas seulement les mauvais. Sur la config a risque connu (accumulation multi-positions), il attenue la perte et le drawdown d'environ 13% - un effet reel mais qui traite un symptome deja mieux couvert par le garde-fou anti-accumulation (EF-23) et le filtre de tendance. Decision : reste optionnel et desactive par defaut, a activer au cas par cas plutot que systematiquement sur toute instance.

### 3.22 Sortie partielle / scale-out (EF-32) — étape 3 de la feuille de route performance

**Objectif** : actuellement une position se ferme ENTIEREMENT au premier seuil atteint (stop-loss, take-profit ou trailing stop) - EF-24/§3.15 documentait deja le trailing stop comme protection des gains, mais rien ne permettait de securiser PARTIELLEMENT un gain tot tout en laissant le reste de la position courir.

**Changements** :
- `Portfolio.apply_fill()` : la branche SELL detecte desormais si `order.quantity < position.quantity` (marge flottante `1e-12`) - si oui, c'est une **sortie partielle** : le lot n'est PAS retire de `positions`, seule sa `quantity` est reduite, et son `entry_fee` est repartit au PRORATA de la fraction vendue (`entry_fee_share = entry_fee * (order.quantity / position.quantity)`) pour que le P&L de la portion vendue ET de la portion restante restent tous deux corrects - sans ce partage, la portion restante se verrait facturer un frais d'entree qu'elle ne "doit" plus. Un dict `trade` est ajoute a `trade_history` comme pour une cloture complete, avec un marqueur `"partial": True` en plus.
- `Position` gagne `partial_exit_done: bool = False` - empeche une 2e sortie partielle sur le meme lot (le palier ne se declenche qu'une fois ; le reste suit ensuite le stop-loss/trailing stop existant jusqu'a fermeture complete).
- `RiskConfig` gagne `partial_take_profit_pct` (optionnel, defaut `None` = desactive) et `partial_exit_fraction` (defaut `0.5`). `RiskManager.should_partial_take_profit(position, current_price)` suit le meme patron que `should_take_profit`/`should_trailing_stop`.
- `Engine._decide()` : la sortie partielle est verifiee en DERNIER dans la chaine `elif` des sorties par lot (apres stop-loss, take-profit, trailing stop) - une sortie complete a toujours priorite si plusieurs conditions sont vraies le meme cycle. `Engine._partial_close_position()` calcule la quantite a vendre (`position.quantity * partial_exit_fraction`) et passe par le meme `_place_order` que les autres sorties.
- `control_server.build_config()` : nouveau couple de champs `partial_take_profit_pct`/`partial_exit_fraction`, avec une regle de coherence - **le palier partiel doit etre strictement inferieur au take-profit complet** s'il est aussi configure (sinon le take-profit complet se declencherait toujours en premier, rendant le palier partiel inatteignable).

**Resultat empirique (backtest comparatif, memes configs que les etapes 1/2)** :

| Scenario | Sortie complete | Sortie partielle |
|---|---|---|
| DOGE/USDT sma_cross(20,100)+EMA200 | +26,89 % (DD 6,86%) | +11,79 % (DD 4,61%) — palier 3% → 50% |
| BTC/USDT sma_cross(15,100)+EMA200 | +9,23 % (DD 2,65%) | +4,90 % (DD 2,11%) — palier 3% → 50% |
| DOGE/USDT scalp_dip (config `doge_scalp_v1`, 1 position) | -222,69 % (DD 222,77%) | -226,08 % (DD 226,22%) — palier 0,5% → 50% |

**Enseignement (CT-14 de la STB), encore different des etapes 1 et 2** : ni un gain net (etape 1), ni un effet mitige mineur (etape 2) - la sortie partielle est un **vrai compromis risque/rendement**. Sur les strategies trend-following deja rentables, elle reduit le drawdown de 30-35% mais divise le rendement par ~2 : securiser la moitie du gain tot coupe dans les grandes tendances qui font l'essentiel du profit d'une strategie qui suit la tendance. Sur une config deja perdante, l'effet est legerement negatif sans compensation. Decision : reste optionnelle et desactivee par defaut, a proposer comme option pour un profil plus prudent plutot qu'a activer systematiquement.

### 3.23 Bot d'auto-reoptimisation periodique (EF-33) — étape 5 de la feuille de route performance

**Objectif** : automatiser la re-execution de `optimize.py` au fil du temps pour qu'une instance s'adapte aux conditions de marche changeantes, sans figer indefiniment ses parametres sur ce qui a ete trouve une seule fois a la creation.

**Risque identifie avant conception (discute avec l'utilisateur, voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md)** : un re-optimiseur naif qui prend systematiquement "le meilleur du jour" changerait de config en permanence en poursuivant du bruit statistique, sans jamais laisser une config assez longtemps en paper trading pour etre validee reellement ("config-shopping"). Les 4 garde-fous ci-dessous ne sont pas des options, ce sont des contraintes de conception.

**Changements** :
- Nouveau module `reoptimizer.py`, qui **reutilise integralement** `optimize.py` (memes fonctions : `build_sma_cross_candidates`, `build_scalp_dip_candidates`, `split_train_test`, `run_one_backtest`, `TOP_N_FOR_VALIDATION`, `format_candidate`, `result_to_config_yaml`) - aucune nouvelle logique de backtest, seulement une orchestration ciblee sur UNE instance a la fois plutot qu'une grille exploratoire sur plusieurs paires.
- **Garde-fou 1 (validation out-of-sample obligatoire)** : `is_better_out_of_sample(current, candidate)` - un candidat ne devient une proposition QUE s'il bat la config ACTUELLEMENT DEPLOYEE sur sa performance de VALIDATION (jamais vue pendant la recherche), jamais sur sa seule performance d'entrainement. `candidate_from_config()` reconstruit un `Candidate` a partir de la config YAML deployee, pour la re-backtester avec EXACTEMENT le meme decoupage train/test que les nouveaux candidats - comparaison equitable, pas un chiffre recycle d'un ancien rapport.
- **Garde-fou 2 (frequence lente)** : `is_due_for_reoptimization(last_checked_at, now, interval_days=30)` - 30 jours par defaut entre deux verifications, meme si aucune proposition n'en resulte (l'etat `last_checked_at` avance dans tous les cas, y compris "no_improvement" - sinon le garde-fou ne servirait a rien, on re-testerait a chaque appel). Etat persiste dans `proposals/reoptimize_state.json` (cle = nom de l'instance).
- **Garde-fou 3 (jamais sur position ouverte)** : `has_open_position(name)` relit la table `open_positions` (EF-27, §3.18) de l'instance - coherent avec CT-10 de la STB (modifier la config d'une instance a position ouverte rendrait le cash reconstruit incoherent au redemarrage). Verifie DEUX fois : une fois par `propose_reoptimization()` avant de chercher un candidat, une seconde fois par `control_server._handle_apply_proposal()` au moment d'appliquer (l'etat a pu changer entre la proposition et la decision de l'utilisateur).
- **Garde-fou 4 (semi-automatique - l'humain valide)** : le resultat est ecrit dans `proposals/{nom}_proposal.json` (comparaison lisible actuel vs propose) et `proposals/{nom}_proposed_config.yml` (config prete a l'emploi) - **rien n'est ecrit dans `config/`, rien n'est redemarre**. Nouvelles routes sur le Control Server : `GET /api/list-proposals` (liste les propositions en attente), `POST /api/apply-proposal` (n'ecrase que `strategy`/`risk`/`trend_filter` du fichier de config existant - conserve `capital_allocated`/`warmup_candles`/`flatten_on_start` deja choisis par l'utilisateur pour cette instance - puis arrete/relance le bot s'il tournait), `POST /api/dismiss-proposal` (supprime la proposition sans y toucher). Section "Propositions de reoptimisation" ajoutee dans l'onglet "Gerer les bots" du dashboard, avec boutons Appliquer/Rejeter.
- **Limite resolue le 2026-09-12** : le module lui-meme ne planifie rien (pas de boucle/thread interne) - `run_reoptimizer_weekly.bat` (`.venv/Scripts/python.exe -m tradingbot.reoptimizer --all`, journalise dans `logs/reoptimizer_weekly.log`) est desormais invoque chaque semaine par une tache planifiee Windows (`TradingBot-Reoptimizer-Weekly`, vendredi 3h). Coherent avec le principe "semi-automatique pour commencer" - le declenchement est externe au code, mais bien reel desormais plutot que suppose.

**Resultat verifie (test manuel en conditions reelles)** : `python -m tradingbot.reoptimizer --name btc_sma_cross_v1` a produit une proposition reelle - config deployee (`sma_cross` court=10, long=30) a -1,92% en validation out-of-sample, candidat propose (`sma_cross` court=15, long=100, filtre de tendance EMA200 - la config gagnante de l'etape 1, §3.19/§3.20) a +0,14%. Proposition confirmee visible et actionnable dans le dashboard via navigateur (voir CT-15 de la STB pour le detail).

**Extension (EF-34, EF-35) : bouton "tout reoptimiser", sizing ATR, frequence hebdomadaire, test A/B.**

- **Sizing ATR dans la grille** : `optimize.py` gagne `ATR_SIZING_OPTIONS = [False, True]` (on/off avec les parametres par defaut `DEFAULT_ATR_PERIOD=14`/`DEFAULT_ATR_BASELINE_PERIOD=100`/`DEFAULT_ATR_MIN_MULTIPLIER=0.2`, pas une grille fine de periodes ATR - le resultat de l'etape 2, §3.21, etait deja mitige, inutile d'explorer finement ses propres hyperparametres). `Candidate.atr_sizing_enabled` s'ajoute a `trend_filter_ema_period` comme dimension croisee dans `build_sma_cross_candidates`/`build_scalp_dip_candidates` - la grille passe de 480 a **960 combinaisons par paire**. `run_one_backtest` construit un `AtrSizer` quand active, `format_candidate`/`result_to_config_yaml` refletent la nouvelle dimension.
- **Frequence portee a 7 jours** : `REOPTIMIZE_INTERVAL_DAYS` passe de 30 a 7 - au moins une verification par semaine par instance, comme demande par l'utilisateur.
- **`run_all()`** traite tous les bots connus (`control_server.list_known_configs()`) en une fois : genere une proposition pour chacun (memes garde-fous que `propose_reoptimization` pour une seule instance), puis applique immediatement celles du groupe "auto" (voir ci-dessous). Nouvelle route `POST /api/reoptimize-all` : lance `run_all()` dans un thread daemon et repond immediatement (`{"status": "lance"}`) - le traitement de plusieurs bots a 960 combinaisons chacune peut prendre plusieurs minutes, incompatible avec une reponse HTTP synchrone. Nouveau bouton dashboard "Lancer la reoptimisation de tous les bots" dans l'onglet "Gerer les bots", au-dessus de la liste des propositions (qui se rafraichit toutes les 15s et affiche donc les resultats au fil de l'eau).
- **Test A/B (EF-35)** : `assign_groups(names)` assigne chaque bot connu a un groupe `"auto"` ou `"control"`, de facon **stable** (un bot deja assigne garde son groupe a chaque appel - sinon le test A/B perd tout son sens) et **equilibree** (alternance sur les nouveaux bots pour maintenir les deux groupes a taille comparable). Persiste dans `proposals/ab_test_groups.json`, nettoye des bots supprimes a chaque appel. Dans `run_all()` :
  - groupe **"control"** : la proposition est ecrite comme d'habitude, jamais appliquee - sert de reference pour mesurer l'effet reel de l'auto-reoptimisation par comparaison avec le groupe "auto" au fil du temps.
  - groupe **"auto"** : `apply_proposal_files(name)` est appele immediatement des qu'une proposition est trouvee - **PAS d'attente de validation humaine**. C'est le seul endroit du projet ou ce garde-fou (EF-33, point 4) est delibierement leve, a la demande explicite de l'utilisateur et uniquement parce que le systeme tourne en paper trading (CT-16 de la STB) - les deux autres garde-fous (validation out-of-sample, absence de position ouverte) restent actifs sans exception pour les deux groupes.
- **`apply_proposal_files(name)`** et **`merge_proposal_into_config(original, proposed)`** sont extraits en fonctions reutilisables : le meme code gere l'application manuelle (`control_server._handle_apply_proposal`, dashboard) ET l'application automatique du groupe auto (`run_all`) - evite que les deux chemins divergent. Conserve `capital_allocated`/`warmup_candles`/`flatten_on_start` de la config existante ; revérifie l'absence de position ouverte au moment d'appliquer (l'etat a pu changer depuis la generation de la proposition). **Corrige le 2026-09-12 (CT-19 de la STB)** : ne copie de la proposition QUE `strategy`/`trend_filter`/`atr_sizing` et les champs de `risk` reellement varies par la grille de `optimize.py` (`stop_loss_pct`, `take_profit_pct` - via `RISK_KEYS_FROM_PROPOSAL`) - le reste du bloc `risk` (notamment `max_position_size_pct`, `max_concurrent_positions`, jamais varies par la grille et absents de sa recherche) reste celui deja choisi pour l'instance. Avant ce correctif, `merged["risk"] = proposed_config["risk"]` remplacait tout le bloc et ecrasait silencieusement un sizing choisi manuellement des qu'une proposition etait appliquee automatiquement (constate en conditions reelles sur 3 bots du groupe "auto" le jour meme).
- `control_server._kill_by_name` extrait en fonction module-level `kill_by_name()`, reutilisee par `reoptimizer.apply_proposal_files` (evite un cycle d'import en import differe dans la fonction).

**Resultat verifie (test manuel en conditions reelles)** : bouton "Lancer la reoptimisation de tous les bots" declenche sur les 8 bots en cours d'execution - voir le detail des propositions/applications generees dans le manuel utilisateur et la feuille de route.

---

### 3.24 Garde-fous anti-"config-shopping" (EF-38, EF-39) — étape 6 de la feuille de route performance

**Declencheur** : une simulation retrospective "walk-forward" (rejeu des 6 derniers mois avec le reoptimiseur hebdomadaire reellement actif a chaque checkpoint de 7 jours, meme grille et meme validation que la vraie tache planifiee) a montre que les 9 reoptimisations appliquees degradaient le resultat net de -46,11 sur la periode par rapport a des parametres figes - chaque candidat battait bien la config actuelle sur son score de validation AU MOMENT de la decision, mais le marche avait deja change de regime la semaine suivante (CT-20 de la STB). Le garde-fou existant ("candidat > actuel", EF-33) ne protegeait pas contre un ecart minuscule (parfois < 0,1 point) qui n'est que du bruit statistique lie au deplacement de la fenetre glissante.

**Deux nouveaux garde-fous, tous deux dans `reoptimizer.py`** :

1. **Marge d'amelioration minimale (EF-38)** : `is_better_out_of_sample(current, candidate, min_margin=MIN_IMPROVEMENT_MARGIN)` exige desormais `candidate.total_return_pct > current.total_return_pct + min_margin` au lieu d'un simple `>`. `MIN_IMPROVEMENT_MARGIN = 0.005` (0,5 point de rendement de validation) par defaut, parametrable pour les tests. Une regression aurait ete detectee par 5 des 9 changements appliques dans la simulation retrospective (ecarts mesures souvent inferieurs a ce seuil).
2. **Exigence de battre un buy & hold (EF-39)** : `has_edge_over_benchmark(result)` refuse un candidat dont `result.beats_benchmark is False` - permissif (`True`) si le benchmark n'a pas pu etre calcule (periode trop courte), pour ne jamais bloquer sur une donnee manquante. Combine a `is_better_out_of_sample` dans `propose_reoptimization` : `if not is_better_out_of_sample(...) or not has_edge_over_benchmark(...): return {"status": "no_improvement", ...}`.

**Le benchmark buy & hold lui-meme** vit dans `reporting/stats.py::compute_buy_and_hold_return_pct(candles)` - rendement d'un simple achat au premier prix de la periode, conserve jusqu'au dernier, sans aucune strategie. Integre directement dans `optimize.py::BacktestResult` (nouveau champ `benchmark_return_pct`, propriete `beats_benchmark`) et calcule automatiquement par `run_one_backtest` sur les MEMES bougies que le backtest - reutilise donc par `optimize.py` (affichage dans le TOP 10 et alerte si le meilleur candidat perd contre buy & hold) ET par `reoptimizer.py` sans code duplique.

**Revalidation par simulation walk-forward (2026-09-12), 3 periodes independantes** : capital deploye reduit de 44% du nombre de changements appliques sur les 6 derniers mois (9->5), sans jamais bloquer un changement dont l'ecart etait large et reel (S1 2025 : les 2 changements passent les deux filtres sans etre bloques, resultat identique a l'ancien code). **Limite confirmee empiriquement** : ces deux garde-fous reduisent le bruit mais ne suffisent pas a rendre la reoptimisation hebdomadaire nettement benefique sur la duree (6 derniers mois toujours legerement pire qu'a parametres figes, S1 2024/2025 quasi identiques au statique) - un vrai changement de regime de marche reste plus rapide que ce qu'une fenetre de validation glissante peut anticiper. Pistes encore ouvertes : selection par critere ajuste au risque, validation sur plusieurs fenetres, confirmation sur plusieurs semaines avant bascule, diversification de familles de strategies - voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md etape 6.

**Validation** : 7 nouveaux tests (`test_is_better_out_of_sample_rejects_improvement_below_minimum_margin`, `..._accepts_improvement_above_minimum_margin`, `..._custom_margin_overrides_default`, `test_has_edge_over_benchmark_*` x4) + 5 tests pour `compute_buy_and_hold_return_pct`. Suite complete : 321 tests passent.

---

### 3.25 Confirmation, selection au risque, consistance multi-fenetres, diversification (EF-40 a EF-43) — etape 6, pistes 3 a 6

**Contexte** : la revalidation de la section 3.24 a confirme que filtrer le bruit statistique (marge + benchmark) ne suffisait pas a rendre la reoptimisation hebdomadaire nettement benefique. L'utilisateur a demande de traiter les 4 pistes restantes du backlog. En parallele, sur son propre avis ("les reoptimisations ne servent a rien" au vu des resultats mesures), tous les bots ont ete repasses en groupe **"control"** dans `proposals/ab_test_groups.json` (2026-09-13) : le reoptimiseur continue de tourner chaque semaine et d'ecrire des propositions (visibilite/donnees conservees), mais **plus aucune n'est appliquee automatiquement** tant que l'effet net des 4 pistes suivantes n'est pas revalide.

1. **Confirmation sur 2 checks consecutifs (EF-40)** : `propose_reoptimization` persiste desormais `pending_candidate` (la description du candidat gagnant) dans `proposals/reoptimize_state.json` par bot. Un candidat qui bat la config actuelle pour la premiere fois retourne le statut `'pending_confirmation'` (rien n'est ecrit/applique) ; il ne devient une proposition reelle (`'proposed'`) que si le MEME candidat (meme `format_candidate()`) regagne au check hebdomadaire suivant. Tout resultat `'no_improvement'` efface la confirmation en attente (pas de blocage indefini si le marche change encore d'avis). **Bug corrige au passage** : `_print_result` ne geraatt pas ce nouveau statut et plantait sur `result['proposal']` manquant - `elif status == "pending_confirmation"` ajoute, teste (`test_print_result_handles_every_status_without_crashing`).

2. **Selection ajustee au risque (EF-41)** : `BacktestResult.risk_adjusted_return` (nouvelle propriete) = `total_return_pct / max(max_drawdown_pct, MIN_DRAWDOWN_FLOOR)` (`MIN_DRAWDOWN_FLOOR = 0.01`, evite qu'un drawdown quasi nul gonfle artificiellement le score d'un candidat teste sur peu de trades). Remplace `total_return_pct` comme critere de tri partout ou un candidat est choisi parmi plusieurs : tri des candidats d'entrainement avant validation (`optimize.py::main`, `reoptimizer._search_best_out_of_sample`), classement final du TOP 10/meilleur candidat. `is_better_out_of_sample` (comparaison candidat vs config actuelle, avec marge) reste sur `total_return_pct` - ce sont deux questions differentes : "lequel choisir parmi la grille" (risque pris en compte) vs "cet ecart est-il assez large pour justifier un changement" (marge calibree en points de rendement, pas en ratio).

3. **Consistance multi-fenetres (EF-42)** : `optimize.py::split_into_windows(candles, num_windows=3)` decoupe une periode (typiquement la validation) en sous-fenetres contigues de taille egale (le reste eventuel est fusionne dans l'avant-derniere plutot que de laisser une fenetre trop courte). `compute_window_consistency(candles, candidate, num_windows)` rejoue le MEME candidat independamment sur chaque sous-fenetre et retourne (rendements par fenetre, fraction de fenetres exploitables qui sont positives). `reoptimizer.is_consistent_across_windows(test_candles, candidate, min_consistency=MIN_WINDOW_CONSISTENCY)` (`MIN_WINDOW_CONSISTENCY = 0.5`) refuse un candidat positif sur moins de la moitie de ses sous-fenetres - permissif si aucune fenetre n'a assez de trades pour juger. Ajoute comme 3e condition dans le garde-fou de `propose_reoptimization` (avec marge minimale et benchmark). `optimize.py::main` affiche aussi la consistance du meilleur resultat en diagnostic (pas de gate cote CLI manuel, seulement une alerte imprimee).

4. **Diversification de strategie (EF-43)** : nouvelle classe `strategies/mean_reversion.py::MeanReversionStrategy` (bandes de Bollinger) - achat quand le prix casse sous la bande basse (`middle - num_std * ecart_type` sur une fenetre glissante), vente quand il revient a la bande du milieu (moyenne). Famille DIFFERENTE de `sma_cross`/`scalp_dip` (toutes deux suivi de tendance) : parie l'inverse, qu'un prix trop ecarte revient vers sa moyenne. Deliberement SANS filtre de tendance/sizing ATR croises dans sa grille (`build_mean_reversion_candidates`, `MEAN_REVERSION_WINDOWS`/`MEAN_REVERSION_NUM_STD`/`MEAN_REVERSION_STOP_LOSS_OPTIONS`, 18 combinaisons) - un filtre de tendance bloquerait precisement les achats en survente que cette strategie cherche a faire, les deux concepts sont contradictoires. Integree partout ou `sma_cross`/`scalp_dip` le sont deja : `build_strategy` (optimize.py, dispatch par `strategy_type`), `format_candidate`, `result_to_config_yaml` (warmup calcule via `params.get("window", 0)`), grille combinee de `optimize.py::main` et `reoptimizer._search_best_out_of_sample`, registre `run_backtest.STRATEGY_REGISTRY` (deployable via config YAML). **Limite assumee** : pas d'ajout au formulaire de creation du dashboard (`control_server.VALID_STRATEGIES` inchange) - un bot `mean_reversion` se cree via une config YAML generee par `optimize.py` ou ecrite a la main, comme `optimized_dogeusdt_sma_cross` l'a ete a l'origine, puis demarre via le bouton "Demarrer" d'un bot existant (qui ne repasse pas par la validation du formulaire).

**Bug reel decouvert en testant EF-43 (CT-21 de la STB)** : relancer `python -m tradingbot.optimize --symbols DOGE/USDT` pour verifier que `mean_reversion` s'integrait a la grille a silencieusement ecrase `config/optimized_dogeusdt_sma_cross.yml` - le nom auto-genere par l'outil coincidait exactement avec la config du bot LIVE du meme nom, deja tunee (etape 4quater). **Corrige** : `write_config_without_overwriting(config_name, yaml_content)` verifie si `config/{nom}.yml` existe deja et ecrit dans `config/{nom}_candidate.yml` a la place, avec avertissement explicite, plutot que d'ecraser en silence.

**Validation** : 27 nouveaux tests (confirmation sur 2 checks, `risk_adjusted_return`, `split_into_windows`/`compute_window_consistency`, `is_consistent_across_windows`, `MeanReversionStrategy` x7, dispatch/format de la nouvelle strategie, `write_config_without_overwriting`). Suite complete : 351 tests passent.

**Verification empirique de EF-43 (2026-09-13)** : recherche complete (978 combinaisons, sma_cross + scalp_dip + mean_reversion) relancee specifiquement sur les 4 paires qui n'avaient JAMAIS trouve d'edge positif avec le suivi de tendance (BNB, SOL, LINK, AVAX). Resultat honnete : `mean_reversion` n'apparait dans AUCUN des 4 classements "meilleur par type" - ses candidats n'ont meme pas atteint le top 15 a l'entrainement, la strategie est simplement moins bonne que `sma_cross` sur ces 4 paires sur cette fenetre de 3 ans. La diversification est correctement implementee et integree (memes points d'integration que les strategies existantes, testee unitairement), mais **n'a pas encore demontre le benefice espere** avec cette implementation simple (bandes de Bollinger a 2 parametres, sans filtre de regime) - reste au dela du perimetre traite ici : tester d'autres implementations de retour a la moyenne (RSI, filtre de range pour n'activer la strategie qu'en marche sans tendance), ou d'autres timeframes.

### 3.26 Market making natif (EF-44) — étape 7 de la feuille de route performance

**Contexte** : suite a une comparaison avec Hummingbot (framework open-source de trading, dont le market making est la stratégie phare), decision de s'inspirer du CONCEPT plutot que d'importer son code (abstractions incompatibles - ordres limites, carnet d'ordres, event loop dedie). Objectif : donner a la flotte un edge STRUCTUREL (capture de spread), different du suivi de tendance/retour a la moyenne (tous deux directionnels, tous deux sans edge demontre sur BNB/SOL/LINK/AVAX - voir §3.25).

**Limite structurelle assumee des la conception** : ce projet ne connait que des bougies OHLCV en cache (`data_feed.py`) et des ordres au marche executes au prix de cloture (`BacktestExecutor`/`PaperExecutor`) - ni carnet d'ordres historique, ni ordre limite qui reste en attente. Un vrai market making cote en continu bid/ask en carnet. Ici, les fills sont **simules par approximation OHLC** : bid touche si `candle.low <= bid_price`, ask touche si `candle.high >= ask_price`, en reutilisant les champs `high`/`low` deja presents dans `Candle`. C'est raisonnable en l'absence de donnees tick/L2, mais plus optimiste qu'un vrai carnet (pas de concurrence avec d'autres market makers, pas de glissement intra-bougie, pas de risque de ne jamais etre execute).

**Composants nouveaux** :
- `types.Quote(bid_price, ask_price, bid_qty, ask_qty, reason)` - un `Signal` directionnel ne peut pas exprimer "coter les deux cotes en meme temps avec des prix explicites".
- `strategies/market_making.py::MarketMakingStrategy` - **n'implemente pas l'interface `Strategy`** (`on_candle(candle) -> Signal|None`, fonction pure). Sa methode `quote(candle, inventory) -> Quote|None` depend intrinsequement de l'inventaire courant (dérogation documentee a ENF-07, necessaire ici). Parametres `spread_pct`, `order_size_quote`/`max_inventory_quote` (exprimes en devise de COTATION, pas en actif de base, pour generaliser entre symboles - 1 BTC et 1 DOGE n'ont rien a voir en valeur), `skew_factor` (recentrage : plus l'inventaire est eleve, plus bid ET ask sont abaisses, pour pousser l'inventaire vers 0 ; pas de symetrie negative, le spot ne permet pas d'etre short).
- `mm_engine.py::MarketMakingEngine` - moteur DEDIE, parallele a `Engine` plutot qu'une extension : le cycle "un seul signal directionnel par bougie" de `Engine._decide` ne correspond pas a "coter les deux cotes a chaque bougie, 0/1/2 fills possibles". Reutilise `Portfolio.apply_fill` sans aucune modification (un fill bid ouvre un nouveau lot, deja supporte par EF-21) et le flux `SharedPool` deja ecrit pour `Engine` (voir factorisation ci-dessous).
- `risk/risk_manager.py::MarketMakingConfig` - a cote de `RiskConfig`, pas une extension : ne porte que `fee_pct`/`max_daily_loss_pct` (les concepts stop-loss/take-profit/max_position_size_pct n'ont pas de sens pour du market making). **Limite assumee** : `max_daily_loss_pct` n'est pas encore applique par `MarketMakingEngine` (pas de coupe-circuit journalier implemente pour cette strategie) - a traiter si `market_making` passe un jour en paper trading reel.

**Factorisation `shared_pool.py`** : `reserve_for_buy`/`settle_or_release_buy`/`credit_for_sell` (fonctions libres) extraites du code deja ecrit dans `Engine._handle_buy_signal`/`Engine._place_order`, pour que `MarketMakingEngine` reutilise EXACTEMENT le meme protocole reserve/settle/release/credit sans dupliquer la marge de slippage (`RESERVATION_SLIPPAGE_BUFFER`) ni la mise a jour de l'allocation dynamique. `Engine` refactorise pour utiliser ces memes fonctions (comportement inchange, verifie par la suite de tests existante).

**Integration `optimize.py`** : `build_market_making_candidates()` (36 combinaisons : `spread_pct` x `order_size_quote` x `max_inventory_quote` x `skew_factor`, filtre les combinaisons ou un seul ordre depasserait le plafond d'inventaire), `run_one_backtest` bifurque vers `MarketMakingEngine` (pas de `RiskManager`/`trend_filter`/`atr_sizer`, sans objet pour cette strategie), `format_candidate` et `build_strategy` etendus. Reutilise SANS modification `BacktestResult`/`risk_adjusted_return`/`beats_benchmark`/`compute_window_consistency` - ces garde-fous (etape 6) sont agnostiques au type de strategie. **Non integre a `reoptimizer._search_best_out_of_sample`** (decision deliberee, pas un oubli) : `merge_proposal_into_config` ne remplace que les cles `RISK_KEYS_FROM_PROPOSAL` (stop_loss_pct/take_profit_pct) du risk existant, qui n'existent pas dans une proposition `market_making` (`{"fee_pct": ...}` seulement) - appliquer une proposition qui changerait le TYPE de strategie d'un bot existant laisserait sa section `risk` dans un etat incoherent (champs `RiskConfig` sur une config `market_making`), un vrai risque de plantage a `run_paper.py`. Comme tous les bots sont deja en groupe "control" (§3.25), ceci est actuellement sans consequence pratique, mais reste une limite documentee plutot qu'un correctif fait a la hate.

**`run_backtest.py`/`run_paper.py`** : detection de `config["strategy"]["type"] == "market_making"` pour construire `MarketMakingEngine`/`MarketMakingConfig` a la place de `Engine`/`RiskManager`/`RiskConfig`. `warm_up_strategy` (run_paper.py) ignore l'appel a `on_candle` pour cette strategie (pas de fenetre glissante a rechauffer - `MarketMakingStrategy.quote` ne depend que de la bougie courante et de l'inventaire). `control_server.VALID_STRATEGIES` **inchange** (meme limite de perimetre que `mean_reversion`, §3.25) : un bot `market_making` se cree uniquement via config YAML, pas via le formulaire dashboard.

**Bug reel decouvert et corrige pendant la validation empirique (CT-22 de la STB)** : premier run sur donnees reelles (BNB/SOL/LINK/AVAX, 3 ans) affichait des rendements absurdes (+15 000% a +19 000%). Cause : `_fill_ask` vendait en un seul ordre FIFO sans `lot_id` une quantite calculee sur l'inventaire TOTAL (reparti sur des dizaines de petits lots, un par fill bid), alors que `Portfolio.apply_fill` ne verifie pas que cette quantite tient dans le lot le plus ancien pris isolement - imputait le prix d'entree de ce lot a une quantite qu'il n'avait jamais detenue, creant un profit fictif amplifie par des milliers de trades. **Corrige** : `_fill_ask` vend desormais lot par lot, FIFO explicite par `lot_id`, jamais plus que ce que chaque lot detient reellement. Regression testee (`test_ask_fill_across_multiple_lots_does_not_create_phantom_profit`).

**Validation** : 26 nouveaux tests (`MarketMakingStrategy` x9, `MarketMakingEngine` x9 dont la regression CT-22, `optimize.py` x4, `Engine`/`shared_pool` refactorises sans regression sur la suite existante). Suite complete : 372 tests passent.

**Verification empirique (2026-09-13)**, meme discipline que EF-43 (validation out-of-sample + benchmark buy & hold + consistance multi-fenetres, script scratchpad en lecture seule, jamais la CLI reelle en ecriture - lecon de CT-21 appliquee) sur BNB/SOL/LINK/AVAX : **resultat negatif**. Le meilleur candidat par symbole perd entre -22% et -42% sur la periode de validation, avec un drawdown de 23% a 42% et une consistance multi-fenetres negative sur les 3 sous-fenetres pour les 4 symboles - aucun candidat ne passe les garde-fous (benchmark ET consistance). Aucun bot `market_making` cree. Comme pour EF-43, l'implementation est correcte et testee, mais cette premiere version simple (spread fixe, skew lineaire, pas de detection de regime/volatilite) n'a pas trouve d'edge sur ces 4 paires sur cette fenetre - une piste non explorée ici serait d'elargir le spread en periode de forte volatilite (a l'instar de l'ATR sizing, etape 2) pour reduire le risque de selection adverse en marche trending.

**Limite supplementaire constatee (smoke test manuel)** : ni `BacktestExecutor` ni `Portfolio.apply_fill` ne verifient que `cash` reste positif avant de remplir un achat (limite PREEXISTANTE, commune a toutes les strategies - les strategies directionnelles restent bornees en pratique par `RiskManager.validate` qui limite le nombre de positions simultanees, ce que `market_making` n'a pas puisqu'elle rachete un montant fixe a chaque fill de bid tant que `max_inventory_quote` n'est pas atteint). En backtest, `cash` peut donc devenir negatif (constate : -329,94 sur un run manuel), ce qu'un exchange reel refuserait. Les resultats de validation ci-dessus restent des comparaisons justes ENTRE candidats (tous mesures avec la meme limite), mais le rendement absolu affiche peut etre plus pessimiste qu'un deploiement reel qui s'arreterait simplement faute de fonds plutot que de continuer a trader a decouvert. A corriger avant tout paper trading reel de cette strategie (verifier `portfolio.cash >= cout de l'ordre` avant le fill bid, en plus de la verification `SharedPool` deja en place quand un panier commun est utilise).

### 3.27 Funding rate arbitrage - Phase A, pipeline + backtest (EF-45) — étape 8 de la feuille de route performance

**Contexte** : suite a la lecture d'un document de reference sur les strategies quant crypto (partage par l'utilisateur), identification du funding rate arbitrage (cash-and-carry : long spot + short perpetuel de meme notionnel, position delta-neutre, encaisse le funding periodique) comme edge structurellement different du suivi de tendance/retour a la moyenne/market making - un SERVICE rendu au marche (financement des positions a effet de levier), pas un pari directionnel ni une capture de spread.

**Decision de scope, ASSUMEE et EXPLICITE** : ce projet ne trade que du SPOT (`BacktestExecutor`/`PaperExecutor`/`Portfolio` a un seul actif). Une integration live complete (connecteur perpetuel, gestion de marge/effet de levier, moteur a deux jambes simultanees spot+perp) est un chantier de l'ampleur d'un nouveau sous-systeme, pas d'une strategie de plus - hors de portee d'une seule session. **Phase A (seule realisee ici)** se limite au pipeline de donnees et a un backtest de validation, dans le meme esprit que toutes les strategies testees ce soir : jamais de code de deploiement live avant d'avoir la preuve empirique que l'edge existe. Une eventuelle Phase B (execution live) serait planifiee separement, uniquement si la Phase A demontrait un edge robuste - ce qui n'a PAS ete le cas (voir plus bas).

**Verifie techniquement avant de coder** (test live contre l'API publique Binance, lecture seule) : `ccxt` (deja une dependance) expose nativement `fetch_funding_rate_history(symbol, since, limit)` et gere les perpetuels lineaires via le symbole unifie `"BTC/USDT:USDT"` - `fetch_ohlcv` fonctionne dessus exactement comme sur le spot. Aucune nouvelle dependance, aucun nouveau client exchange.

**Composants nouveaux** :
- `types.FundingRatePoint(timestamp, funding_rate)`.
- `data_feed.fetch_funding_rate_history(exchange_id, symbol, since_iso, use_cache=True, exchange=None)` - meme patron de pagination/cache Parquet que `fetch_historical_candles`, mais avec un parametre `exchange` injectable (patron deja utilise par `control_server.fetch_price_history`/`FakePriceExchange`, plus testable que `fetch_historical_candles` qui ne le permet pas).
- `funding_arb.py` (nouveau module autonome, sur le modele de `optimize.py` - pas une extension de `Engine`/`Portfolio`, concus pour un seul actif) :
  - `FundingArbCandidate`/`FundingArbResult` (`risk_adjusted_return` = meme formule que `BacktestResult`, `MIN_DRAWDOWN_FLOOR` reutilise depuis `optimize.py`).
  - `simulate_funding_arb(spot_candles, perp_candles, funding_history, candidate)` : boucle sur les ECHEANCES de funding (pas sur chaque bougie) ; entre/sort selon une moyenne glissante du funding (`lookback_periods`, evite de reagir a un seul versement bruite) ; a la sortie, calcule explicitement le **P&L de base** (`qty_spot x (exit_spot - entry_spot) + qty_perp x (entry_perp - exit_perp)`) - le residuel apres couverture, JAMAIS suppose nul (c'est precisement le risque que la doc de reference identifie comme le plus sous-estime de cette strategie). Frais appliques sur les 4 legs (achat+vente spot, achat+vente perp) par cycle.
  - `compute_funding_window_consistency` : meme esprit que `optimize.compute_window_consistency`, reimplemente car il opere sur des echeances de funding et doit recouper les bougies spot/perp sur chaque sous-fenetre temporelle.
  - **Nuance de garde-fou, documentee explicitement dans le code** : `has_edge_over_benchmark`/`beats_benchmark` (etape 6, EF-39) NE S'APPLIQUE PAS ici - une strategie delta-neutre est CENSEE etre decouplee de la direction du marche, exiger qu'elle batte un buy & hold en marche haussier n'a pas de sens. Remplace par : rendement ajuste au risque positif ET consistance multi-fenetres >= 50%. Le benchmark reste calcule et affiche (a titre informatif), mais n'est plus un gate.
  - `main(symbols)` (CLI `python -m tradingbot.funding_arb --symbols BTC/USDT,ETH/USDT,SOL/USDT`) : perpetuel derive automatiquement du symbole spot (`f"{symbol}:USDT"`), split train/test reutilise `optimize.split_train_test` (generique, fonctionne sur n'importe quelle liste). **N'ecrit aucune config** - pas de bot deployable en Phase A, il n'existe pas de moteur live pour cette strategie.

**Validation** : 13 nouveaux tests (`fetch_funding_rate_history` x4 avec `FakeFundingExchange`, `simulate_funding_arb` x6 dont l'isolement du P&L de base, `build_funding_arb_candidates`/`format_candidate`/`compute_funding_window_consistency` x3). Suite complete : 386 tests passent.

**Verification empirique (2026-09-14)** sur BTC/USDT, ETH/USDT, SOL/USDT (perpetuels les plus liquides, 3 ans d'historique reel via `ccxt`) : **resultat NON CONCLUANT**, a rapporter honnetement plutot qu'a arrondir dans un sens ou l'autre :
- **BTC/USDT** : echoue les garde-fous. A l'entrainement, le risque de base DOMINE largement le funding collecte (P&L de base -425,70 contre funding collecte +187,53 sur la meme periode) - confirmation empirique directe du risque documente par la source de reference ("le residuel de couverture peut largement depasser le spread/funding capte"). En validation, redevient positif (+2,24%) mais sur seulement 2 cycles, consistance non mesurable (fenetres trop courtes).
- **ETH/USDT** : "passe" les garde-fous tels que definis (rendement ajuste au risque positif, consistance 100% sur les fenetres exploitables), mais sur un signal **statistiquement faible** - seulement 2-3 cycles complets sur la periode de validation, et une seule sous-fenetre sur 3 avait assez de cycles pour etre mesuree. Ce n'est pas une confirmation robuste, juste l'absence de signal negatif sur un tres petit echantillon.
- **SOL/USDT** : legerement negatif en validation (-0,35%), echoue les garde-fous.

**Bilan honnete** : contrairement a l'espoir initial (edge structurel, documente comme plus fiable que le pari directionnel), le funding rate arbitrage TEL QUE MODELISE ICI (seuils fixes sur moyenne glissante, sans ajustement de taille a la volatilite, sans limite de duree de detention) ne demontre pas un edge robuste sur ces 3 paires sur cette fenetre de 3 ans - le risque de base (pas le funding lui-meme) est le facteur qui domine le resultat, exactement comme la documentation de reference l'anticipait. **Aucune Phase B (execution live) engagee** - conformement a la decision de scope prise en debut de section, l'edge n'etant pas confirme, il n'y a pas de raison d'investir dans le chantier d'execution a deux jambes.

### 3.28 Rebond de creux sans stop-loss + bot passif (EF-46, EF-47) — etape 9 de la feuille de route performance

**Contexte** : suite au bilan de l'etape 8 (aucune strategie testee ce soir n'a demontre d'edge robuste) et a une question de l'utilisateur sur le trading passif, l'utilisateur propose sa PROPRE logique : acheter pres d'un creux recent tant que le regime reste haussier, tenir SANS stop-loss, et sortir soit sur un nouveau plus haut recent, soit via un verrou de gain (une fois un premier seuil de gain depasse, vendre si le gain retombe a un second seuil, plus bas). En parallele, ajout d'un bot "buy & hold" passif, pour rendre l'alternative "arreter le trading actif" concretement deployable plutot que theorique.

**Bonne nouvelle architecturale** : contrairement a `market_making`/`funding_arb` (etapes 7/8), ces deux strategies sont a un seul actif, une position a la fois, dirigees par signal - elles rentrent EXACTEMENT dans le modele `Strategy`/`Engine`/`RiskManager`/`Portfolio` existant, sans nouveau moteur.

**Composants nouveaux** :
- `strategies/dip_bounce.py::DipBounceStrategy(trend_ma_period=24, dip_threshold_pct=0.005)` - UNE SEULE fenetre glissante sert a la fois de moyenne de regime, de minimum (detection du creux) et de maximum (objectif de sortie), coherent avec l'enonce original ("sur 24h" applique partout). Agnostique du timeframe : raisonne en nombre de bougies, pas en heures - `trend_ma_period=24` sur bougies 1h et `=60` sur bougies 1m expriment la MEME regle a deux granularites (voir plus bas, "2 presets"). Achat si `close > sma ET close <= min*(1+dip_threshold_pct)` ; vente si `close >= max` (cible glissante, recalculee a chaque bougie - pas fixee a l'entree).
- `strategies/buy_and_hold.py::BuyAndHoldStrategy` - achete une seule fois (`_bought` interne), ne revend jamais. Operationnalise en bot deployable le meme benchmark deja utilise toute la soiree pour juger les autres strategies (`compute_buy_and_hold_return_pct`).
- `risk/risk_manager.py` : `RiskConfig.stop_loss_pct` devient `float | None` (etait obligatoire) - `None` desactive REELLEMENT le stop-loss (`should_stop_loss` retourne `False`), au lieu de bricoler une valeur enorme. Nouveaux champs `profit_lock_arm_pct`/`profit_lock_trigger_pct` et nouvelle methode `should_profit_lock` : arme si le PIC de gain depuis l'entree (`position.peak_price`, deja maintenu par `Engine._decide` exactement comme pour `should_trailing_stop` - aucun changement de schema de `Position`) a deja depasse `profit_lock_arm_pct`, puis declenche des que le gain COURANT retombe a ou sous `profit_lock_trigger_pct`. Different du trailing stop existant (EF-24, distance FIXE depuis le pic) : ici le plancher de sortie est un seuil ABSOLU une fois arme, peu importe a quel point le pic a depasse l'armement.
- `engine.py::_decide` : nouvelle branche `should_profit_lock` dans la boucle de sorties par lot, juste apres `should_trailing_stop`.
- `optimize.py::build_dip_bounce_candidates()` - grille sur `trend_ma_period`/`dip_threshold_pct`/`profit_lock_arm_pct`/un ecart de rappel (`giveback`) dont derive `profit_lock_trigger_pct` (filtre les combinaisons ou `trigger <= 0`). `run_one_backtest` : **aucun changement** (chemin `Engine`/`RiskManager` standard, contrairement a `market_making`). `buy_and_hold` n'est PAS integre a la grille : aucun parametre a optimiser.

**Integration dashboard - limite des etapes 7/8 levee pour cette famille** : contrairement a `mean_reversion`/`market_making`/`funding_arb` (YAML uniquement), `dip_bounce` (2 presets) et `buy_and_hold` sont creables directement depuis le formulaire (`control_server.py`/`reporting/dashboard.py`) :
- `VALID_STRATEGIES` etendu a `dip_bounce_hourly`, `dip_bounce_minute`, `buy_and_hold` - des PRESETS cote formulaire, pas de nouveaux types de strategie reels : les deux presets `dip_bounce_*` ecrivent `strategy.type: dip_bounce` en YAML avec `trend_ma_period`/`timeframe` fixes (24/1h ou 60/1m). **`timeframe` est force cote serveur**, independamment de ce que le formulaire a soumis - la coherence preset/granularite ne doit jamais dependre d'un champ libre.
- `stop_loss_pct` devient conditionnellement `None` (les 3 nouveaux types), le formulaire desactive visuellement le champ (`onStrategyTypeChange`, grise + message "Desactive : cette strategie n'a pas de stop-loss").
- **Bug prevenu avant qu'il n'existe** : `warm_up_strategy` (run_paper.py) appelle `strategy.on_candle()` sur l'historique pendant le "rechauffement" (etat interne prime, signal jete) - pour `buy_and_hold`, le moindre rechauffement non nul aurait declenche son achat UNIQUE pour de faux, et le bot n'aurait plus jamais achete reellement au demarrage live. **Corrige en amont** : `warmup_candles` force a 0 cote serveur pour ce type, jamais deduit du formulaire. Aucun changement necessaire dans `run_paper.py` lui-meme (deja generique sur `config["timeframe"]`, "1m" fonctionne deja comme "1h").

**Validation** : 15 nouveaux tests (`DipBounceStrategy` x9, `BuyAndHoldStrategy` x2, `RiskManager.should_profit_lock`/`should_stop_loss(None)` x5), 6 tests Engine (`should_profit_lock` declenche une sortie, absence confirmee de stop-loss meme apres un crash simule quand `stop_loss_pct=None`), 3 tests `optimize.py`, 4 tests `control_server` (creation des 2 presets + `buy_and_hold`, timeframe force malgre valeur soumise differente, warmup force a 0, seuil de declenchement >= armement rejete). Suite complete : 411 tests passent (voir §3.29 pour les 8 tests ajoutes ensuite pour backtest_lab.py).

**Verification empirique (variante horaire uniquement, 2026-09-14)** sur les 10 symboles de la flotte (3 ans, script scratchpad en lecture seule - meme lecon de CT-21) : **resultat mitige**. 5/10 symboles (ETH, XRP, BNB, LINK, DOGE) passent le filtre mecanique (bat le buy & hold ET consistance >= 50%), mais avec une nuance importante : sur la periode testee, le buy & hold etait fortement NEGATIF pour la plupart des symboles (ADA -67%, AVAX -63%, DOGE -55%) - une strategie qui reste la plupart du temps hors marche bat quasi automatiquement un marche qui s'effondre, ce qui n'est PAS la preuve d'un edge. Seul TRX (le seul marche en hausse sur la periode, +8,24%) offre un vrai test : la strategie y **perd** contre le buy & hold (+0,21% vs +8,24%). Taux de reussite eleve (66-83%) mais gains individuels minuscules (verrou de gain a +0,4%/+1%). **Le risque "pas de stop-loss" s'est concretement materialise** : pire trade a -32,24 sur ADA (-3,2% du capital de test en un seul trade), et sur LINK une position est restee ouverte a la toute fin de la periode de validation (le scenario "on ne sait pas ce qu'elle serait devenue"). **Variante minute non testee empiriquement** - le cout de telechargement (historique 1m sur 3 ans, ~4h pour 10 symboles) a ete annonce, la decision de le lancer a ete differee. Aucun bot cree en config reelle a ce stade ; l'utilisateur a neanmoins demande l'integration dashboard des deux presets malgre ce resultat mitige, pour pouvoir experimenter directement.

**Correction de comportement (2026-09-14, suite a une relecture de l'utilisateur)** : la regle de sortie sur "nouveau plus haut de la fenetre glissante" (`candle.close >= rolling_max`, decrite ci-dessus) est **retiree**. L'utilisateur a explicite son intention comme un vrai "achete et garde, jusqu'a ce qu'un gain apparaisse puis se fasse rogner" - or `rolling_max` etant le plus haut des SEULES 24 dernieres bougies (pas depuis l'achat), cette sortie pouvait se declencher pour un gain minuscule bien avant que le verrou de gain ait la moindre chance de s'armer, ce que confirme la validation empirique ci-dessus (gains individuels "minuscules"). `DipBounceStrategy.on_candle` n'emet plus desormais QUE des signaux BUY - la seule sortie possible est `should_profit_lock` (deja gere par `engine.py`, inchange). **Consequence architecturale** : `_in_position` (et `rolling_max`) sont retires de la strategie - ils ne servaient qu'a gerer cette sortie disparue. Empecher un double achat pendant qu'une position est deja ouverte est desormais entierement le role de `RiskManager.max_concurrent_positions` (deja applique au niveau `Engine`, base sur les positions REELLEMENT ouvertes) - un flag interne a la strategie se serait de toute facon desynchronise des la premiere fermeture externe (verrou de gain) puisque la strategie n'est jamais notifiee des sorties decidees par le `RiskManager`. 2 tests mis a jour dans `test_dip_bounce_strategy.py` (`test_never_emits_a_sell_signal`, `test_signals_buy_again_on_every_candle_while_conditions_persist`) a la place des 2 tests qui couvraient l'ancien comportement. **La validation empirique ci-dessus date d'AVANT cette correction** - a rejouer avec le comportement actuel avant de tirer une conclusion sur un eventuel edge.

**Deuxieme correction de comportement (2026-09-14, meme jour)** : l'utilisateur a clarifie que la condition d'entree ne devait retenir QUE "le prix est au plus bas sur les dernieres 24h", sans exiger en plus un regime haussier (`close > sma`). Le calcul de `sma` et la condition `is_bullish_regime` sont retires de `on_candle` - seule reste `near_the_dip` (`close <= rolling_min * (1 + dip_threshold_pct)`). Consequence mesuree sur BTC/USDT janvier-avril 2025 : 4 -> 7 trades sur la meme periode (l'entree redevient possible aussi en marche baissier), detention max 137h -> 257h. `trend_ma_period` reste le nom du parametre (compatibilite des presets/config existants) mais ne represente plus qu'une fenetre de detection du plus bas, plus une moyenne de regime. Tests mis a jour : `test_buy_when_near_the_dip` (ex-`..._bullish_regime_and...`), `test_buy_even_in_a_falling_market_when_price_is_the_new_low` (ex-`test_no_buy_when_bearish_regime_...`, assertion inversee : achete desormais dans ce cas), `test_no_buy_when_far_from_the_dip` (renomme, comportement inchange).

### 3.29 Outil de test unifie `backtest_lab.py` (EF-48) — etape 9 (suite)

**Contexte** : au fil des etapes 6 a 9, les tests ponctuels (frequence de surveillance, `DipBounceStrategy`, etc.) ont chacun donne lieu a un script scratchpad ecrit dans l'instant, avec ses propres parametres codes en dur - au bout de plusieurs sessions, ces jeux de parametres ne correspondent plus a rien de reproductible ni de comparable entre eux. L'utilisateur a demande un outil dedie plutot que de continuer a accumuler des scripts jetables.

**Choix de conception** : `src/tradingbot/backtest_lab.py`, point d'entree unique, PAS un nouveau moteur - reutilise integralement `Engine`/`MarketMakingEngine`/`RiskManager`/`Portfolio`/`BacktestExecutor` et le `STRATEGY_REGISTRY` deja definis dans `run_backtest.py` (aucune duplication de logique de simulation).

- Un dictionnaire `PRESETS` declare, pour chaque type de bot testable (les 4 strategies directionnelles + market making + les 2 presets dip_bounce + buy_and_hold), ses parametres de strategie et de risque sous forme de `ParamSpec` (nom, libelle, defaut, type, unite) - une seule declaration alimente a la fois le mode interactif (menu numerote, valeur par defaut proposee) et le mode scriptable (`--param cle=valeur`, valide contre la liste des parametres attendus pour cette strategie, erreur explicite sinon).
- **Deux modes d'usage** : lance sans argument -> questions posees une par une (type de bot, devise, exchange, periode, capital, parametres) ; lance avec `--strategy`/`--symbol`/`--since` -> execution directe scriptable, pour rejouer un test exact plus tard. `--list-strategies` affiche les types disponibles.
- **Filtrage de periode** : `fetch_historical_candles` (data_feed.py) ne prend qu'un `since` (pas de borne de fin) - `backtest_lab.py` filtre la liste de bougies obtenue a la fenetre `[since, until]` demandee, sans modifier `data_feed.py`.
- **Rapport de sortie** (`format_report`) : rendement total, comparaison explicite au benchmark buy & hold (`compute_buy_and_hold_return_pct`, deja utilise par l'optimizer), drawdown max, P&L realise, PUIS un bloc "Trades" qui rend visibles les risques plutot que de les masquer derriere le rendement agrege - nombre de trades, taux de reussite, meilleur/PIRE trade, duree de detention maximale, et positions encore ouvertes en fin de periode avec leur P&L latent non realise (pertinent en particulier pour les strategies sans stop-loss, §3.28). Affiche a l'ecran ET enregistre dans `backtest_reports/<preset>_<devise>_<horodatage>.txt`.

**Option `--repeat N`** : decoupe la periode `[since, until]` en N sous-periodes contigues de meme duree (`split_periods`, pas de fenetres glissantes/chevauchantes - un decoupage simple suffit) et rejoue un backtest INDEPENDANT sur chacune (`run_one_period` cree une strategie/un portefeuille/un moteur neufs a chaque sous-periode - aucun etat report de l'une a l'autre). Repond directement au constat de l'etape 9 (§3.28) qu'un resultat agrege peut cacher une seule periode exceptionnelle (aout) noyee dans des mois neutres ou negatifs - le rapport (`format_repeat_report`) liste le rendement et la comparaison au buy & hold de chaque sous-periode, puis une synthese (rendement moyen/median, meilleure/pire sous-periode, proportion de sous-periodes positives et de sous-periodes qui battent le buy & hold).

**Limite assumee** : couvre le backtest d'un seul bot a la fois (par design - remplace les scripts qui en enchainaient plusieurs avec des parametres disparates), pas une nouvelle campagne de validation out-of-sample multi-symboles - `optimize.py` reste l'outil pour la recherche de parametres sur grille.

**Validation** : verifie manuellement sur les 3 familles de moteur (`Engine` standard, `MarketMakingEngine`) et les cas limites (parametre inconnu rejete proprement, `buy_and_hold` avec position encore ouverte en fin de periode correctement remontee). 8 nouveaux tests (`tests/test_backtest_lab.py`) couvrant `split_periods`, `presets_metadata`, `build_namespace_from_payload`, et `run_backtest_job` (rejet strategie/parametre inconnu, execution bout-en-bout avec des bougies factices, mode --repeat) - candles simulees via monkeypatch de `fetch_historical_candles`, aucun appel reseau. Suite complete : 419 tests (voir §3.30 pour 3 tests supplementaires ajoutes ensuite).

### 3.30 Correction du cache de bougies historiques (CT-23)

**Constat en conditions reelles (2026-09-14)**, via le nouvel onglet Test/Backtest (§3.6) : un backtest `dip_bounce_minute` sur DOGE/USDT (juin-aout 2026) renvoyait "0 bougie recuperee" alors qu'un cache local existait pour ce symbole/timeframe. Deux bugs empiles dans `data_feed.fetch_historical_candles` :

1. **`ccxt.Exchange.parse8601` renvoie `None` sur une date SANS heure** (`"2025-04-01"` -> `None`, seul `"2025-04-01T00:00:00Z"` fonctionne) - `backtest_lab.py` passait directement la date du formulaire/CLI (`args.since`, format `AAAA-MM-JJ`) a `fetch_historical_candles`. Consequence silencieuse jusqu'ici : `since=None` transmis a `fetch_ohlcv` fait partir la recuperation de l'origine des temps au lieu de la date demandee - "fonctionnait" par accident tant que le filtrage cote appelant (`backtest_lab.filter_candles`) recoupait ensuite a la bonne fenetre, mais telechargeait (et mettait en cache) bien plus de donnees que necessaire.
2. **Le cache ne verifiait jamais qu'il couvrait la periode demandee** : `if use_cache and cache_path.exists(): return <tout le cache>` faisait confiance a la seule PRESENCE d'un fichier cache, jamais a son etendue reelle. Un cache 1m etroit pour DOGE/USDT (construit pour une toute autre periode, une semaine de septembre) masquait donc silencieusement n'importe quelle periode differente demandee ensuite - y compris une periode plus ancienne, sans jamais retelecharger.

**Corrige le jour meme** :
- `backtest_lab.py` formate desormais `since_iso=f"{args.since}T00:00:00Z"` avant l'appel.
- `fetch_historical_candles(..., exchange=None)` : `exchange` devient injectable (meme pattern que `fetch_funding_rate_history`, pour les tests sans reseau). Le cache n'est retourne tel quel que si `since_ms` n'a pas pu etre parse (comportement de repli inchange) OU si `df["timestamp"].min() <= since_ms` - sinon le cache est ignore et une recuperation fraiche est lancee (et re-ecrit le cache, comme le comportement "sans cache" deja existant).

**Validation** : 3 nouveaux tests (`tests/test_data_feed.py`) avec un exchange factice (`FakeCandleExchange`) - cache suffisant reutilise sans appel reseau, cache trop etroit ignore avec un vrai appel `fetch_ohlcv`, cache conserve si `since` n'a pas pu etre parse. Reproduit et confirme sur le cas reel (DOGE/USDT 1m, juin-aout 2026) : la recuperation fraiche part desormais bien du 1er juin (au lieu de l'origine des temps ou d'un cache non pertinent). Suite complete : 422 tests.

### 3.31 Sizing par niveau de prix + trade force (EF-51, EF-52) - 2 idees proposees par l'utilisateur

**Sizing par niveau de prix (EF-51)** : `analysis/price_level_sizer.py::PriceLevelSizer`, sur le meme principe optionnel/independant que `AtrSizer`/`TrendFilter` (`update(candle)` a chaque bougie, `size_multiplier(current_price)` avant chaque achat) - MAIS contrairement a `AtrSizer` (qui ne fait que REDUIRE la taille), celui-ci peut aussi bien l'AGRANDIR (prix sous la moyenne du mois) que la reduire (prix au-dessus), avec deux bornes independantes `min_size_multiplier`/`max_size_multiplier` (0.5/1.5 par defaut). La moyenne se reinitialise au 1er de chaque mois calendaire (UTC) - decision assumee de l'utilisateur, bruitee en debut de mois. Cable partout ou `AtrSizer` l'est deja, en parallele (pas en remplacement) : nouveau parametre `Engine(price_level_sizer=...)` (multiplie avec celui de l'ATR si les deux sont actifs), `run_paper.py` (construction depuis `config["price_level_sizing"]`, warmup, statut dashboard), `control_server.py` (`price_level_sizing_enabled`/`price_level_min_multiplier`/`price_level_max_multiplier`), nouveau filtre avance dans le formulaire du dashboard, nouvelle carte statistique "Sizing niveau de prix" dans l'onglet Bot. **Non teste empiriquement** - aucun bot reel de ce projet ne l'active a ce jour.

**Trade force apres N heures (EF-52)** : nouveau parametre optionnel `DipBounceStrategy(force_trade_after_hours: float | None = None)`. Si aucun achat n'a eu lieu depuis ce nombre d'heures REEL (base sur `candle.timestamp`, pas un nombre de bougies - reste coherent quel que soit le timeframe), le seuil `dip_threshold_pct` est double a chaque periode entiere supplementaire ecoulee sans achat (`_effective_threshold`), jusqu'a finir par matcher sur une bougie - jamais un achat instantane "a tout prix", juste un seuil de moins en moins strict. Le compteur (`_last_buy_ts`) repart de zero a chaque signal BUY emis par la strategie, que l'ordre soit ensuite accepte ou rejete par le `RiskManager` (ex: `max_concurrent_positions` deja atteint) - la strategie ne connait que ses propres signaux, pas leur sort cote Engine, ce qui est le comportement voulu ici (ce parametre cible le cas "la strategie ne signale jamais rien", pas le cas "une position reste bloquee", deja traite par EF-46 v0.32/`max_concurrent_positions`). Cable dans `backtest_lab.py` (`ParamSpec` du preset, `0` = desactive -> converti en `None` dans `build_strategy_instance`) et `control_server.py`/dashboard (memes conventions, `0`/vide = desactive) pour les 2 presets `dip_bounce_hourly`/`dip_bounce_minute`.

**Validation** : 7 tests `PriceLevelSizer` (`tests/test_price_level_sizer.py`), 3 tests Engine (`tests/test_engine_price_level_sizer.py`), 4 tests `DipBounceStrategy` (desactive par defaut, seuil qui finit par s'assouplir, reset du compteur apres achat, validation du parametre), 4 tests `control_server` (accepte/rejette, `0` = desactive). Suite complete : 445 tests (voir §3.29 pour les 4 tests supplementaires ajoutes ensuite pour le cablage backtest_lab, 449 au total).

### 3.32 Surveillance des sorties a granularite fine (EF-53) + CT-24

**Contexte** : suite a une discussion sur un backtest `dip_bounce_hourly` reel (verrou de gain arme a 1%, declenche a 0.7%), l'utilisateur a fait remarquer que des trades se cloturaient a des pertes de plusieurs % malgre "aucune sortie possible sauf en profit" - diagnostic : le verrou de gain n'est verifie qu'UNE FOIS PAR BOUGIE (candle.close), donc sur un timeframe d'entree de 1h, un prix qui s'effondre entre deux verifications peut deja avoir chute loin sous le seuil de declenchement avant que la vente ne se produise. L'utilisateur a demande que la verification se fasse toutes les 5 minutes plutot que toutes les heures.

**Choix d'architecture** : au lieu de reduire le timeframe de la STRATEGIE elle-meme (ce qui changerait aussi ses entrees, non demande), separation entre "bougies vues par la strategie" (entrees, timeframe large ex. 1h) et "bougies de surveillance des sorties" (timeframe fin ex. 5m) :
- `Engine.check_lot_exits(candle) -> list[str]` : la boucle "sorties par lot" (stop-loss/take-profit/trailing/verrou de gain/sortie partielle), extraite de `_decide` sans changement de comportement (`_decide` l'appelle desormais au lieu de dupliquer la logique).
- `Engine.process_price_update(candle) -> list[str]` : appelle UNIQUEMENT `check_lot_exits` + enregistre l'equity - jamais la strategie ni les sizers (atr_sizer/price_level_sizer), pour ne jamais faire avancer leur etat sur des donnees plus fines que celles pour lesquelles ils sont configures.
- `backtest_lab.py::merge_dual_timeframe(entry_candles, exit_check_candles, entry_timeframe, exit_check_timeframe)` fusionne les deux series en une seule sequence chronologique consommee par `run_one_period` (`process_candle` pour les bougies d'entree, `process_price_update` pour les bougies fines).
- Nouveau CLI `--exit-check-timeframe` / champ dashboard "Timeframe de surveillance des sorties" (Test/Backtest uniquement pour l'instant - pas encore cable dans `run_paper.py`/`control_server.py` pour un vrai bot, limite assumee en attendant une validation empirique).

**CT-24 (bug reel decouvert pendant l'implementation)** : la premiere version de `merge_dual_timeframe` triait les deux series par `candle.timestamp` BRUT (l'OUVERTURE de la bougie). Or une bougie 1h ouverte a T n'est connue (son `close` disponible) qu'a T+1h - une heure APRES les bougies 5 min de cette meme heure qui partagent le meme `timestamp` d'ouverture nominal. Consequence mesuree sur un vrai backtest (BTC/USDT, verrou de gain 1%/0.7%) : la bougie 1h de l'heure N (dont le `close` reflete en realite le prix a la fin de l'heure N, donc au debut de l'heure N+1) etait traitee comme si elle arrivait AVANT les bougies 5 min de l'heure N+1, provoquant des "sauts" de prix artificiels de plusieurs % dans la sequence vue par `check_lot_exits` - un trade s'est ainsi vendu a -3.12% au lieu de pres de +0.7%. **Corrige le jour meme** : le tri se fait desormais sur l'instant ou chaque bougie devient REELLEMENT connue (`timestamp + ccxt.Exchange.parse_timeframe(timeframe) * 1000`), pas sur son ouverture ; une bougie fine et une bougie d'entree qui partagent le meme instant de cloture voient la bougie d'entree l'emporter (traitement complet, pas de doublon). Sans ce correctif, la fonctionnalite aurait empire exactement le probleme qu'elle visait a corriger.

**Validation** : 4 nouveaux tests `backtest_lab` (ordre correct par instant de cloture - reproduit explicitement le bug CT-24 avec des valeurs qui le rendraient visible immediatement si la regression revenait -, remplacement d'une bougie fine coincidente par la bougie d'entree, execution bout-en-bout avec un scenario cree pour reproduire un armement puis une chute franche), 4 nouveaux tests `Engine.process_price_update`/`check_lot_exits` (jamais d'appel a la strategie, declenche bien une sortie sur un prix intermediaire, enregistre l'equity, non-regression du refactoring de `_decide`). Resultat empirique avant/apres sur le cas reel qui a motive la demande : 29/79 trades negatifs (pire -3.32) sans surveillance fine -> 1/12 (pire -0.01, un pur effet de frais) avec surveillance a 5 minutes, sur la meme periode et les memes parametres. Suite complete : 456 tests.

**Extension aux vrais bots (2026-09-15)** : l'utilisateur a demande le meme reglage "sur tous les bots", pas seulement en test. Nouveau champ top-niveau (hors `risk`, ce n'est pas une regle de risque mais une frequence de sondage) `exit_check_timeframe` dans la config YAML :
- `control_server.py::build_config` : valide que le timeframe fourni est dans `VALID_TIMEFRAMES` ET strictement plus fin que le `timeframe` du bot (`ccxt.Exchange.parse_timeframe` compare les durees) - sans objet pour `market_making` (absent de `VALID_STRATEGIES`, jamais construit via ce chemin).
- `run_paper.py` : **aucun appel reseau supplementaire** - la boucle de sondage recupere deja `current_price` via `exchange.fetch_ticker(...)` a chaque cycle quand aucune bougie d'entree ne vient de se clore (`poll_interval_seconds = min(60, timeframe_seconds)`, deja <= 60s). Il suffit de reutiliser ce prix : un minuteur (`last_exit_check_ts`, remis a zero a chaque bougie d'entree traitee) declenche `engine.process_price_update(candle_synthetique)` des que `exit_check_interval_seconds` (converti depuis `exit_check_timeframe`) s'est ecoule. Une bougie synthetique `open=high=low=close=current_price` est construite pour l'occasion - `check_lot_exits` ne regarde que `candle.close`, aucune perte d'information.
- Formulaire dashboard : nouveau champ "Timeframe de surveillance des sorties" dans le bloc "Gestion du risque" (§5.2), visible pour tous les types de bot du formulaire.

**Validation** : 4 nouveaux tests `control_server` (absent par defaut, accepte un timeframe plus fin, rejette un timeframe invalide, rejette un timeframe pas plus fin que celui du bot). Suite complete : 460 tests.

---

### 3.33 CT-25 : bug reel corrige - `_target_prices` plantait sur `stop_loss_pct=None`

**Decouvert** le 2026-09-15 : `ETHSWING`/`XRP_SWING` (2 bots `dip_bounce` reels, `stop_loss_pct: null` assume, voir §3.28) ont plante des leur premiere position ouverte. Traceback : `TypeError: unsupported operand type(s) for -: 'int' and 'NoneType'` dans `reporting/stats.py::_target_prices`, qui calculait `entry_price * (1 - risk_config.stop_loss_pct)` sans jamais verifier que `stop_loss_pct` etait bien defini - un oubli introduit lors du passage de ce champ a `float | None` (§3.28), jamais declenche jusqu'ici car aucun bot `dip_bounce` n'avait encore ete deploye en reel avec une position ouverte. **Corrige** : garde `if risk_config.stop_loss_pct is not None else None`, symetrique a celle deja presente pour `take_profit_pct`. 2 nouveaux tests de regression (`test_build_orders_table.py`, position ouverte et position fermee sans stop-loss). Suite complete : 462 tests avant la suite des changements de cette version.

### 3.34 Parite Test/Backtest avec la config de bot reelle (EF-54)

**Contexte** : demande explicite de l'utilisateur ("la config de test n'est pas identique à la configuration de bot et c'est dommage") - l'onglet Test/Backtest et le formulaire de creation de bot avaient diverge au fil des sessions : plusieurs reglages de risque (taille position max, perte max journaliere, trailing stop, frais, sortie partielle) et 2 filtres optionnels (tendance EMA, sizing ATR) n'existaient QUE cote bot reel, empechant de les valider en backtest avant deploiement. Le timeframe etait aussi fige a "1h" en backtest pour les presets qui n'en forcent pas (sma_cross, scalp_dip, mean_reversion, buy_and_hold), sans readaptation possible.

**Choix retenus** :
- `backtest_lab.py::build_risk_kwargs_and_summary` etendu (memes noms/echelles que `control_server.py::build_config`) : `max_position_size_pct`, `max_daily_loss_pct`, `trailing_stop_pct`, `fee_pct`, `partial_take_profit_pct`/`partial_exit_fraction`, tous optionnels (absent du payload = defaut `RiskConfig` inchange, retro-compatible avec le CLI/les tests existants). Meme garde-fou "positions x taille <= 100%" que cote bot reel.
- Nouvelles fonctions `build_trend_filter_kwargs`/`build_atr_sizer_kwargs` (meme principe que `build_price_level_sizer_kwargs` deja existant) - `run_one_period` construit un `TrendFilter`/`AtrSizer` FRAIS par (sous-)periode et les passe a `Engine` (qui les acceptait deja en parametre, cote seulement branche cote `run_paper.py` jusqu'ici). **Demarrent a froid** (pas d'historique avant la periode testee pour les rechauffer, contrairement au mode paper qui les rechauffe via `warm_up_strategy`) - meme limite deja acceptee pour le sizing par niveau de prix en backtest, documentee dans le docstring de `run_one_period` plutot que corrigee (aurait exige de retelecharger et rejouer une fenetre supplementaire avant chaque sous-periode, hors perimetre de cette demande).
- Timeframe : `run_backtest_job` accepte desormais `args.timeframe` quand `preset.timeframe is None` (valide contre `VALID_TIMEFRAMES`, duplique de `control_server.py` - ce module ne doit rien importer de `control_server`, qui importe DE lui) ; ignore silencieusement pour les presets qui en forcent un (`dip_bounce_hourly`/`minute`), meme garantie que cote bot reel.
- **Exclusion volontaire et documentee du filtre de probabilite (Monte Carlo)** : `ProbabilityGate.current_probability()` calcule "moyenne des rendements journaliers des `lookback_years` dernieres annees a partir de MAINTENANT (`time.time()`)", jamais relatif a la periode testee - le brancher tel quel sur un backtest de janvier 2025 aurait utilise des donnees allant jusqu'a la date reelle d'execution du test (biais de preconnaissance : le backtest aurait "vu" des donnees posterieures a la periode qu'il pretend tester). Corriger cela correctement demanderait un `ProbabilityGate` conscient du temps simule (ancrer le calcul sur le timestamp de la bougie testee, pas sur l'horloge reelle) - non fait ici, propose comme piste separee plutot que d'introduire silencieusement un biais dans un outil dont la rigueur (validation out-of-sample, benchmark buy&hold) est justement la raison d'etre.
- Dashboard (`reporting/dashboard.py`) : formulaire Test/Backtest reorganise pour porter les memes sections que le formulaire de creation (§5.2 du manuel) - timeframe libre/verrouille selon le preset (`onBacktestStrategyChange` etendu), 4 nouveaux champs de risque generiques, blocs repliables Sortie partielle/Filtre de tendance/Sizing ATR, tous masques pour `market_making` (memes conditions que les blocs deja existants Sizing par niveau de prix/Verification des sorties).

**CT-26 (decouvert pendant la verification manuelle)** : le premier test dans le navigateur montrait les nouveaux reglages absents du rapport malgre un payload JSON correctement forme (verifie en interceptant `window.fetch`). Cause : DEUX instances de `control_server.py` tournaient simultanement sur ce poste (aucune protection `process_lock.py` sur ce process, contrairement aux bots - `bot_{name}.lock` ne couvre que `run_paper.py`), l'une lancee des le debut de la session, l'autre plus tard depuis un autre terminal ; sous Windows, `http.server.HTTPServer.allow_reuse_address` permet a la seconde de capturer le port 8765 sans faire echouer la premiere au demarrage - les requetes du dashboard atterrissaient sur l'instance la plus recente, mais celle-ci avait charge `backtest_lab.py` AVANT les modifications de cette session (les imports Python ne se rechargent jamais tout seuls dans un process deja demarre, meme probleme deja rencontre plusieurs fois avec `dashboard.py` - voir §3.6). Resolu en tuant les 2 paires de process et en relancant une seule instance. **Corrige le jour meme (demande explicite de l'utilisateur)** : `control_server.py::main()` appelle desormais `process_lock.acquire_lock(control_server.lock)` avant de demarrer le serveur - meme mecanisme atomique que les bots, applique a ce process lui-meme. Un second lancement echoue proprement avec un message explicite au lieu de capturer silencieusement le port. Message de `process_lock.acquire_lock` generalise ("Une instance tourne deja (PID X, verrou Y.lock)" au lieu de "Une instance du bot...", desormais partage par 2 types de process differents).

**Validation** : 12 nouveaux tests `backtest_lab` (reglages de risque generiques resolus/valides, rejet palier partiel >= take-profit, rejet position x concurrence > 100%, filtre de tendance/ATR actifs/desactives/ignores pour market_making, timeframe libre respecte, timeframe ignore quand le preset en force un, execution bout-en-bout avec tendance+ATR actifs). Verification manuelle navigateur : creation d'un bot de chaque variante testee via le formulaire, rapport de backtest confirmant les valeurs exactes saisies (`max_position_size_pct=0.15`, `trend_filter_ema_period=20`, `atr_period=5`, etc.). Suite complete : 473 tests.

---

### 3.35 EF-55 : stop-loss optionnel reintegre pour `dip_bounce` (Rebond de creux)

**Contexte** : suite a l'ajout du filtre de tendance EMA au backtest (§3.34), l'utilisateur a compare empiriquement un bot `dip_bounce_hourly` reel (ETH/USDT, verrou de gain 5%/4,5%, `max_concurrent_positions=50`) - **100% de reussite sur les trades fermes**, mais **rendement total -18,06%** a cause de 10 positions encore ouvertes en fin de periode totalisant -406,89 de perte latente (contre +217,80 de gain realise) et un drawdown max de 69,2%. Diagnostic partage avec l'utilisateur : le "100% de reussite" est un artefact mecanique de "pas de stop-loss + sortie uniquement sur gain" (un trade ne se ferme jamais en perte, il reste juste ouvert indefiniment) - la vraie mesure de risque est la perte latente non realisee, pas le taux de reussite des trades fermes. Demande resultante : reintegrer un stop-loss, mais **optionnel** (pas force comme avant EF-46/47 qui l'avait explicitement retire).

**Choix retenus** (memes 3 points d'entree deja identifies pour EF-46, cette fois reouverts plutot que fermes) :
- `backtest_lab.py::StrategyPreset` : nouveau champ `default_stop_loss_pct: float | None = 0.02` (valeur appliquee quand le champ est laisse vide ET `supports_stop_loss` est True) - `sma_cross`/`scalp_dip`/`mean_reversion` gardent `0.02` (comportement CLI historique inchange, retro-compatible), `dip_bounce_hourly`/`minute` passent `supports_stop_loss=True` (avant : `False`) avec `default_stop_loss_pct=None` (vide reste desactive, contrairement aux 3 autres). `build_risk_kwargs_and_summary` utilise `preset.default_stop_loss_pct` au lieu du `0.02` fige. `presets_metadata()` expose `default_stop_loss_pct` pour que le dashboard sache quel comportement de champ appliquer par preset.
- `control_server.py::build_config` : la branche qui forcait `stop_loss_pct = None` pour `dip_bounce_hourly`/`minute` ET `buy_and_hold` est scindee - `buy_and_hold` seul garde le forcage total (achat unique jamais revendu, le stop-loss n'a pas de sens dans ce recit) ; `dip_bounce` devient optionnel (`payload.get("stop_loss_pct")` vide => `None`, une valeur => validee comme les autres strategies via `_require_fraction`).
- Dashboard (`reporting/dashboard.py`) : `onStrategyTypeChange` (formulaire de creation) et `onBacktestStrategyChange` (Test/Backtest) ne desactivent plus le champ Stop-loss pour `dip_bounce` - il reste actif, vide par defaut (placeholder "vide = desactive"), avec un message explicite ("Optionnel, vide par defaut... une valeur l'active"). Seul `buy_and_hold` grise encore totalement le champ. Texte de `strategyFieldsHtml` mis a jour ("Stop-loss optionnel" au lieu de "Aucun stop-loss - decision assumee").

**Aucun changement moteur necessaire** : `RiskManager.should_stop_loss`/`Engine._decide` traitent deja `stop_loss_pct` generiquement (`None` => jamais declenche, une valeur => declenche normalement) depuis EF-46 (§3.28) - la fonctionnalite existait deja au niveau moteur, seule la couche formulaire/config l'empechait d'etre utilisee pour ce preset. Comportement des bots existants (`ETHSWING`, `XRP_SWING`, `stop_loss_pct: null` deja en config) strictement inchange : vide reste le defaut, rien ne s'active tout seul.

**Validation** : 2 tests `backtest_lab` mis a jour (`presets_metadata` attend desormais `supports_stop_loss=True`/`default_stop_loss_pct=None` pour `dip_bounce_hourly`), 2 tests `control_server` mis a jour (paiement par defaut du payload de test inclut `stop_loss_pct=0.02` - corrige a `""` pour ne pas casser l'intention "dip_bounce sans stop-loss par defaut" des tests existants) et 2 nouveaux (`stop_loss_pct` vide => `None`, valeur explicite => acceptee et propagee). Verification manuelle navigateur : formulaire de creation ET Test/Backtest, champ actif/vide avec message pour `dip_bounce_hourly` ; backtest reel avec `stop_loss_pct=0.15` confirme un trade ferme a -16,12% (stop-loss reellement declenche) dans le rapport. Suite complete : 475 tests.

---

### 3.36 Bouton "Exporter ces parametres vers un nouveau bot" (Test/Backtest -> Creation)

**Contexte** : apres plusieurs iterations de reglages sur le bot `dip_bounce` dans l'onglet Test/Backtest (stop-loss, take-profit, trailing, filtre de tendance...), l'utilisateur a demande un moyen de reporter directement une config de test satisfaisante dans un vrai bot, sans retaper chaque champ a la main dans le formulaire de Creation.

**Choix retenu** : nouveau bouton sous le rapport de backtest (`reporting/dashboard.py::runBacktestFromForm`), actif uniquement si `CREATABLE_STRATEGY_TYPES` (memes 5 cles que le formulaire de Creation : `sma_cross`, `scalp_dip`, `dip_bounce_hourly`/`minute`, `buy_and_hold`) contient la strategie testee - grise avec une infobulle pour `mean_reversion`/`market_making` (YAML uniquement, jamais promus au formulaire). `exportBacktestToNewBot()` lit l'etat courant de TOUS les champs `bt_*` (general, risque generique, sortie partielle, filtre de tendance, sizing ATR, sizing niveau de prix, parametres specifiques `bt_p_*`/`bt_r_*`), bascule l'onglet principal sur Configuration -> Creation (meme `currentMainTab`/`currentConfigSubTab` que `editBot()`), force un formulaire VIERGE (`editingBotName = null` + suppression de `#manage-bots-root` avant `renderSubTabsAndContent()`, meme reset que `cancelEdit()` - pour ne jamais confondre "exporter vers un nouveau bot" avec une edition en cours), puis reporte chaque valeur dans le champ `f_*` correspondant. Les cles de strategie et les unites (`%` affiches en valeur brute, ex. "0.5" pour 0.5%) sont deja identiques entre les deux formulaires - aucune conversion necessaire, une simple copie de valeur suffit champ par champ. Le nom et le plafond de mise restent a la charge de l'utilisateur (`capital de depart` du backtest est repris comme valeur de depart pour "Plafond de mise", mais reste modifiable).

**Bug reel decouvert et corrige en verifiant la fonctionnalite** : le bouton (attribut `disabled title="..."` construit dans un ternaire JS) utilisait des guillemets echappes (`\"`) a l'interieur d'un template JS lui-meme a l'interieur du gabarit HTML Python (`_MASTER_DASHBOARD_HTML = """..."""`, chaine normale PAS raw) - Python interprete `\"` comme un simple `"` avant meme que le JavaScript ne soit genere, cassant silencieusement la chaine de caracteres JS resultante (`SyntaxError: Missing } in template expression` au chargement du dashboard, page blanche). Corrige en utilisant des guillemets simples JS (`'disabled title="..."'`) pour cette valeur - aucun caractere a echapper, donc aucune interference avec l'echappement Python du gabarit. **Lecon generale pour ce fichier** : toute chaine JS ajoutee dans `_MASTER_DASHBOARD_HTML` doit eviter `\"` (echappement Python actif) - preferer alterner apostrophes/guillemets simples et doubles selon l'imbrication, jamais de backslash.

**Validation** : verification manuelle navigateur - backtest `dip_bounce_hourly` avec stop-loss 12%, seuil de creux 1,5%, filtre de tendance EMA 150 actif ; clic sur "Exporter" confirme que Symbole/Timeframe (verrouille)/Strategie/Seuil de creux/Stop-loss/Filtre de tendance (case cochee, periode 150, section repliable ouverte automatiquement) sont tous correctement reportes dans le formulaire de Creation, message de statut affiche. Suite complete inchangee (475 tests, aucun test unitaire dedie a cette fonction cote JS - non couvert par la suite pytest, verification manuelle uniquement).

---

### 3.37 CT-27 : `flatten_existing_position` creditait a tort le solde de test exchange sur notre cash

**Decouvert** suite a une demande de l'utilisateur ("nettoyer les trades en cours, ca fausse mes chiffres") apres un nettoyage de sa flotte de bots (12 bots reduits a 3 : `BTC_SWING_V2`, `ETH_SWING_V2`, `SOL_SWING_V2`). Investigation : aucune position n'etait reellement ouverte sur aucun des 3 bots - mais `BTC_SWING_V2` affichait une equity de **1272** pour un capital de depart de 1000 (+272), et `ETH_SWING_V2` **1101,57** (+101), chacun avec un seul "trade" a son actif, tague `flatten_on_start`, au P&L quasi nul (-0,27 et -0,067 respectivement).

**Cause reelle** : `PaperExecutor._load_portfolio_from_exchange` (execution/paper_executor.py) initialise le portefeuille a partir du VRAI solde du compte testnet Binance - y compris un eventuel solde de la devise de base (ex: un peu de BTC/ETH offert par le testnet ou reste d'un test manuel anterieur), interprete comme une "position deja ouverte". `main()` (run_paper.py) reinitialise ensuite correctement `portfolio.cash` a `capital_allocated` (ignore le VRAI solde USDT du testnet, qui n'a aucun rapport avec notre capital trace) - **mais ne reinitialisait pas `portfolio.positions`**, qui gardait cette position fantome. `flatten_existing_position` la vendait alors via `executor.place_order()` -> `portfolio.apply_fill()`, qui credite **le produit COMPLET de la vente** (quantite x prix, ex. 272,27 pour 0,00353 BTC a 77132) sur le cash - alors que cette position n'avait jamais ete DEBITEE de notre cash a l'achat (elle ne vient pas de notre capital). Resultat : un gain fictif systematique au tout premier demarrage de chaque bot, proportionnel a la poussiere presente sur le compte testnet a cet instant - jamais detecte avant faute d'avoir un bot deploye avec un solde de base non nul au premier lancement.

**Corrige** (`run_paper.py::flatten_existing_position`) : la position est toujours liquidee REELLEMENT sur l'exchange (evite de laisser trainer un solde qui perturberait un futur redemarrage), via un appel direct `exchange.create_order(...)` (contourne `place_order`/`apply_fill`) - mais n'est plus JAMAIS imputee a notre portefeuille : `executor.portfolio.positions = []` directement, sans passer par le cash ni le P&L ni l'historique de trades. Un `try/except` autour de l'appel exchange gere le cas ou la poussiere est sous le minimum d'ordre accepte (ordre rejete par l'exchange) - la position est quand meme ignoree localement, jamais bloquante.

**Correction des donnees deja corrompues** : suppression manuelle (avec confirmation explicite de l'utilisateur, action irreversible) des lignes `closed_trades`/`orders`/`open_positions` dans `data/BTC_SWING_V2.db` et `data/ETH_SWING_V2.db`, puis redemarrage des 2 bots - `restore_persisted_state` les traite alors a nouveau comme un tout premier lancement (`is_first_ever_run=True`, tables vides), `cash` repart proprement a `capital_allocated`. Verifie : equity = 1000.0 exactement sur les deux apres redemarrage, un seul processus (logique) par bot. Registre du dashboard nettoye au passage d'une entree fantome (`preview_bot`, sans fichier de donnees associe) via `remove_from_dashboard_registry`.

**Validation** : 2 nouveaux tests `test_flatten_on_start.py` (le cash/P&L/historique restent inchanges apres un flatten reussi ; la position est ignoree localement meme si l'ordre exchange echoue). Suite complete : 477 tests.

---

### 3.38 EF-56 : barre de progression pendant un backtest

**Contexte** : demande de l'utilisateur - l'onglet Test/Backtest n'affichait qu'un texte statique ("Test en cours...") pendant l'execution, sans aucune indication de progression, alors qu'un backtest peut prendre du temps (premier telechargement d'un symbole/timeframe, ou plusieurs sous-periodes en mode `--repeat`).

**Contrainte d'architecture** : `control_server.py` est un `ThreadingHTTPServer` synchrone (`http.server`, pas d'ASGI/websocket) - la requete `POST /api/run-backtest` bloque le thread qui la traite jusqu'a la fin du test, impossible d'y streamer une progression au fil de l'eau dans la meme reponse HTTP. **Solution retenue** : exploiter le fait que `ThreadingHTTPServer` traite CHAQUE requete dans un thread separe - une requete `POST` bloquante et une requete `GET` de polling peuvent donc s'executer EN PARALLELE sans rien changer a l'architecture serveur.

**Implementation** :
- `backtest_lab.py::run_backtest_job` gagne un parametre optionnel `progress_callback: Callable[[dict], None] | None = None` (defaut `None`, aucun effet sur le CLI/les tests existants) - appele a chaque etape notable : avant chaque telechargement d'historique (`{"stage": "download", "message": ...}`), avant/apres la simulation d'une periode unique (`{"stage": "running", "current": 0|1, "total": 1}`), et a chaque sous-periode en mode `--repeat` (`{"stage": "running", "current": i, "total": N}`).
- `control_server.py` : nouveau dict partage `_backtest_progress` (proteg par un `threading.Lock`, cle = `job_id` genere cote client) - `_handle_run_backtest` y publie la progression via un callback ferme sur `job_id`, le retire dans un `finally` (succes, erreur ou exception, jamais de fuite). Nouvelle route `GET /api/backtest-progress?job_id=...` qui renvoie l'etat courant (ou `null` si inconnu/deja termine).
- Dashboard (`reporting/dashboard.py`) : `runBacktestFromForm` genere un `job_id` cote client (`bt_${Date.now()}_${random}`), l'ajoute au payload, et demarre un `setInterval` (600ms) qui interroge `/api/backtest-progress` en parallele de l'attente de la reponse POST - `updateBacktestProgressUI` traduit chaque etat en barre : **indeterminee** (animation CSS, pas de pourcentage precis possible) pour `download` et pour `running` a une seule periode (`total <= 1`, aucune granularite fine disponible sans instrumenter le moteur bougie par bougie - juge hors perimetre) ; **pourcentage reel** (`current/total`) pour `running` en mode `--repeat` (`total > 1`), ou chaque sous-periode terminee fait avancer la barre. Nettoyage systematique dans un `finally` cote JS (arrete le polling, masque la barre) quel que soit le denouement.

**Validation** : 3 nouveaux tests `backtest_lab` (sequence d'etapes reportee pour un test simple, `current` 0->N pour un `--repeat`, fonctionne toujours sans callback). Verification manuelle navigateur : backtest sur un symbole jamais telecharge (AVAX/USDT depuis 2022) confirme la barre indeterminee avec le message "Telechargement..." pendant l'attente reelle, requetes de polling visibles dans le reseau au meme moment que la requete POST encore en vol ; test `--repeat=6` confirme (logique verifiee directement) le pourcentage reel par sous-periode. Suite complete : 480 tests.

---

## 4. Structure du projet

```
trading-bot/
├── docs/
│   ├── STB.md
│   ├── STC.md
│   └── MANUEL_UTILISATEUR.md        # guide non technique du dashboard
├── config/
│   ├── example_instance.yml         # une config = une instance d'algo (capital, risque, stratégie, paire)
│   ├── btc_sma_cross_fast.yml       # variante B du comparateur A/B
│   ├── doge_scalp.yml               # exemple de config scalping
│   └── ...                         # une config par bot cree, y compris via le dashboard
├── src/
│   └── tradingbot/
│       ├── engine.py                 # orchestrateur (Engine), journal de decisions
│       ├── data_feed.py              # historique + temps reel (ccxt)
│       ├── process_lock.py           # verrou anti-doublon par instance
│       ├── find_trending.py          # CLI : cryptos tendance (hausses/baisses/volumes)
│       ├── control_server.py         # serveur HTTP local : creer/lancer/arreter/modifier/supprimer un bot
│       ├── analysis/
│       │   ├── monte_carlo.py        # bootstrap Monte Carlo (probabilite de hausse)
│       │   └── probability_gate.py   # filtre optionnel EF-18, avec cache
│       ├── run_backtest.py           # point d'entree CLI backtest
│       ├── run_paper.py              # point d'entree CLI paper trading
│       ├── optimize.py               # CLI : recherche des meilleurs parametres par backtest sur grille
│       ├── strategies/
│       │   ├── base.py               # interface Strategy
│       │   ├── sma_cross.py          # suivi de tendance
│       │   └── scalp_dip.py          # scalping sur creux de prix
│       ├── risk/
│       │   └── risk_manager.py
│       ├── execution/
│       │   ├── base.py               # interface ExecutionAdapter
│       │   ├── backtest_executor.py
│       │   └── paper_executor.py     # + garde-fous exchange (§3.7)
│       ├── portfolio.py              # + historique des trades clotures
│       └── reporting/
│           ├── logger.py             # ecriture SQLite
│           ├── stats.py              # calcul P&L, drawdown, win rate
│           └── dashboard.py          # dashboard.html + dashboard_data/{nom}.js
├── tests/                            # 460 tests a ce jour
├── data_cache/                       # historique telecharge (.parquet), non versionne
├── data/                             # bases SQLite par instance, non versionne
├── logs/                             # sortie des bots lances via le control server, non versionne
├── dashboard_data/                   # donnees generees pour le dashboard, non versionne
├── dashboard.html                    # genere automatiquement, non versionne
├── start_control_server.bat          # lance le serveur de controle (necessaire pour le dashboard interactif)
├── start_btc_swing_bot.bat / start_btc_sma_fast_bot.bat / start_doge_scalp_bot.bat
├── .env.example                      # variables d'environnement attendues (cles API), sans valeurs reelles
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 5. Modes d'exécution et sécurité (ENF-02)

| Mode | Ordres réels ? | Activation |
|---|---|---|
| `backtest` | Non — simulé sur données historiques | Par défaut, sans clé API nécessaire |
| `paper` | Non — simulé sur flux temps réel via Binance **testnet** | Nécessite une clé API testnet (gratuite) — **mode actuellement utilisé pour toutes les instances en cours** |
| `live` | **Oui — argent réel** | **Non implémenté à ce jour.** Conception prévue inchangée : (1) clé API réelle, (2) flag explicite en ligne de commande, (3) variable d'environnement `LIVE_TRADING_ENABLED=true`. Sans les trois, le mode live devra refuser de démarrer. À construire seulement après plusieurs jours de paper trading sans interruption. |

Cette triple confirmation répondra à ENF-02 (le mode réel ne doit jamais être activable par accident) le jour où le mode live sera implémenté.

---

## 6. Gestion du risque (EF-09)

Paramètres configurables par instance (fichier YAML, ou via le formulaire du dashboard) :
- `max_position_size_pct` : taille maximale d'une position (en % du capital de l'instance)
- `stop_loss_pct` : perte max tolérée sur une position avant clôture automatique
- `take_profit_pct` : gain visé avant clôture automatique (optionnel — indispensable pour une stratégie de scalping, qui n'émet elle-même aucun signal de sortie)
- `max_daily_loss_pct` : perte cumulée max sur une journée avant arrêt automatique de l'instance jusqu'au lendemain
- `capital_allocated` : budget virtuel isolé de l'instance (§3.5)
- `fee_pct` : frais de transaction simulés par ordre, défaut 0,1% (§3.13)
- `trailing_stop_pct` : stop suiveur optionnel (§3.15)
- `block_buy_if_any_position_losing` : garde-fou anti-accumulation, actif par défaut (§3.14)

Le Risk Manager est évalué **avant** toute transmission à l'Execution Adapter : un signal de stratégie ne devient jamais un ordre sans passer par cette validation. Tous ces paramètres sont désormais **validés à la création/modification** d'une instance (§3.7 a), et non plus seulement au moment de l'exécution.

**Retour d'expérience** : un take-profit mal dimensionné par rapport au stop-loss (ex. take-profit 40x plus petit que le stop-loss) exige un taux de réussite irréaliste pour être profitable, même hors frais de transaction. Ce n'est pas une erreur technique détectable automatiquement (les deux valeurs sont individuellement valides) — c'est un point de vigilance métier à vérifier manuellement avant de laisser tourner une instance longtemps.

---

## 7. Persistance et traçabilité (ENF-04)

Base SQLite par instance (`data/{instance_name}.db`), tables :
- `orders` (id, timestamp, side, quantity, price, mode, status)
- `equity_curve` (id, timestamp, equity)
- `events` (id, timestamp, level, message) — démarrage/arrêt, liquidation au démarrage

En complément, le dashboard lit un **snapshot léger** régénéré à chaque cycle (`dashboard_data/{instance}.js` : dernier état + 200 derniers points de la courbe + 10 dernières décisions), plutôt que d'interroger SQLite depuis le navigateur — SQLite reste la source de vérité complète et durable, le snapshot JS est une vue rapide pour l'affichage.

**Retour d'expérience (mis à jour par EF-27, §3.18)** : `flatten_on_start` ne déclenche plus systématiquement une vente à chaque démarrage — seulement au tout premier lancement d'une instance (aucun historique, aucune position persistée). À partir de la 2e session, une position ouverte est restaurée telle quelle plutôt que liquidée. Le point de vigilance historique reste valable pour le tout premier lancement (une liquidation administrative d'un solde de test préexistant peut encore apparaître une fois dans l'historique) et pour toute modification volontaire de `capital_allocated` alors qu'une position est ouverte (CT-10 de la STB).

---

## 8. Tests (480 tests à ce jour)

| Type de test | Objet | Répond à |
|---|---|---|
| Tests unitaires stratégies | `SmaCrossStrategy`, `ScalpDipStrategy` : signaux corrects sur des séries de bougies connues | ENF-07 |
| Tests unitaires Risk Manager | Rejet des ordres hors limites, `explain_rejection`, stop-loss/take-profit | ENF-07 |
| Tests unitaires Portfolio | Calcul du P&L par trade clôturé, historique des trades | ENF-07 |
| Tests unitaires Execution | `BacktestExecutor`, `PaperExecutor` (avec un faux exchange injecté) : arrondi de quantité, rejet sous le montant minimum, quantités entières obligatoires (§3.7 b) | ENF-07, ENF-10 |
| Tests unitaires Process Lock | Détection d'un verrou actif, nettoyage d'un verrou obsolète | ENF-03 |
| Tests unitaires Control Server | Validation des paramètres (`build_config`, avec API Binance simulée), détection d'un crash immédiat au lancement, listing des configs | ENF-09, ENF-10 |
| Tests unitaires Monte Carlo / Probability Gate | Cohérence statistique (rendements tous positifs → probabilité 1, déterminisme avec seed), cache, comportement fail-open sur erreur réseau, blocage/autorisation d'achat | EF-18 |
| Tests unitaires Optimizer | Grille de candidats valide (paires courte<longue), filtre de significativité (rejet si trop peu de trades), formatage des résultats | EF-19 |
| Tests unitaires Orders Table | Prix cibles corrects pour position ouverte/clôturée, raison de vente propagée (stop-loss/take-profit/signal), tri par date décroissante | EF-20 |
| Tests unitaires/intégration Multi-positions | Lots distincts créés par achat, fermeture par `lot_id` ou FIFO, équité sommée sur tous les lots, limite `max_concurrent_positions` respectée, sortie stratégie ferme tous les lots, stop-loss/take-profit par lot indépendant | EF-21 |
| Tests unitaires Frais | Déduction du frais à l'achat et à la vente, cumul dans `total_fees_paid`, callback `on_trade_closed` | EF-22 |
| Tests unitaires Anti-accumulation | Rejet d'un achat quand une position existante est en perte, autorisation quand toutes sont gagnantes, `explain_rejection` mise à jour | EF-23 |
| Tests unitaires Stop suiveur | `should_trailing_stop` déclenché après recul depuis `peak_price`, non déclenché avant le seuil | EF-24 |
| Tests d'intégration Risk features | Stop suiveur ferme réellement une position dans la boucle Engine, second achat bloqué pendant qu'un lot est perdant | EF-23, EF-24 |
| Tests unitaires Persistance | `log_closed_trade`/`load_closed_trades`/`load_equity_curve` : écriture, relecture, ordre chronologique | EF-25 |
| Tests unitaires/intégration Persistance positions ouvertes | `save_open_positions`/`load_open_positions` (remplacement complet, pas un journal), `restore_persisted_state` (détection premier lancement vs reprise, calcul du `_next_lot_id`), `compute_restored_cash` (reconstruction exacte du cash) | EF-27 |
| Tests unitaires Graphique de cours | `write_dashboard` expose `price_history` (pas `equity_curve`) au dashboard, `warm_up_strategy` alimente `price_history` avec l'historique de réchauffement | EF-28 |
| Tests unitaires Historique de prix par période | `fetch_price_history` : mapping période → (timeframe, limite) ccxt, rejet d'une période inconnue, cache par (symbole, période) avec exchange injecté (pas d'appel réseau réel) | EF-29 |
| Tests unitaires/intégration Filtre de tendance | `TrendFilter` (calcul EMA, fail-open avant formation, régime haussier/baissier), blocage d'achat dans l'`Engine`, réchauffement (`warm_up_strategy` étend la fenêtre de fetch à `ema_period`), validation `control_server`, `build_trend_filter`/`trend_status` | EF-30 |
| Tests unitaires Optimizer + filtre de tendance | Les grilles `sma_cross`/`scalp_dip` incluent les 4 variantes de filtre de tendance, wiring du `TrendFilter` dans l'`Engine` (espion), présence/absence du bloc `trend_filter` dans la config YAML générée | EF-19, EF-30 |
| Tests unitaires/intégration Sizing ATR | `AtrSizer` (calcul True Range, EMA imbriquées, bornes `[min_size_multiplier, 1.0]`), `size_for_signal` avec multiplicateur, réduction de taille dans l'`Engine` lors d'un pic de volatilité, réchauffement étendu (`baseline_period`), validation `control_server`, `build_atr_sizer`/`atr_sizer_status` | EF-31 |
| Tests unitaires/intégration Sortie partielle | `Portfolio.apply_fill` (répartition proportionnelle du frais d'entrée, lot conservé ouvert, cloture complète après épuisement, non-régression sur une vente complète en un seul ordre), `RiskManager.should_partial_take_profit` (déclenchement unique par lot), intégration `Engine` (priorité aux sorties complètes, stop-loss actif sur le reste), validation `control_server` (palier < take-profit complet) | EF-32 |
| Tests unitaires/intégration Bot d'auto-réoptimisation | Les 4 garde-fous (`is_better_out_of_sample`, `is_due_for_reoptimization`, `has_open_position`, `candidate_from_config`), `propose_reoptimization` de bout en bout (position ouverte → skip, fréquence → skip, config sans edge → proposition écrite, état mis à jour même sans amélioration), `control_server.list_proposals` | EF-33 |
| Tests unitaires/intégration Extension réoptimiseur | Sizing ATR dans la grille (`optimize.py`, wiring `AtrSizer`↔`Engine`), `assign_groups` (équilibré, stable across appels, nettoie les bots supprimés), `merge_proposal_into_config` (conserve capital/warmup, retire les blocs optionnels absents), `apply_proposal_files` (proposition manquante, position ouverte, fusion + redémarrage), `run_all` (applique le groupe auto, laisse le groupe control intact) | EF-34, EF-35 |
| Tests unitaires Optimizer out-of-sample | `split_train_test` respecte le ratio, découpe chronologique (non mélangée), sans chevauchement train/test | EF-26 |
| Tests unitaires Control Server (frais, trailing stop) | Valeurs par défaut et personnalisées de `fee_pct`/`trailing_stop_pct`, rejet hors plage | EF-22, EF-24 |
| Tests d'intégration | Boucle Engine complète en mode `backtest` sur un petit jeu de données, vérifie que le P&L calculé est correct ; hook `on_decision` | EF-03, EF-07, EF-15 |
| Test manuel de recette | Plusieurs instances en mode `paper` tournant en parallèle sur testnet, capital isolé vérifié, dashboard vérifié en conditions réelles | EF-04, EF-06, EF-07, EF-12, EF-14, ENF-03 |

Le détail d'un plan de tests de recette formel (cas de test précis, critères d'acceptation chiffrés) reste à documenter avant d'envisager le mode réel (EF-05).

---

## 9. Points ouverts d'origine (tous tranchés)

| ID | Question | Décision |
|---|---|---|
| PO-1 | Quelle paire crypto pour le MVP ? | **BTC/USDT** — étendu depuis à ETH/USDT et DOGE/USDT |
| PO-2 | Quelle stratégie de départ pour valider le pipeline ? | **Croisement de moyennes mobiles (SMA cross)** — étendu depuis avec `ScalpDipStrategy` |
| PO-3 | Granularité des bougies (1m, 5m, 1h...) ? | **1h** pour le suivi de tendance, **1m/5m** pour le scalping |

## 10. API du serveur de contrôle (référence)

Toutes les routes sont servies sur `http://localhost:8765` (localhost uniquement) :

| Route | Méthode | Usage |
|---|---|---|
| `/dashboard.html`, `/dashboard_data/*` | GET | Sert les fichiers statiques du dashboard |
| `/api/list-configs` | GET | Liste tous les bots connus (`config/*.yml`) avec leur statut en direct |
| `/api/config?name=...` | GET | Retourne la config complète d'un bot (pré-remplissage du formulaire de modification) |
| `/api/launch-bot` | POST | Crée un nouveau bot (valide, écrit le YAML, lance le process) |
| `/api/start-bot` | POST | Démarre un bot déjà configuré (`{config_path}`) |
| `/api/stop-bot` | POST | Arrête un bot (`{name}`), via `taskkill`/`kill` sur le PID du verrou |
| `/api/update-bot` | POST | Modifie un bot existant ; s'il tournait, il est arrêté puis relancé avec les nouveaux paramètres |
| `/api/delete-bot` | POST | Supprime la config d'un bot (refusé s'il tourne) ; conserve son historique SQLite |
| `/api/price-history?symbol=...&range=...` | GET | Historique de prix réel (marché spot Binance) pour le graphique, `range` ∈ {live *(géré côté client)*, 1h, 1j, 1mois, 1an, 5ans, 10ans} — voir §3.19 |
| `/api/list-proposals` | GET | Liste les propositions de réoptimisation en attente (écrites par `python -m tradingbot.reoptimizer`) — voir §3.23 |
| `/api/apply-proposal` | POST | Applique une proposition (`strategy`/`risk`/`trend_filter` uniquement) ; refuse si une position est ouverte |
| `/api/dismiss-proposal` | POST | Supprime une proposition sans l'appliquer |
| `/api/reoptimize-all` | POST | Lance `reoptimizer.run_all()` en arrière-plan pour tous les bots connus (test A/B auto/control) — répond immédiatement, résultats visibles via `/api/list-proposals` — voir §3.23 |

---

## 11. Suite du cycle en V

```
STB ✔
STC ✔
Réalisation ✔ (MVP + extensions multi-algo, dashboard, garde-fous)
   │
   ▼
Tests unitaires / intégration ✔ (460 tests, §8)
   │
   ▼
Tests de recette              ← EN COURS : observation continue des instances en paper trading
   │
   ▼
Mode réel (EF-05)             ← non demarré, conditionné a plusieurs jours de paper trading stable
```

**Prochaine étape** : laisser les instances actuelles tourner sans interruption (chaque redémarrage pollue les statistiques, voir §7) pour accumuler un historique de trades exploitable, avant d'envisager un plan de tests de recette formel puis le mode réel.
