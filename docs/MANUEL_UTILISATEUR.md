# Manuel utilisateur — Dashboard du Trading Bot

Ce document explique comment utiliser le dashboard au quotidien, sans avoir besoin de lire le code ni les documents techniques (STB/STC). Il est **mis à jour à chaque changement visuel ou fonctionnel** de l'interface (voir l'historique en fin de document).

⚠️ **Rappel important** : tout tourne en mode **paper trading** sur le **testnet Binance**. Aucun argent réel n'est engagé, quoi qu'il arrive dans le dashboard.

---

## 1. Démarrage

### 1.1 Lancer le serveur de contrôle (une fois, à chaque session de travail)

Double-clique sur **`start_control_server.bat`** à la racine du projet. Une fenêtre noire s'ouvre et reste ouverte (ne pas la fermer) — c'est ce qui permet au dashboard de créer/démarrer/arrêter des bots.

Sans ce serveur lancé, le dashboard reste consultable (lecture seule) mais l'onglet "Gérer les bots" affichera un message d'erreur.

### 1.2 Ouvrir le dashboard

Ouvre le fichier **`dashboard.html`** (à la racine du projet) dans ton navigateur — double-clic dessus, ou glisser-déposer dans une fenêtre de navigateur.

La page se rafraîchit **automatiquement toutes les 15 secondes**. Pas besoin d'actualiser manuellement, sauf si tu viens de mettre à jour le logiciel lui-même (voir §10).

### 1.3 Lancer un bot existant sans passer par le dashboard

Double-clic sur un des raccourcis à la racine (`start_btc_swing_bot.bat`, `start_doge_scalp_bot.bat`, etc.) — une fenêtre s'ouvre et le bot tourne tant qu'elle reste ouverte.

---

## 2. Vue d'ensemble du dashboard

En haut de la page, une **barre de 4 onglets principaux** :
- **🏠 Accueil** (affiché par défaut à l'ouverture) : statistiques globales et comparatif rapide de tous les bots — voir §3.
- **🤖 Bot** : le détail d'un bot précis, avec un sous-onglet par bot actif ou déjà créé — voir §4.
- **⚙ Configuration** : deux sous-onglets, **Supervision** (démarrer/arrêter un bot existant, propositions de réoptimisation) et **Création** (créer ou modifier un bot) — voir §5.
- **🧪 Test** : un sous-onglet **Backtest** pour tester un bot précis sur une période choisie, sans passer par le terminal — voir §6.

Un onglet principal avec plusieurs sous-onglets affiche une seconde barre, juste en dessous, pour choisir le sous-onglet. L'onglet (et le sous-onglet) sélectionné sont conservés lors des rafraîchissements automatiques.

---

## 3. Onglet "Accueil"

Vue comparative de **tous les bots suivis**, triée par performance (P&L %) — utile pour comparer deux variantes d'une même stratégie (comparateur A/B) ou plusieurs cryptos entre elles. C'est l'onglet affiché par défaut à l'ouverture du dashboard.

- Cartes en haut : nombre de bots actifs, plafonds de mise cumulés, **panier commun disponible**, valeur totale actuelle, P&L global, nombre total de trades.
- Tableau : une ligne par bot avec son plafond de base et son plafond effectif (ajusté selon sa performance), avec un 🏆 sur le meilleur performeur du moment.
- Bouton "Arrêter" directement dans le tableau.

💰 **Panier de capital commun.** Tous les bots piochent désormais dans un même panier d'argent partagé au lieu d'avoir chacun un budget isolé — le champ "Plafond de mise (panier commun)" du formulaire fixe seulement une limite haute par bot, pas une réserve qui lui serait exclusive. Ce plafond s'ajuste ensuite automatiquement à la hausse ou à la baisse (±5% à chaque trade clôturé) selon que le bot performe bien ou mal, une fois qu'il a clôturé au moins 10 trades — le capital se concentre ainsi progressivement sur les stratégies qui marchent. Une garantie technique (réservation avant chaque achat) empêche le panier commun de jamais passer en négatif, même si plusieurs bots achètent au même moment.

✅ **Mise à jour importante : plus de liquidation automatique à chaque redémarrage.** Avant, redémarrer un bot (ou une extinction du PC) vendait systématiquement sa position en cours, ce qui polluait les statistiques avec des "trades" sans rapport avec la stratégie. Maintenant, une position ouverte est **restaurée à l'identique** au redémarrage — la seule exception est le tout premier lancement d'un bot (aucun historique existant), où un ancien solde de test résiduel est encore purgé automatiquement.

⚠️ **Point de vigilance restant** : si tu modifies le "Plafond de mise" d'un bot **pendant qu'il a une position ouverte**, le calcul de son cash de suivi individuel au redémarrage suivant sera faux (voir §4). Ne change ce champ que lorsque le bot n'a aucune position en cours (regarde "Positions ouvertes" avant de modifier). Cela n'affecte que le suivi de performance de CE bot, pas la disponibilité réelle des fonds dans le panier commun.

### 3.1 Rôle de chaque bot actif

**Troisième audit (2026-09-12)** : après un test rétrospectif sur 6 mois répartis entre 2023 et 2026, `ETHAV5mn` et `GAINfoou` se sont révélés négatifs sur l'ensemble de la période (edge quasi nul de leur stratégie à leur fréquence de trading) — **supprimés**. La flotte a été reconstruite en **1 bot par cryptomonnaie du top 10 par capitalisation** (hors stablecoins USDT/USDC etc., qui n'ont pas de mouvement de prix à trader), chaque bot ayant ses propres paramètres `sma_cross` validés out-of-sample par l'outil `optimize` (3 ans d'historique, 1h) :

| Bot | Paire | Validation out-of-sample | Plafond / taille / positions simultanées |
|---|---|---|---|
| `btc_sma_cross_v1` | BTC/USDT | +0,40 % ✅ | 500 / 45 % / 3 |
| `eth_sma_cross_v1` | ETH/USDT | +0,46 % ✅ | 500 / 45 % / 3 |
| `xrp_sma_cross_v1` | XRP/USDT | +0,87 % ✅ | 500 / 45 % / 3 |
| `optimized_dogeusdt_sma_cross` | DOGE/USDT | +1,83 % ✅ | 500 / 45 % / 3 |
| `ada_sma_cross_v1` | ADA/USDT | +1,53 % ✅ | 500 / 45 % / 3 |
| `trx_sma_cross_v1` | TRX/USDT | +0,92 % ✅ | 500 / 45 % / 3 |
| `bnb_sma_cross_v1` | BNB/USDT | -0,73 % ⚠️ | 150 / 15 % / 1 |
| `sol_sma_cross_v1` | SOL/USDT | -2,47 % ⚠️ | 150 / 15 % / 1 |
| `link_sma_cross_v1` | LINK/USDT | -2,09 % ⚠️ | 150 / 15 % / 1 |
| `avax_sma_cross_v1` | AVAX/USDT | -4,94 % ⚠️ | 150 / 15 % / 1 |

⚠️ **Les 4 bots marqués ne montrent AUCUN edge démontré** (performance de validation négative malgré un entraînement favorable — signe classique de surapprentissage, voir STB CT-09/EF-26) : ils existent pour couvrir les 10 plus grosses cryptos comme demandé, mais avec un plafond de mise et une taille de position volontairement réduits. L'allocation dynamique (voir plus haut) réduira encore leur plafond automatiquement s'ils continuent de perdre en paper trading réel.

💰 **Correction de l'utilisation du capital (2026-09-12)** : un rejeu rétrospectif a montré que seulement 8,2% du panier commun était utilisé en moyenne — le plafond et la taille de position des 6 bots validés ont été relevés (voir tableau ci-dessus, 350→500 / 25%→45% / 2→3 positions), portant le capital moyen déployé à 18,1% du panier (+121%) et le P&L mesuré sur les 6 derniers mois de +90,59 à +237,90. Les 4 bots sans edge démontré n'ont volontairement pas été touchés.

`btc_sma_cross_v1` et `optimized_dogeusdt_sma_cross` conservent leur nom et leur historique (`data/{nom}.db`) d'avant cette reconstruction. `btc_sma_cross_fast_v1` (ancien comparateur A/B de `btc_sma_cross_v1`) a été retiré pour ne garder qu'un seul bot par paire, conformément à la demande. `TestETH`, `TestETH2proba`, `doge_scalp_v1`, `Testdodge` avaient déjà été supprimés lors d'audits précédents.

---

## 4. Onglet "Bot"

Un sous-onglet par bot actif ou déjà créé (nom de l'instance) apparaît juste sous les 4 onglets principaux — clique sur un nom pour afficher son détail.

**"Configuration de ce bot"** : un petit volet repliable juste sous le nom du bot (clique dessus pour l'ouvrir) affiche tous ses réglages actuels — symbole, timeframe, stratégie et ses paramètres, gestion du risque, filtres avancés activés — sans avoir à aller dans l'onglet Configuration. Le bouton **"Modifier cette configuration"** en bas du volet t'amène directement à Configuration → Création avec le formulaire déjà pré-rempli pour ce bot ; enregistrer relance le bot avec les nouveaux réglages, exactement comme depuis le sous-onglet Supervision.

| Élément | Signification |
|---|---|
| Badge "Mode paper" | Rappel : aucun argent réel |
| Badge "En cours" (vert) / "Arrêté" (rouge) | Le bot a écrit une mise à jour récemment (< 3 min) ou non |
| Bouton "Arrêter" | Stoppe immédiatement ce bot (n'apparaît que s'il tourne) |
| **Plafond de mise (panier commun)** | La limite haute que ce bot peut viser dans le panier de capital commun (voir §3) — pas un budget qui lui serait réservé. Une petite note "base : X" apparaît en dessous seulement si l'allocation dynamique a déjà fait diverger ce plafond de sa valeur de départ |
| **Investi actuellement** | Combien d'argent est **réellement** immobilisé dans la ou les position(s) ouverte(s) en ce moment (quantité détenue × prix actuel) — la question la plus directe ("j'ai combien dans le trade en cours ?"), absente jusqu'ici du dashboard |
| **Valeur actuelle** | Cash disponible pour ce bot + valeur de la position ouverte au prix actuel |
| **Gain / Perte** | Différence entre valeur actuelle et capital de départ, en valeur et en % |
| **Positions ouvertes** | Nombre de positions distinctes actuellement ouvertes (1 sauf si "Positions simultanées max" > 1) |
| **Trades exécutés** | Nombre de trades **complets** (achat + revente) — un achat seul sans revente ne compte pas encore |
| **Win rate** | % de trades clôturés avec un gain, parmi les trades complets |
| **Drawdown max** | Plus grosse baisse de capital observée depuis un pic, en % |
| **Cours du marché & positions** | Graphique en chandeliers du prix réel de la crypto, comme dans l'onglet Test : un triangle vert marque chaque achat, un triangle rouge chaque vente, un cercle entoure l'achat d'une position encore ouverte — voir §4.2 |
| **Proba. hausse 24h (Monte Carlo)** | N'apparaît que si le filtre de probabilité est activé (§5.2) — probabilité estimée que le prix soit plus haut dans 24h, basée sur 3 ans d'historique |
| **Régime de tendance (EMAxxx)** | N'apparaît que si le filtre de tendance est activé (§5.2) — "Haussier" (vert) si le prix est au-dessus de sa moyenne mobile, "Baissier" (rouge) sinon, "en formation" tant qu'il n'y a pas encore assez d'historique |
| **Sizing volatilité (ATRxxx)** | N'apparaît que si le sizing par volatilité est activé (§5.2) — % de la taille normale actuellement appliquée (100% = volatilité normale, moins si le marché est agité) |
| **Sizing niveau de prix (moyenne du mois)** | N'apparaît que si le sizing par niveau de prix est activé (§5.2) — % de la taille normale actuellement appliqué selon l'écart entre le prix actuel et la moyenne du mois calendaire en cours (plus de 100% si le prix est sous la moyenne, moins s'il est au-dessus) |
| **Tableau "Ordres"** | Sous la courbe (pleine largeur, plus dans un panneau étroit sur le côté) : le détail de chaque position (voir ci-dessous) |
| **Dernières actions** | Les 10 dernières décisions du bot, avec l'heure, l'action (ou l'absence d'action) et sa raison, et l'écart de prix par rapport au cycle précédent |

*Le "Panier commun disponible" (le solde global partagé par tous les bots) n'est plus répété sur chaque bot : il apparaît une seule fois, juste sous l'heure de mise à jour. "Frais payés (cumulés)" et "Position ouverte (total)" (quantité brute) ont été retirés de cette vue — l'information utile (le montant en euros/dollars réellement engagé) est maintenant directement dans "Investi actuellement" et dans la colonne "Montant" du tableau des ordres.*

**Comprendre "Aucun signal de la stratégie"** : c'est l'état normal la plupart du temps — la stratégie a analysé le prix et n'a rien trouvé qui justifie d'acheter ou de vendre à cet instant précis.

**Comprendre "rejeté par l'exchange"** : le montant ou la quantité calculée était trop petit pour être accepté par Binance (chaque crypto a ses propres règles de montant minimum). Le bot continue de tourner normalement, il attend juste un signal viable.

**Comprendre "bloqué par le filtre de probabilité"** : la stratégie voulait acheter, mais la simulation statistique estime la probabilité de hausse à 24h insuffisante par rapport au seuil configuré. N'apparaît que si tu as activé ce filtre (§5.2). Rien d'anormal — c'est exactement son rôle.

### 4.1 Le tableau "Ordres"

Une ligne par position, les positions **ouvertes en premier** (l'argent engagé maintenant, ce qu'on cherche à voir en priorité), puis les clôturées de la plus récente à la plus ancienne :

| Colonne | Signification |
|---|---|
| Statut | 🟢 Ouvert (position en cours) ou 🔴 Vendu (position clôturée) |
| Achat | Prix réel payé à l'achat |
| Quantité | Quantité de crypto achetée sur cette position |
| Montant | Quantité × prix d'achat — combien d'argent a été mis dans ce trade précisément |
| SL visé | Prix de vente qui déclencherait le stop-loss, calculé à partir du prix d'achat et du % configuré |
| Vente réelle | Prix réellement obtenu à la vente — "-" tant que la position est ouverte |
| Raison | Pourquoi la vente a eu lieu : Stop-loss, Take-profit, Trailing stop, Sortie partielle, Signal stratégie (le croisement de moyennes a décidé de vendre, indépendamment des seuils), ou Liquidation (redémarrage) |
| P&L | Gain ou perte réalisé sur cette position — "-" tant qu'elle est ouverte |

*La colonne "TP visé" (take-profit) a été retirée : aucun des bots actuels n'a de take-profit configuré, elle n'affichait donc jamais que "-".*

Ça permet de vérifier concrètement si une vente s'est faite au prix visé ou non (écart dû au fait que le prix est vérifié à chaque bougie fermée, pas en continu — un léger dépassement du seuil est normal).

✅ Depuis l'ajout de la persistance, ce tableau et les statistiques (trades, win rate, P&L, frais) **survivent désormais aux redémarrages** du bot — elles sont rechargées depuis la base de données à chaque démarrage, elles ne repartent plus de zéro. Une position **ouverte** au moment d'une coupure (extinction du PC, crash) est elle aussi restaurée à l'identique désormais, au lieu d'être automatiquement vendue (voir l'avertissement §3) — le bot reprend exactement là où il s'était arrêté.

### 4.2 Le graphique "Cours du marché & positions"

Ce graphique a remplacé l'ancienne "courbe de capital" (jugée peu lisible : elle montrait juste un chiffre qui monte ou descend, sans dire pourquoi). Il affiche maintenant :
- **Les bougies** (depuis le 2026-09-23, même présentation que l'onglet Test) : chacune résume une période — son ouverture, son plus haut, son plus bas et sa clôture. **Verte** si le cours a fini plus haut qu'il n'a commencé, **rouge** sinon.
- **Un triangle vert** pointant vers le haut à l'endroit exact de chaque achat, **un triangle rouge** pointant vers le bas à chaque vente.
- **Un cercle** autour de l'achat d'une position encore ouverte.
- **Les axes** : le prix à gauche, les dates en bas.

Ça permet de voir en un coup d'œil si le bot achète au bon moment par rapport aux mouvements réels du marché.

**Depuis le 2026-09-26, ce graphique est celui de TradingView** (sa bibliothèque gratuite) : **molette** pour zoomer, **glisser** pour se déplacer, et au **survol** d'une bougie, ses quatre valeurs s'affichent en haut à gauche (O = ouverture, H = plus haut, B = plus bas, C = clôture). Les achats sont des flèches vertes, les ventes des flèches rouges, avec leur prix. Le zoom que tu choisis est conservé quand la page se rafraîchit. Si la bibliothèque ne peut pas être chargée (pas d'internet), l'ancien graphique s'affiche à la place.

**Boutons de période** au-dessus du graphique : **Live** (les données en temps réel du bot, granularité fine mais fenêtre courte), **1 heure**, **1 jour**, **1 mois**, **1 an**, **5 ans**, **10 ans**. Les périodes autres que "Live" interrogent l'historique réel du marché (marché spot Binance, pas le testnet dont l'historique est trop court) via le serveur de contrôle — nécessite donc que `python -m tradingbot.control_server` tourne, comme pour créer/modifier un bot. Le résultat est mis en cache une minute pour ne pas surcharger l'exchange si plusieurs onglets sont ouverts sur la même crypto.

Un achat ou une vente antérieur à la période affichée n'apparaît simplement pas : choisis une période plus longue pour le voir.

**Afficher les zones** — trois cases à cocher au-dessus du graphique, que ton navigateur retient :
- **Stop-loss et objectifs** : pour chaque position ouverte, son prix d'achat, et selon les réglages du bot son stop-loss (vente si le cours tombe là), son objectif (vente avec gain), son **trailing stop** (qui monte avec le plus haut atteint depuis l'achat) et son verrou de gain. Les bots « trend_regime » n'ont volontairement ni stop-loss ni objectif : chez eux, seul le prix d'achat s'affiche.
- **Seuils de la stratégie** : les niveaux où la stratégie agit. Pour « trend_regime » : la tendance de fond (le bot vend si le cours passe dessous) et le seuil au-dessus duquel il achète.
- **Ordres manuels** : tes ordres en attente, en pointillés orange.

**Poser un ordre d'achat en cliquant** — clique sur le graphique à la hauteur du prix voulu. Une fenêtre te propose : « acheter si le cours descend sous ce prix ». Si tu confirmes, le bot surveille ce seuil toutes les minutes et achète **lui-même**, au marché, dès que le cours y arrive. Ce qu'il faut savoir :
- l'achat passe par **les mêmes protections que la stratégie** : si le bot a déjà atteint son nombre maximal de positions, ou sa perte du jour, l'ordre est refusé et la raison s'affiche. Les bots actuels sont limités à une position à la fois et sont tous en position : un ordre posé sur eux sera refusé tant qu'ils le restent ;
- une fois acheté, le lot devient une position normale du bot, qui la revendra selon ses propres règles ;
- le cours est vérifié toutes les minutes : un creux très bref entre deux vérifications peut passer inaperçu, et le prix d'achat réel peut différer un peu du seuil ;
- si le cours est **déjà** sous le prix cliqué, la fenêtre te prévient : l'achat partira dans la minute.

Sous le graphique, le tableau **« Ordres manuels sur ce bot »** liste tes ordres : en attente (avec un bouton **Annuler**), exécuté, refusé (avec la raison), ou annulé. Un ordre ne se déclenche qu'une fois.

---

## 5. Onglet "Configuration"

Deux sous-onglets : **Supervision** (démarrer/arrêter un bot existant, propositions de réoptimisation) et **Création** (créer ou modifier un bot).

### 5.1 Sous-onglet "Supervision"

Tableau de tous les bots configurés (`config/*.yml`), avec pour chacun :
- **Démarrer** (s'il est arrêté) ou **Arrêter** (s'il tourne),
- **Modifier** : pré-remplit le formulaire ci-dessous avec ses paramètres actuels (désactivé si le bot tourne — arrête-le d'abord),
- **Supprimer** : supprime définitivement sa config (désactivé si le bot tourne). L'historique des trades en base SQLite (`data/{nom}.db`) est conservé.

**Bouton "Redémarrer tous les bots (recharge le code)"** : arrête puis relance chaque bot **actuellement en cours** depuis sa config sur disque. Utile après une mise à jour du logiciel (nouvelle version de `run_paper.py`, de la stratégie, ou du dashboard lui-même) — un bot déjà lancé tourne avec le code qu'il avait en mémoire à son démarrage, il ne le recharge jamais tout seul. Comme un redémarrage individuel, **une position ouverte est restaurée à l'identique** (voir §4) : ce n'est pas une liquidation. La page se recharge automatiquement quelques secondes après, pour afficher la dernière version de l'interface.

### 5.2 Sous-onglet "Création"

Le formulaire est organisé en 3 blocs : **Général** (nom, symbole, timeframe, stratégie), **Gestion du risque** (les réglages de base, toujours visibles), et **Filtres avancés** — 4 sections repliables (cliquables) : sortie partielle, filtre de probabilité, filtre de tendance, sizing ATR. Clique sur le nom d'une section pour la déplier et voir ses champs.

| Champ | Explication |
|---|---|
| Nom | Identifiant unique du bot (lettres, chiffres, underscore) |
| Type de compte | **Crypto (testnet Binance)** ou **Actions (paper trading Interactive Brokers)** — voir l'encadré ci-dessous pour ce second mode, ajouté le 2026-09-16 |
| Symbole | Paire à trader. Liste déroulante des 10 cryptos les plus courantes (BTC, ETH, XRP, BNB, SOL, DOGE, ADA, TRX, LINK, AVAX, toutes vs USDT) ; choisir "Autre..." fait apparaître un champ texte libre pour une autre paire (ex. `MATIC/USDT`) — doit alors exister réellement sur Binance, une faute de frappe est détectée avec une suggestion automatique. **Pour "Actions"**, la liste déroulante propose 11 actions courantes (TotalEnergies, Orange, Société Générale, Renault, Air France-KLM, ArcelorMittal, Air Liquide, LVMH, L'Oréal, Sanofi, BNP Paribas) ; "Autre..." reste disponible pour un ticker non listé (ex. `RNO.PA` pour Renault) |
| Timeframe | Durée d'une bougie (1 minute à 1 jour). Court = plus réactif, plus de bruit ; long = plus stable, plus lent. **Verrouillé sur "1 jour" pour "Actions"** (voir encadré ci-dessous) |
| Stratégie | **Croisement de moyennes** (suit une tendance, peu de trades), **Scalp sur creux** (achète les petites baisses, vise des gains rapides et fréquents), **Rebond de creux - horaire/minute/journalier**, **Creux vs moyenne** (5 min, sans verrou), **Détecteur de pente** (1 min, trailing 5%) ou **Buy & hold (passif)** — voir §5.3 pour ces dernières |
| Plafond de mise (panier commun) | Limite haute de ce que ce bot peut viser dans le panier de capital commun — pas un budget qui lui serait réservé (voir §3, onglet Accueil) ; s'ajuste automatiquement selon sa performance récente. **Pour "Actions"**, ce panier est totalement séparé de celui des bots crypto |
| Taille position max (%) | Part du capital investie sur un seul trade |
| Stop-loss (%) | Perte tolérée avant vente automatique. **Absent pour "Buy & hold"** (achat unique, jamais revendu). **Optionnel pour "Rebond de creux" (toutes variantes) et "Détecteur de pente"** : vide par défaut (voir §5.3), une valeur saisie l'active exactement comme pour les autres stratégies. **Obligatoire pour "Creux vs moyenne"** (voir §5.3) — sans verrou de gain pour cette stratégie, un stop-loss est la seule protection contre une position qui ne se fermerait jamais |
| Take-profit (%) | Gain visé avant vente automatique. **Indispensable pour la stratégie "Scalp sur creux"**, qui n'a pas d'autre moyen de revendre |
| Perte max journalière (%) | Le bot arrête de trader pour la journée s'il atteint ce seuil de perte cumulée |
| Positions simultanées max | Par défaut 1 (comportement historique : une seule position à la fois). Au-delà de 1, le bot peut ouvrir plusieurs positions en parallèle au lieu d'attendre que la précédente se clôture — voir l'avertissement ci-dessous |
| Trailing stop (%) | Optionnel, désactivé par défaut. Stop-loss "suiveur" : au lieu d'un seuil fixe, il remonte au fur et à mesure que le prix monte, pour sécuriser une partie des gains si le prix redescend ensuite. Ex. 3% : si le prix monte de 10%, la vente automatique se déclenche s'il redescend de plus de 3% depuis son plus haut, même si ça reste au-dessus du prix d'achat |
| Sens du trailing stop | Comment lire le pourcentage du trailing stop. **« % sous le plus haut atteint »** (par défaut) : vend si le cours retombe de ce pourcentage sous son plus haut, même en dessous du prix d'achat. **« % du gain rendu »** : le pourcentage est la part du GAIN que tu acceptes de rendre. Achat à 2000, plus haut à 2100, trailing 50 % : vente à 2050 — la moitié du gain est gardée. Ce seuil monte avec le plus haut et ne descend jamais sous le prix d'achat |
| Armement (mode « % du gain rendu ») | Gain minimum que le plus haut doit avoir atteint avant que le trailing s'active. Vide = dès que les frais d'achat et de vente sont couverts (0,2 %). Utile : sans armement, juste après l'achat, le moindre recul ferait vendre. Mesuré sur 2025-2026 pour le bot ETH : armé à 2 % ou plus, ce mode fonctionne bien ; armé à 0,2 %, il vend et rachète des centaines de fois par semestre et perd de l'argent |
| Frais par ordre (%) | Frais de transaction simulés à chaque achat et vente, par défaut 0,1% (taux standard Binance). Déduit automatiquement du P&L pour un résultat réaliste |
| Timeframe de surveillance des sorties (ex. `5m`) | Optionnel, vide = désactivé. Vérifie le stop-loss/verrou de gain/trailing stop plus souvent que le timeframe du bot (ex. toutes les 5 minutes au lieu d'une fois par heure), sans changer les entrées de la stratégie — doit être plus fin (plus court) que le timeframe choisi plus haut, sinon le formulaire refuse. Corrige un vrai risque : une vérification une seule fois par heure peut vendre bien plus bas que le seuil prévu si le prix chute vite entre deux vérifications. Réutilise le prix déjà récupéré par le bot à chaque cycle, aucune donnée supplémentaire à télécharger en direct |
| Bougies de réchauffement | Historique chargé au démarrage pour que la stratégie ait des données dès le début (évite d'attendre des heures avant le premier signal possible) |

Champs spécifiques au **scalp sur creux** :
- **Lookback** : nombre de bougies utilisées pour calculer la moyenne de référence,
- **Seuil de creux (%)** : chute de prix (par rapport à cette moyenne) qui déclenche un achat.

⚠️ **"Type de compte" — Actions via Interactive Brokers (2026-09-16, demandé par l'utilisateur)**

Choisir "Actions (paper trading Interactive Brokers)" permet de créer un bot qui investit sur une vraie action (ex. TotalEnergies, Renault) au lieu d'une crypto — mais **uniquement en argent fictif** (paper trading), jamais en argent réel. Cette option existe parce que la quasi-totalité des courtiers PEA/CTO français (Bourse Direct, BoursoBank, Fortuneo, Degiro...) n'offrent aucune connexion automatisée — seul **Interactive Brokers** en propose une, avec un PEA conforme à la réglementation française depuis juillet 2024.

**Prérequis, à faire toi-même avant de pouvoir lancer un tel bot** (rien de ceci n'est automatisable) :
1. Ouvrir un compte Interactive Brokers.
2. Installer TWS ("Trader Workstation") ou IB Gateway (plus léger) sur ce PC.
3. Le connecter en mode **PAPER** (jamais LIVE tant que tu ne veux pas engager de l'argent réel).
4. Activer l'API dans Configuration globale → API → Paramètres.
5. Renseigner `IBKR_HOST`/`IBKR_PORT` dans le fichier `.env` du projet (voir `.env.example`).

Sans ça, un bot "Actions" créé échouera au démarrage avec un message clair indiquant que la connexion à TWS/IB Gateway a échoué — ce n'est pas un bug, c'est le comportement voulu (échouer vite et clairement plutôt que de rester bloqué silencieusement).

**Différences avec un bot crypto** : bougies journalières uniquement (pas d'heures de marché à gérer, un jour non ouvré ne produit simplement aucune bougie), quantités en actions entières (pas de fractions comme en crypto), panier de capital totalement séparé du panier crypto, et seulement 4 stratégies compatibles : "Rebond de creux - journalier", "Croisement de moyennes", "Scalp sur creux", "Buy & hold" (les autres imposent un timeframe trop fin, incompatible).

### 5.3 Rebond de creux, Creux vs moyenne, Détecteur de pente, et Buy & hold — stratégies proposées par toi

**Rebond de creux (horaire, minute, ou journalier)** : achète dès que le prix est proche de son plus bas récent — **aucune condition de tendance requise** (plus haussière ni autre) ; puis **hold jusqu'à être rentable** — la seule vente possible est le **verrou de gain** (sauf variante journalière, voir plus bas) : une fois qu'un premier seuil de gain est dépassé, le bot vend dès que ce gain retombe à un second seuil (plus bas), ça sécurise un gain déjà acquis sans le figer à un montant fixe. *(Corrections du 2026-09-14, à la demande de l'utilisateur : (1) la version initiale vendait aussi dès qu'un nouveau plus haut récent était atteint, ce qui pouvait clôturer la position pour un gain minuscule avant même que le verrou ait la moindre chance de s'armer — retiré, pour un vrai "achète et garde, protégé par le verrou de gain" ; (2) l'entrée exigeait aussi que le prix soit au-dessus de sa propre moyenne glissante — retiré, l'entrée ne dépend plus que de la proximité au plus bas récent.)* Trois variantes au choix dans le menu Stratégie :
- **Rebond de creux - horaire** : raisonne sur une fenêtre de 24 bougies d'1 heure (24h). Le timeframe se verrouille automatiquement sur "1 heure".
- **Rebond de creux - minute** : la même logique, mais sur une fenêtre de 60 bougies d'1 minute (1h). Le timeframe se verrouille automatiquement sur "1 minute".
- **Rebond de creux - journalier** (2026-09-16, pour les actions) : la même logique en bougies journalières, mais **la fenêtre de tendance est réglable** (au lieu d'être fixée à 24/60) — la recherche empirique menée sur plusieurs actions a montré qu'elle varie fortement d'une action à l'autre (10 jours pour Renault, 40 jours pour Air France-KLM par exemple). **Pas de verrou de gain** pour cette variante : seuls le Stop-loss (optionnel) et le Trailing stop ferment une position. **Constat honnête** : aucun edge démontré sur des actions en tendance haussière forte ; plus crédible (ça limite les pertes, ce n'est pas un vrai avantage de sélection) sur des actions en baisse ou chahutées — voir le détail dans STC.md §3.47 si ça t'intéresse.

Champs spécifiques :
- **Seuil de creux (%)** : à quel point le prix doit être proche du plus bas de la fenêtre pour déclencher un achat,
- **Armement du verrou de gain (%)** : le gain à partir duquel le verrou s'active,
- **Déclenchement du verrou de gain (%)** : le gain, en dessous du précédent, qui déclenche la vente une fois le verrou armé — doit être strictement inférieur au seuil d'armement,
- **Forcer un trade après N heures sans achat (0 = désactivé)** : si aucun achat n'a eu lieu depuis N heures, le seuil de creux s'assouplit progressivement (double à chaque période supplémentaire écoulée sans achat) jusqu'à finir par déclencher un achat — idée proposée par toi, pour éviter qu'un seuil trop strict laisse le bot inactif indéfiniment. Jamais un achat instantané "à tout prix" : juste un seuil de moins en moins strict.

⚠️ **Pas de stop-loss par défaut (vide), pas un oubli — mais réintégré en option** (demande explicite de l'utilisateur, 2026-09-15) : si le champ "Stop-loss" (§5.2) reste vide, une position n'a que le verrou de gain comme porte de sortie et peut rester ouverte indéfiniment, même en perte. Validation empirique (variante horaire, 10 cryptos, 3 ans, voir [FEUILLE_DE_ROUTE_PERFORMANCE.md](FEUILLE_DE_ROUTE_PERFORMANCE.md) étape 9, **avant le retrait de la sortie sur nouveau plus haut** — à revalider avec le comportement actuel) : résultat mitigé, et ce risque s'est concrètement matérialisé (un trade a perdu jusqu'à 3,2% du capital de test en une seule fois, une position est restée ouverte à la fin de la période testée). Renseigner le champ "Stop-loss" active une protection classique en plus du verrou de gain, si le risque de blocage prolongé ne convient pas.

**Buy & hold (passif)** : achète une seule fois, dès le premier cycle, avec "Taille position max" du "Plafond de mise", puis ne revend jamais — pas de stop-loss, pas de take-profit, aucun réglage de stratégie à renseigner. C'est la version "bot" du benchmark buy & hold déjà utilisé pour juger les autres stratégies tout au long de ce projet : utile pour comparer directement, en conditions réelles, le trading actif à la simple détention.

**Creux vs moyenne (5 min, sans verrou)** — proposée le 2026-09-16 en observant le graphique de cours en direct, où de nombreux pics descendants brefs (quelques dizaines de minutes) sont visibles sans qu'aucune stratégie existante ne les capte ("Rebond de creux" regarde un plus bas glissant sur 24h, trop large pour ce genre de mouvement). Cette stratégie détecte un creux différemment : **l'écart entre le prix et sa moyenne mobile récente** (même calcul que les bandes de Bollinger) — achète dès que le prix passe sous cette bande basse. Le Timeframe se verrouille automatiquement sur "5 minutes" (fenêtre de 12 bougies ≈ 1 heure).

Champs spécifiques :
- **Fenêtre (bougies)** : nombre de bougies 5 min utilisées pour calculer la moyenne (12 par défaut ≈ 1h),
- **Largeur des bandes (écarts-types)** : à quel point le prix doit s'écarter de la moyenne pour compter comme un creux (2,0 par défaut — plus petit = plus sensible, plus de trades).

⚠️ **Aucune sortie gérée par la stratégie elle-même** — contrairement à "Rebond de creux" (verrou de gain) : ici, seuls le **Stop-loss** et le **Trailing stop** (§5.2) peuvent fermer une position. C'est pourquoi le **Stop-loss est obligatoire** pour cette stratégie (actif à 2% par défaut, pas de case pour le désactiver) — sans lui et sans verrou de gain, une position perdante ne se fermerait jamais.

**"Positions simultanées max" pré-rempli à 10** (au lieu de 1) dès que cette stratégie est choisie : testé le 2026-09-16, avec une seule position autorisée, la première position ouverte bloque toute nouvelle entrée jusqu'à son stop-loss (rarement déclenché) — la stratégie devient quasi inactive, un seul trade par semaine environ. **Recherche empirique menée sur plusieurs périodes** : aucun réglage de fenêtre/écarts-types testé n'a démontré un avantage fiable et durable — un résultat qui semblait bon sur 2 mois s'est effondré sur une période de 5,5 mois. À utiliser avec cette limite en tête, comme les autres stratégies de ce projet.

**Détecteur de pente (1 min, trailing 5%)** — proposée le 2026-09-16, idée directe de l'utilisateur : "un détecteur de pente, plus la pente est élevée, plus la baisse va être importante... si entre 2 bougies de 1 min on a une grosse pente alors on achète... on garde l'ordre et on vend sur le trailing à 5%". Compare la clôture de la bougie courante à celle d'il y a N bougies **1 minute** (2 par défaut = la bougie précédente immédiate) : si la baisse dépasse le seuil réglé, achat immédiat. Le Timeframe se verrouille automatiquement sur "1 minute".

Champs spécifiques :
- **Seuil de pente (%)** : à partir de quelle baisse (en %) entre les 2 bougies comparées l'achat se déclenche (0,5% par défaut — plus petit = plus sensible, plus de trades).
- **Nombre de bougies pour mesurer la pente** : sur combien de bougies la pente est mesurée (2 par défaut = comparaison à la bougie précédente immédiate). Ajouté le 2026-09-16 après avoir visualisé une journée réelle (voir capture partagée) où plusieurs achats étaient en fait partis sur une tendance baissière continue, pas une chute isolée — élargir cette fenêtre (ex: 5 bougies) lisse le bruit d'une seule minute.
- **Limiter à 1 achat par pente continue** (case à cocher, décochée par défaut) : sur une dérive baissière continue, la condition de pente peut rester vraie à plusieurs bougies d'affilée — sans cette case, la stratégie rachète à chaque bougie qualifiante et empile plusieurs positions sur la MÊME tendance au lieu d'une seule. Cochée, un seul achat par épisode de chute continue ; se réarme dès que la chute s'interrompt (même brièvement), prêt pour le prochain épisode.

⚠️ **Aucune sortie gérée par la stratégie elle-même** — "garder l'ordre" veut dire que la stratégie n'a pas de logique de vente propre, PAS qu'elle attend longtemps avant de vendre : le **Trailing stop** (§5.2) est armé dès l'achat (il suit le plus haut atteint depuis l'entrée) et vend dès que le prix retombe de ce pourcentage sous ce plus haut — donc dès qu'un gain apparaît et se retourne, la vente peut être immédiate. Le champ "Trailing stop" se pré-remplit à **5%** (demande explicite) si tu ne l'as pas déjà modifié. Le **Stop-loss** reste optionnel (filet de sécurité, vide par défaut, comme "Rebond de creux").

⚠️ **"Nombre de bougies" testé empiriquement (2 vs 5), constat honnête** : élargir à 5 bougies augmente le rendement moyen sur plusieurs périodes (ETH/BTC) mais aussi fortement la variance - le pire cas par période est environ 4 fois plus large, et la médiane reste négative dans les deux cas. La moyenne plus haute vient de 1-2 périodes exceptionnelles, pas d'une amélioration régulière. Le défaut reste à 2 (comportement d'origine) - à tester au cas par cas plutôt qu'à considérer 5 comme un meilleur réglage.

⚠️ **"Limiter à 1 achat par pente continue" testé empiriquement, constat honnête** : avec le réglage par défaut (2 bougies), l'effet est quasi nul sur plusieurs périodes testées - une comparaison à la seule bougie précédente reste rarement vraie plusieurs bougies d'affilée sur un marché réel, donc peu de doublons à supprimer. Avec une fenêtre large (ex: 7 bougies), l'effet est plus net sur l'exemple testé (1 seule journée : 6 trades → 4, rendement -0,16% → +0,01%) mais un seul jour ne suffit pas à conclure à un avantage général. Combine surtout bien avec un "Nombre de bougies" élevé.

**Recherche empirique menée sur plusieurs périodes (ETH/BTC, 2026-09-16)** : aucun réglage testé (trailing 1,5%, 3% ou 5%) ne démontre un avantage fiable et durable — le rendement moyen par période reste proche de zéro, voire négatif. Resserrer le trailing (le rendre plus réactif) **dégrade** le résultat au lieu de l'améliorer : sur une granularité d'1 minute, le bruit normal du marché fait sortir la position avant qu'un vrai rebond n'ait eu le temps de se développer. Le réglage par défaut à 5% (celui demandé initialement) reste le meilleur des 3 testés, sans pour autant être un réglage optimal démontré — à utiliser avec cette limite en tête.

**Filtre de probabilité (optionnel)** : coche "Filtre de probabilité" pour bloquer automatiquement un achat si une simulation statistique (basée sur 3 ans d'historique) estime que la probabilité de hausse du prix dans les prochaines 24h est sous le seuil que tu définis (55% par défaut).

**Filtre de tendance (optionnel)** : coche "Filtre de tendance" pour bloquer automatiquement un achat si le prix est actuellement sous sa moyenne mobile (régime baissier) — évite d'acheter à contre-courant d'une tendance de fond. La "Période de l'EMA" (200 bougies par défaut) contrôle la réactivité : plus elle est courte, plus le filtre réagit vite mais peut se faire piéger par de petites fluctuations ; plus elle est longue, plus il suit une tendance de fond stable mais réagit lentement à un vrai retournement.

⚠️ **Ce que le filtre de tendance ne fait pas** : un backtest comparatif (voir [FEUILLE_DE_ROUTE_PERFORMANCE.md](FEUILLE_DE_ROUTE_PERFORMANCE.md)) a montré qu'il réduit nettement le nombre de trades et les pertes maximales, mais qu'il ne rend pas une stratégie sans edge rentable — sur la période testée (2024-2026 réelle), les deux stratégies restaient négatives, filtre activé ou non. Traite-le comme un garde-fou qui limite la casse, pas comme un signal qui garantit un gain.

**Sizing par volatilité (optionnel)** : coche "Sizing par volatilité" pour que la taille d'une position soit automatiquement réduite quand le marché est plus agité que d'habitude (mesuré par l'ATR, une mesure standard de volatilité) — jamais plus grande que "Taille position max", seulement plus petite en période agitée. La "Taille minimum" (20% par défaut) empêche de descendre à une position quasi nulle même en cas de volatilité extrême.

⚠️ **Résultat mitigé, contrairement au filtre de tendance** : un backtest comparatif a montré que ce réglage aide dans le pire cas connu (accumulation de pertes en multi-positions) mais coûte légèrement en rendement sur des configs déjà rentables — il freine aussi les mouvements de marché favorables, pas seulement les défavorables. Aucun bot réel de ce projet ne l'active à ce jour ; à tester au cas par cas plutôt qu'à activer systématiquement.

**Sizing par niveau de prix (optionnel, idée proposée par toi)** : coche "Sizing par niveau de prix" pour que la taille d'une position varie selon le prix actuel comparé à la moyenne du mois calendaire en cours — **plus grande** si le prix est sous cette moyenne (on met plus sur un creux relatif du mois), **plus petite** s'il est au-dessus. Contrairement au sizing par volatilité, celui-ci peut aussi bien agrandir que réduire la position : les bornes "Taille minimum"/"Taille maximum" (50%/150% par défaut) encadrent l'ampleur de l'effet dans les deux sens. La moyenne se réinitialise au 1er de chaque mois — en début de mois, elle est basée sur peu de données (plus bruitée), assumé.

⚠️ **Non testé empiriquement à ce jour** : contrairement aux autres filtres avancés, celui-ci vient d'être ajouté et n'a pas encore été validé sur données historiques — traite tout résultat comme une première expérimentation, pas comme une piste confirmée.

**Sortie partielle (optionnel)** : renseigne un "Palier de sortie partielle" pour vendre automatiquement une FRACTION de la position (50% par défaut, réglable) dès qu'un premier gain est atteint, et laisser le reste continuer avec le stop-loss/trailing stop normal. Doit être strictement inférieur au "Take-profit" complet si les deux sont configurés (sinon le take-profit se déclencherait toujours en premier). Ne se déclenche qu'une seule fois par position.

⚠️ **Compromis risque/rendement réel, pas une amélioration gratuite** : un backtest comparatif a montré que la sortie partielle réduit le drawdown de 30 à 35% sur des stratégies suiveuses de tendance déjà rentables, mais divise leur rendement par environ 2 — sécuriser une partie du gain tôt coupe dans les grandes tendances qui font l'essentiel du profit. C'est un choix légitime pour un profil plus prudent (moins de volatilité, moins de rendement), pas une option à activer sans réfléchir. Aucun bot réel de ce projet ne l'active à ce jour.

⚠️ **"Positions simultanées max" > 1, à utiliser avec prudence.** Test réel effectué sur DOGE/USDT (scalp sur creux) : avec 1 position, +5,21% sur 3 ans ; avec 5 positions simultanées, **-34,68%** sur la même période. Pourquoi : le bot continue d'ouvrir de nouvelles positions à chaque creux détecté, même s'il en a déjà plusieurs en perte — pendant une baisse prolongée, ça multiplie les pertes au lieu de les limiter. Ce n'est pas un réglage à activer "pour aller plus vite" : c'est une fonctionnalité d'expérimentation pour explorer les capacités du système, à tester en backtest avant d'y engager du capital réel.

✅ **Garde-fou automatique (toujours actif)** : suite au constat ci-dessus, le bot refuse désormais d'ouvrir une nouvelle position tant qu'au moins une position déjà ouverte est en perte — même si "Positions simultanées max" le permettrait. Ça n'empêche pas complètement d'accumuler des pertes (les positions ouvertes avant qu'elles ne passent en perte restent en place), mais ça évite d'en rajouter une couche pendant une baisse déjà en cours. Ce garde-fou ne se désactive pas depuis le formulaire.

⚠️ **Ce filtre n'est pas une boule de cristal.** Il extrapole la volatilité et la tendance passées sur 3 ans — ce n'est pas une prédiction fiable du marché. Sur BTC/USDT par exemple, la probabilité mesurée tourne généralement autour de 50-51% (le marché n'a pas de biais fort à la hausse ou à la baisse sur cet horizon), donc un seuil à 55% bloquera la plupart des achats la plupart du temps. C'est volontaire : ce filtre sert de garde-fou supplémentaire, pas de signal d'achat principal — la stratégie (SMA cross, scalp) reste ce qui déclenche l'intention d'achat, le filtre ne fait que la confirmer ou la bloquer.

⚠️ **Point de vigilance non détecté automatiquement** : un take-profit beaucoup plus petit que le stop-loss (ex. 0,05% contre 2%) exige un taux de réussite quasi impossible pour être rentable. Vérifie que le rapport entre les deux reste raisonnable (le bot `doge_scalp_v1` fourni utilise 0,5% / 1%, à titre de repère).

Clique sur **"Lancer le bot"**. Si tout est valide, le bot démarre en quelques secondes (le formulaire vérifie aussi que le bot ne plante pas immédiatement avant de confirmer).

### 5.4 Modifier un bot

Clique sur **"Modifier"** dans la liste du sous-onglet Supervision : le dashboard bascule automatiquement sur le sous-onglet Création avec le formulaire pré-rempli. Change ce que tu veux, puis clique sur **"Enregistrer les modifications"**. Si le bot tournait, il est automatiquement arrêté puis relancé avec les nouveaux paramètres (ce qui liquide sa position en cours, voir l'avertissement §3).

Si tu renommes un bot, l'ancien nom disparaît de la liste des sous-onglets de l'onglet Bot (ce n'était pas le cas avant une correction — un ancien nom pouvait rester affiché indéfiniment).

---

## 6. Onglet "Test"

Un seul sous-onglet pour l'instant : **Backtest**.

### 6.1 Sous-onglet "Backtest"

Teste un bot précis (type de bot, devise, exchange, période, capital, paramètres) directement depuis le dashboard, sans terminal — c'est le même moteur que l'outil en ligne de commande `backtest_lab` (voir §9.1), juste avec un formulaire à la place des options en ligne de commande.

| Champ | Explication |
|---|---|
| Type de bot | La liste complète des stratégies testables (croisement de moyennes, scalp sur creux, retour à la moyenne, market making, rebond de creux horaire/minute, buy & hold) — les champs qui suivent s'adaptent automatiquement au choix |
| Symbole / Exchange | Paire à tester — même liste déroulante des 10 cryptos les plus courantes que le formulaire de création, avec "Autre..." pour en saisir une autre — et exchange source de l'historique (`binance` par défaut) |
| Timeframe | Comme dans le formulaire de création (§5.1) : librement réglable, sauf pour "Rebond de creux" qui l'impose (1h ou 1m selon la variante) et se grise automatiquement avec un message explicatif |
| Début / Fin | Période à tester. "Fin" vide = jusqu'à maintenant |
| Capital de départ | Capital de simulation pour ce test (indépendant du panier commun réel) |
| Sous-périodes | 1 = un seul test sur toute la période ; N > 1 découpe la période en N tronçons égaux et rejoue le test sur chacun indépendamment — utile pour vérifier qu'un bon résultat ne repose pas sur une seule période chanceuse |
| Positions simultanées max | 1 par défaut (une seule position à la fois). Au-delà, le bot peut ouvrir plusieurs positions en parallèle au lieu d'attendre que la précédente se clôture — utile pour une stratégie qui reste souvent bloquée en attente d'une seule position (ex. "Rebond de creux" sans stop-loss). Absent pour "Market making" (notion sans objet). À tester avec prudence : peut accumuler des pertes corrélées en marché baissier, voir §5.2 |
| Taille position max / Perte max journalière / Trailing stop / Frais par ordre | Mêmes réglages de risque que le formulaire de création de bot (§5.2), désormais testables avant de déployer un vrai bot. Absents pour "Market making" |
| Sortie partielle (scale-out) | Optionnel, absent pour "Market making" — vend une fraction du lot dès un premier gain atteint, le reste continue avec le stop-loss/trailing stop normal. Même réglage que §5.2 |
| Filtre de tendance (EMA) | Optionnel, absent pour "Market making" — bloque un achat si le prix est sous sa moyenne mobile exponentielle. Même réglage que §5.2 |
| Sizing par volatilité (ATR) | Optionnel, absent pour "Market making" — réduit la taille d'une position en période de forte volatilité. Même réglage que §5.2 |
| Sizing par niveau de prix (case à cocher) | Optionnel, absent pour "Market making". Une fois coché : "Taille minimum"/"Taille maximum" (50%/150% par défaut) — module la taille de chaque position selon l'écart entre le prix actuel et la moyenne du mois calendaire en cours (plus grande sous la moyenne, plus petite au-dessus). Même réglage que dans le formulaire de création de bot (§5.2), pour tester avant de déployer un vrai bot |
| Timeframe de surveillance des sorties (ex. `5m`) | Optionnel, vide = désactivé, absent pour "Market making". Vérifie le stop-loss/verrou de gain/trailing stop sur des bougies plus fines que celles utilisées pour les entrées (ex. toutes les 5 minutes au lieu d'une fois par heure) — corrige un vrai risque : une vérification une seule fois par heure peut vendre bien plus bas que le seuil prévu si le prix chute vite entre deux vérifications. Les entrées de la stratégie ne changent pas. Télécharge une deuxième série de bougies (peut prendre du temps la première fois) |
| Stop-loss / Take-profit | Absents seulement pour "Buy & hold" (achat unique, jamais revendu). Pour "Rebond de creux", le stop-loss est optionnel : vide par défaut (décision historique de cette stratégie), une valeur saisie l'active comme pour les autres stratégies |
| Paramètres de la stratégie / de risque spécifiques | Champs propres à la stratégie choisie, avec une valeur par défaut pré-remplie |

Le **filtre de probabilité (Monte Carlo)** du formulaire de création (§5.2) n'apparaît volontairement pas ici : son calcul se base sur "aujourd'hui moins 3 ans", pas sur la période testée, ce qui fausserait le résultat (un backtest sur 2025 verrait des données de 2026). Reste testable seulement en paper trading réel pour l'instant.

Clique sur **"Lancer le test"**. Une barre de progression apparaît pendant l'exécution : animée (sans pourcentage précis) pendant le téléchargement de l'historique ou la simulation d'une période unique, et avec un vrai pourcentage ("Sous-période 3/6"...) quand "Sous-périodes" est réglé à plus de 1. Le rapport s'affiche directement sous le formulaire : rendement, comparaison au simple fait d'avoir acheté et gardé (buy & hold) sur la même période, drawdown, puis un bloc "Trades" qui montre aussi les points négatifs plutôt que de les cacher (pire trade, durée de détention la plus longue, position encore ouverte en fin de période). Il est aussi enregistré dans `backtest_reports/` (chemin affiché sous le rapport).

Sous le rapport, le bouton **"Exporter ces paramètres vers un nouveau bot"** bascule directement vers Configuration → Création avec tous les réglages du test déjà remplis (symbole, timeframe, paramètres de stratégie, gestion du risque, filtres avancés) — reste à donner un nom et vérifier le plafond de mise avant de lancer. Grisé pour "Retour à la moyenne" et "Market making", pas encore créables depuis un formulaire (YAML uniquement).

**Graphique en chandelles (2026-09-16, demandé par l'utilisateur)** — pour un test sur une **période unique** (Sous-périodes = 1), un graphique apparaît sous le rapport : les vraies bougies (ouverture/plus haut/plus bas/clôture) de la période testée, avec un triangle vert à chaque achat et un triangle rouge à chaque vente ; un cercle marque une position encore ouverte en fin de période. Deux curseurs "Début de la fenêtre (%)"/"Fin de la fenêtre (%)" permettent de zoomer sur une plage précise sans relancer le test (pratique pour examiner un trade en détail), et une case à cocher permet de basculer entre l'affichage en bougies et une simple courbe de clôture. **Absent en mode "Sous-périodes" > 1** : il faudrait un graphique par sous-période, pas encore implémenté.

**Mesure de pente au clic (2026-09-16, demandé par l'utilisateur)** — directement sur le graphique, sans bouton : clique sur une 1<sup>re</sup> bougie, puis sur une 2<sup>e</sup>, et la variation de clôture entre les deux s'affiche automatiquement (en %, coloré vert si positif/rouge si négatif) dans un encart sous le graphique, avec les deux points reliés par un trait pointillé sur le graphique lui-même. Un 3<sup>e</sup> clic recommence une nouvelle mesure. Pratique pour vérifier la pente réelle entre 2 points précis (par exemple pour comparer au seuil réglé pour "Détecteur de pente", §5.3). ⚠️ Si le graphique est très zoomé arrière, chaque point cliquable peut représenter plusieurs bougies réelles regroupées (voir ci-dessus) — zoomer avant de mesurer donne un résultat plus précis.

⚠️ Le premier test sur une devise/timeframe jamais utilisée peut prendre du temps (téléchargement de l'historique) — les tests suivants sur la même combinaison sont quasi instantanés (mis en cache localement). Comme pour `optimize`, un bon résultat sur une période passée n'est jamais une garantie pour l'avenir. Le filtre de tendance (EMA) et le sizing ATR démarrent "à froid" en backtest (pas d'historique avant la période testée pour les réchauffer, contrairement au paper trading) — leurs tout premiers effets dans le test peuvent donc différer légèrement d'un bot réel déjà rodé.

---

## 7. Onglet "Investissement"

Cet onglet gère un type de bot à part, qui ne ressemble pas aux autres : au
lieu d'essayer de repérer le bon moment pour acheter, il **verse une somme
fixe chaque mois** sur une répartition d'actions que tu as choisie, et **ne
vend jamais parce que ça baisse**.

Pourquoi ce choix : toutes les recherches menées dans ce projet (sur les
cryptos comme sur les actions, jusqu'à 972 combinaisons testées d'un coup)
donnent le même résultat une fois vérifiées sur des périodes que le réglage
n'a pas servi à choisir — aucune stratégie testée ne fait mieux, de façon
reproductible, qu'un panier diversifié acheté et gardé. Ce bot ne prétend
donc pas battre le marché. Il automatise seulement les trois choses qui
améliorent vraiment un résultat sans avoir besoin de deviner quoi que ce
soit : verser régulièrement sans se demander si « c'est le bon moment »,
revenir vers la répartition visée, et mesurer honnêtement.

> **Argent fictif uniquement.** Comme les bots actions classiques, il passe
> ses ordres sur le compte **paper** d'Interactive Brokers. Les ports du
> compte réel sont refusés par le logiciel lui-même.

### 7.1 Sous-onglet "Suivi"

Une fiche par bot, avec :

- **Total versé** : la somme de tous tes versements mensuels.
- **Valeur** et **Gain** : ce que ça vaut aujourd'hui, et l'écart.
- **Rendement / an** : le rendement annuel *pondéré par les flux*. C'est
  important : comme tu ajoutes de l'argent au fil des mois, un simple
  « pourcentage de gain » serait trompeur (l'argent versé le mois dernier
  n'a pas eu le temps de travailler). Ce calcul en tient compte.
- **Baisse max subie** : la pire chute traversée depuis le début. À regarder
  en face — sur le panier donné en exemple, elle atteint 50 %.
- **Frais payés** : cumul réel. Avec de petits versements, les frais sont un
  poste qui compte vraiment.
- **Le tableau des lignes** : combien de titres tu détiens, leur valeur, le
  poids **réel** de chaque ligne et son poids **cible**, et l'écart entre
  les deux (affiché en rouge s'il sort de la bande de tolérance).

La valorisation utilise les **derniers cours connus**, c'est-à-dire ceux du
dernier passage du bot, pas le cours de la seconde : ce bot n'agit qu'une
fois par mois, l'afficher en direct n'aurait pas de sens. La date est
indiquée sous le tableau.

Deux boutons :

- **« Simuler le passage du jour »** : montre exactement ce que le bot
  ferait aujourd'hui (quels ordres, à quel prix, ce qu'il resterait en
  liquidités). **N'envoie rien et n'enregistre rien** — tu peux le lancer
  autant de fois que tu veux, ça ne consomme pas le versement du mois. Ça
  fonctionne même sans TWS installé.
- **« Exécuter réellement (compte paper) »** : passe les ordres pour de
  vrai sur le compte paper. Demande une confirmation. Nécessite TWS ou IB
  Gateway lancé et connecté en mode paper.

Relancer l'exécution deux fois dans le même mois ne verse **pas** deux fois :
le versement est enregistré par mois, une bonne fois pour toutes.

> **Deux choses à savoir avant de cliquer « Exécuter réellement ».**
>
> **Le suivi peut afficher du faux si un ordre se passe mal.** C'est arrivé
> le 18/09/2026 : le courtier avait bien acheté deux actions mais annonçait
> « ordre annulé », et le bot a enregistré un portefeuille vide avec de
> l'argent qu'il n'avait plus. Le bot croit désormais les **exécutions** du
> courtier plutôt que son message de statut, et te signale l'incohérence.
> Par sécurité, il compare aussi ses positions à celles du courtier avant
> chaque exécution, et **refuse de passer le moindre ordre** en cas d'écart.
>
> **Le compte paper ne facture aucune commission.** Le vrai courtier prend
> 3 € minimum par ordre ; le paper ne prélève rien. Tes résultats en paper
> seront donc **meilleurs que la réalité**, exactement du montant des frais.
> C'est pour ça que le champ « Frais minimum » existe : il sert à ce que le
> suivi reste honnête même quand le courtier ne prélève rien.

### 7.1 bis Ce que montre l'écran, et ce que tu peux y faire

**Le graphique du haut** compare les six lignes du panier. Chacune part de
0 % au début de la période choisie (1 mois à 5 ans). C'est fait exprès :
comparer un cours de 7 € et un de 400 € côte à côte n'apprendrait rien, alors
qu'en pourcentage d'évolution ils se comparent vraiment. La légende donne le
nom de chaque ligne et sa performance sur la période ; survole une courbe pour
retrouver son nom.

**Une carte par action**, avec :

- Le **cours actuel**, et ton gain ou ta perte sur cette ligne.
- Le **prix de revient** : ce que l'action t'a réellement coûté en moyenne,
  frais compris. C'est la seule référence qui compte — un cours de 79 € ne dit
  rien tant qu'on ne sait pas si tu as payé 70 ou 85. Il apparaît aussi en
  pointillés sur la petite courbe.
- La **barre d'allocation** : la part réelle de cette ligne dans ton panier,
  avec un repère vertical sur la part visée. L'écart passe en orange s'il
  dépasse ta bande de tolérance.

**Les boutons**, du plus anodin au plus engageant :

- **− / + et « Montant exact… »** changent ton versement mensuel. Ça s'applique
  au prochain versement, rien n'est engagé sur le coup. En dessous de 50 €/mois
  un avertissement s'affiche : les 3 € de frais par ordre dépasseraient 6 % de
  ton versement.
- **« Vendre la moitié » / « Tout vendre »** sur chaque carte passent un
  **vrai ordre** sur le compte paper, hors du versement mensuel. Une
  confirmation te le rappelle. Hors des heures d'ouverture de la place,
  l'ordre est refusé et te le dit. Vendre ne rend **pas** le versement du mois
  à nouveau disponible.
- **« Remettre le panier à zéro »** efface les positions, les ordres et les
  versements enregistrés du bot — le versement du mois redevient disponible.
  L'historique est **sauvegardé** dans un fichier de secours, rien n'est perdu
  définitivement. **Attention** : ce bouton ne vend rien. Les actions restent
  chez le courtier, et le bot refusera de passer des ordres tant que ses
  comptes ne correspondent pas aux siens. Vends d'abord, remets à zéro ensuite.

Le tableau de chiffres d'avant est toujours là, replié sous
« Tableau détaillé des lignes ».

### 7.2 Sous-onglet "Réglages"

Pour créer un bot, choisis « + Nouveau bot », sinon sélectionne un bot
existant pour le modifier ou le supprimer.

- **Allocation cible** : une ligne par action, avec un poids. Les poids sont
  relatifs — `1 / 1 / 1` donne trois lignes égales, `2 / 1` donne deux tiers
  / un tiers. **C'est le réglage le plus important de toute la page** : il
  pèse bien plus lourd sur ton résultat que tous les autres réunis. Le
  panier proposé par défaut est très concentré (grandes valeurs Euronext
  françaises et néerlandaises, aucune diversification géographique) — il
  sert d'exemple, pas de conseil.
- **Versement mensuel** : prélevé au premier jour d'ouverture de chaque mois.
- **Ordre minimum** : en dessous de ce montant, aucun ordre n'est passé et
  l'argent attend le mois suivant. Utile parce qu'un petit ordre paie
  proportionnellement beaucoup de frais.
- **Répartition du versement** : « concentrer sur les lignes en retard » ou
  « répartir selon les poids cibles ». Les deux donnent le même rendement
  (vérifié sur 6 périodes). Mais répartir 200 € sur 6 lignes fait 33 € par
  ligne, souvent moins que le prix d'une seule action : l'argent reste alors
  en attente. D'où le choix de concentrer par défaut pour de petits
  versements.
- **Bande de tolérance** : si une ligne s'écarte de plus de N points de sa
  cible, le bot allège ce qui a trop monté pour racheter ce qui est en
  retard. Laisse vide pour ne jamais vendre. **Laissée vide par défaut
  depuis le 2026-09-18** : une fois les frais réels du courtier mesurés
  (3 € minimum par ordre, plus 0,4 % de taxe sur chaque rachat), rééquilibrer
  s'est révélé coûter 2 à 4 points de rendement par an — mesuré sur quatre
  dates de départ différentes, à chaque fois perdant. La raison est simple :
  rééquilibrer vend ce qui monte pour racheter ce qui baisse, et paie des
  frais aux deux bouts. Tu ne verras donc plus de ventes dans le suivi, sauf
  si tu remets une valeur ici.
- **Intervalle minimum** : au plus un rééquilibrage tous les N jours (90 =
  une fois par trimestre). Ce plafond n'est pas cosmétique : sans lui, le
  bot rééquilibre tous les jours et les frais dévorent les versements.
- **Frais** : le pourcentage par ordre, et surtout le **minimum par ordre**.
  **Mesuré le 2026-09-18 sur le compte réel : 3,00 €** sur Euronext Paris
  (le manuel indiquait auparavant 1,25 €, une estimation 2,4 fois trop
  basse). C'est ce minimum qui décide tout pour de petits montants : sur un
  ordre de 200 €, il représente 1,5 %. Ajoute la taxe française de 0,4 % à
  l'achat, et un aller-retour coûte 3,4 % avant même que le cours ait bougé.
  C'est pourquoi ce bot achète et conserve au lieu de tourner.
- **Port IBKR** : 7497 pour TWS, **4002 pour IB Gateway** (c'est ce que tu
  utilises). Tous deux en mode paper.

Supprimer un bot retire sa configuration mais **conserve son historique**
de versements et d'ordres dans `data/`.

---

## 8. Outil complémentaire : trouver une crypto tendance

Ce n'est pas dans le dashboard — à lancer depuis un terminal :

```bash
.venv/Scripts/python -m tradingbot.find_trending
```

Affiche les plus fortes hausses, baisses et volumes du moment sur Binance, avec un exemple de config prêt à copier dans le formulaire de création. Une forte hausse récente n'est pas un signal d'achat — c'est un point de départ pour choisir une crypto à tester.

---

## 9. Outil complémentaire : rechercher les meilleurs paramètres

Toujours en terminal, pas dans le dashboard :

```bash
.venv/Scripts/python -m tradingbot.optimize
```

Teste automatiquement ~960 combinaisons de paramètres par paire pour les deux stratégies (dont le filtre de tendance et le sizing par volatilité activés ou non, voir §5.2), sur 3 ans d'historique, sur BTC/USDT, ETH/USDT et DOGE/USDT (personnalisable avec `--symbols`). Affiche un classement et écrit une config prête à l'emploi pour la meilleure combinaison trouvée, dans `config/optimized_{paire}_{stratégie}.yml` — **rien n'est lancé automatiquement**, tu dois la démarrer toi-même (dashboard ou CLI) une fois que tu l'as revue.

⚠️ **Attention si un bot du même nom tourne déjà** : l'outil écrase le fichier de config sans prévenir. S'il existe un bot `optimized_dogeusdt_sma_cross` par exemple, son fichier YAML est réécrit — le bot déjà lancé continue de tourner avec son ancienne config en mémoire jusqu'à ce que tu le redémarres, mais toute nouvelle modification via le formulaire repartirait de la nouvelle config écrite au disque. Vérifie ce que l'outil a écrit avant de redémarrer un bot existant.

✅ **Validation automatique anti-surapprentissage.** L'outil ne se contente plus de choisir le meilleur résultat sur tout l'historique : il réserve les 30% les plus récents comme période de "test", jamais vue pendant la recherche des paramètres, et classe les candidats sur leur performance **sur cette période de test**, pas sur l'entraînement. Exemple réel rencontré sur DOGE/USDT : le meilleur candidat affichait +23,06% sur la période d'entraînement, mais seulement +0,15% sur la période de test — la preuve concrète que ce résultat d'entraînement était trompeur et que la validation évite de se faire piéger par lui.

✅ **Premier edge positif mesuré (feuille de route performance, étape 1).** En ajoutant le filtre de tendance à la recherche, les meilleures configs trouvées sur BTC/USDT et DOGE/USDT affichent désormais un rendement **positif sur la période de test jamais vue** (jusque-là, même les meilleurs résultats validés étaient légèrement négatifs ou proches de zéro). Reste modeste (+1 à +2%) et à confirmer en paper trading, mais c'est la première fois que la validation anti-surapprentissage de cet outil produit un vrai edge mesuré plutôt qu'une simple réduction de perte.

⚠️ **Ça reste un point de départ, pas une certitude.** Même validé sur une période de test, un résultat historique ne garantit rien pour l'avenir — les conditions de marché changent. **Traite toujours le résultat comme un point de départ à valider en mode paper pendant plusieurs jours, jamais comme une certitude.**

### 9.1 Tester un bot précis sur une période choisie (backtest_lab)

Toujours en terminal — le dashboard propose désormais la même chose via un formulaire (onglet Test → Backtest, voir §6.1), pratique quand tu n'as pas de terminal sous la main. La version terminal reste utile pour scripter/automatiser un test ou en garder une trace exacte rejouable. Contrairement à `optimize` (§9, qui teste des centaines de combinaisons automatiquement) et `reoptimizer` (§9.2 ci-dessous), cet outil sert à tester **un seul bot bien précis**, avec **des paramètres et une période que tu choisis toi-même**, et à obtenir un rapport simple à la fin — utile pour rejouer un test exact plutôt que de laisser des scripts jetables s'accumuler.

**Mode questions/réponses**, le plus simple :

```bash
.venv/Scripts/python -m tradingbot.backtest_lab
```

Un menu numéroté propose le type de bot (SMA cross, scalp sur creux, retour à la moyenne, market making, rebond de creux horaire/minute, buy & hold), puis demande la devise, l'exchange, la période (dates de début/fin), le capital de départ, et les paramètres propres à la stratégie choisie (une valeur par défaut est proposée à chaque fois, appuie sur Entrée pour la garder).

**Mode direct**, pour rejouer exactement le même test plus tard ou l'automatiser :

```bash
.venv/Scripts/python -m tradingbot.backtest_lab --strategy dip_bounce_hourly --symbol BTC/USDT --since 2025-04-01 --until 2025-04-30 --capital 1000 --param dip_threshold_pct=0.5 --risk profit_lock_arm_pct=1 --risk profit_lock_trigger_pct=0.7
.venv/Scripts/python -m tradingbot.backtest_lab --list-strategies
```

**Le rapport final** (affiché à l'écran et enregistré dans `backtest_reports/`) donne le rendement, la comparaison au simple fait d'avoir acheté et gardé (buy & hold) sur la même période, le drawdown, puis un bloc "Trades" qui montre aussi les points négatifs plutôt que de les cacher : le pire trade, la durée de détention la plus longue, et si une position est restée ouverte (donc pas encore vendue) à la fin de la période testée.

**Option `--repeat N`** : rejoue le même test sur N sous-périodes égales découpées entre le début et la fin de la période demandée, plutôt qu'un seul essai sur toute la période. Sert à vérifier qu'un bon résultat ne repose pas sur une seule période chanceuse (comme le mois d'août observé plus tôt, très positif alors que les autres mois ne l'étaient pas) :

```bash
.venv/Scripts/python -m tradingbot.backtest_lab --strategy dip_bounce_hourly --symbol BTC/USDT --since 2025-01-01 --until 2025-04-30 --repeat 4
```

Le rapport liste alors chaque sous-période avec son propre rendement et sa comparaison au buy & hold, puis une synthèse : rendement moyen/médian, meilleure/pire sous-période, nombre de sous-périodes positives et nombre de sous-périodes qui battent le buy & hold.

⚠️ Comme pour `optimize`, un bon résultat sur une période passée n'est jamais une garantie pour l'avenir — c'est un outil de test, pas une prédiction.

### 9.2 Réoptimisation automatique périodique (propositions)

**Depuis le dashboard**, dans l'onglet "⚙ Configuration" → sous-onglet "Supervision", clique sur **"Lancer la réoptimisation de tous les bots"** en haut de la section "Propositions de réoptimisation". Ça vérifie tous les bots en une fois (peut prendre plusieurs minutes) ; les résultats apparaissent au fil de l'eau dans le tableau juste en dessous, rafraîchi automatiquement toutes les 15s.

**En ligne de commande**, pour un seul bot ou tous les bots :

```bash
.venv/Scripts/python -m tradingbot.reoptimizer --name mon_bot
.venv/Scripts/python -m tradingbot.reoptimizer --all
```

Vérifie si un bot existant pourrait être amélioré : relance la même recherche que l'outil `optimize` (§9, y compris le sizing ATR maintenant inclus dans la recherche), mais compare le résultat à la config **actuellement déployée** de ce bot précis, sur la même période de validation.

**Deux groupes de bots, pour mesurer si ça sert vraiment à quelque chose** : chaque bot est classé une fois pour toutes dans un groupe "auto" ou "control" (visible dans le tableau des propositions), à parts égales :
- Groupe **"control"** : la proposition apparaît normalement dans le tableau avec les boutons **Appliquer**/**Rejeter** — c'est toi qui décides.
- Groupe **"auto"** : dès qu'un candidat fait mieux que la config actuelle sur la période jamais vue, il est **appliqué automatiquement, sans te demander** — le bot est redémarré avec la nouvelle config tout seul. Ça permet de comparer dans le temps si les bots réoptimisés automatiquement font vraiment mieux que ceux qu'on laisse tranquilles.

⚠️ **Pourquoi c'est acceptable ici et pas ailleurs** : ce projet tourne entièrement en paper trading (aucun argent réel, voir §1) — c'est ce qui rend raisonnable de laisser une moitié des bots changer de config toute seule pour les besoins du test. Si un mode avec de l'argent réel voit le jour un jour, ce comportement automatique ne devra pas être repris tel quel.

⚠️ **Points à connaître** :
- L'outil refuse de proposer un changement (pour les deux groupes) si le bot a une position ouverte (le calcul du cash au redémarrage deviendrait faux, voir §4).
- Il ne revérifie pas plus d'une fois par semaine par bot, même si tu relances la vérification plus souvent entre-temps — pas de "chasse au meilleur résultat" permanente.
- **Cet outil ne se lance pas tout seul** : clique le bouton ou relance la commande toi-même de temps en temps (une fois par semaine est suffisant vu la fréquence ci-dessus), ou programme-la via le planificateur de tâches Windows si tu veux l'automatiser complètement côté vérification.

---

## 10. Dépannage

| Problème | Solution |
|---|---|
| Les onglets "Configuration" ou "Test" affichent une erreur de connexion | Le serveur de contrôle n'est pas lancé — double-clique sur `start_control_server.bat` |
| Je viens de mettre à jour le logiciel mais le dashboard n'a pas changé | Recharge la page (F5) — le rafraîchissement automatique ne recharge que les données des bots, pas la structure de la page. Si ça persiste, un bot déjà lancé avant la mise à jour écrase peut-être le fichier avec l'ancienne version : redémarre-le. Si tu viens de mettre à jour le serveur de contrôle lui-même (nouvelles routes, ex. l'onglet Test), redémarre aussi `start_control_server.bat` — il ne recharge pas son code tout seul |
| Un bot que je viens de créer ne démarre pas | Le formulaire affiche l'erreur exacte (paramètre incohérent, symbole introuvable...) — corrige et relance |
| Je ne sais pas si un bot tourne vraiment | Regarde le badge "En cours"/"Arrêté" — il se base sur la dernière écriture du bot, remise à jour au moins toutes les minutes |
| L'onglet Test → Backtest affiche un menu "Type de bot" vide | Le serveur de contrôle tourne encore avec une ancienne version (avant l'ajout de l'onglet Test) — redémarre `start_control_server.bat` |

---

## 8. Onglet « 🖐 Manuel » : acheter et vendre à la main

Un panier **à part** : son capital est celui que tu y verses avec le bouton
« Verser », il ne touche pas au panier commun des bots. Les ordres partent
**pour de vrai** sur le testnet Binance — argent fictif, mais cours réels,
mêmes arrondis et mêmes limites de paire que les bots (DOGE s'achète en
unités entières, par exemple).

**Pour passer un ordre** : choisis Acheter ou Vendre, la paire, puis le
montant en USDT (achat) ou la quantité (vente). Les boutons 25 % / 50 % /
75 % / Tout remplissent le champ à partir de ton cash ou de ta position.
L'estimation sous le champ te dit ce que tu vas obtenir, frais compris. Une
confirmation te rappelle que l'ordre est réel.

**Ce que le panier t'empêche de faire** : acheter plus que ton cash, acheter
plus que ce que le compte testnet a réellement de libre (il est partagé avec
les bots), vendre plus que tu ne détiens. Dans ces cas l'ordre est refusé
avant même de partir, et la raison s'affiche.

**Positions** : quantité, prix de revient (frais inclus), cours, valeur et
gain ou perte. « Tout vendre » liquide la ligne au marché.

**Remettre le panier à zéro** efface le registre après l'avoir sauvegardé. Ça
ne vend rien : si tu veux repartir sans position, vends d'abord.

## 9. Ouvrir le dashboard depuis ton téléphone ou un autre ordinateur

Le dashboard est accessible depuis n'importe quel appareil de la maison à
l'adresse `http://<adresse-du-serveur>:8765/dashboard.html` — le serveur
affiche cette adresse au démarrage.

**Il faut d'abord définir un mot de passe.** Tant que la ligne
`DASHBOARD_PASSWORD=` du fichier `.env` est vide, les autres appareils
reçoivent un refus qui explique quoi faire. C'est voulu : ce dashboard sait
passer des ordres et arrêter des bots, il ne doit pas s'ouvrir sur le réseau
par oubli. Une fois le mot de passe défini (et le serveur relancé), ton
navigateur demande l'identifiant — `trader` par défaut — une seule fois.

Sur la machine du serveur elle-même, rien ne change : pas de mot de passe.

**Trop de mots de passe faux = blocage de 15 minutes.** Après 10 essais
ratés en un quart d'heure depuis un même appareil, cet appareil reçoit
« Trop de mots de passe faux… accès bloqué pendant encore N min », même
s'il donne ensuite le bon mot de passe. C'est ce qui empêche un appareil
malveillant d'essayer des milliers de mots de passe. Pour te débloquer tout
de suite : attends le délai, ou relance le serveur. La machine du serveur
elle-même n'est jamais bloquée.

**Chiffrer la connexion (HTTPS, recommandé).** Sans cela, le mot de passe et
tes ordres voyagent en clair sur le Wi-Fi de la maison : un appareil
indiscret sur le même réseau pourrait les lire. Pour chiffrer, lance une
fois `bash scripts/generate_dashboard_cert.sh` sur le serveur, ajoute les
deux lignes qu'il affiche dans `.env`, puis relance le serveur. L'adresse
commence alors par `https://` au lieu de `http://`.

La première fois, chaque navigateur affiche un avertissement du type
« Votre connexion n'est pas privée ». C'est normal : le certificat a été
fabriqué par toi et non par une autorité connue du navigateur. Clique sur
« Paramètres avancés » puis « Continuer vers le site » ; le navigateur ne le
redemandera plus. Si tu tapes par erreur l'ancienne adresse en `http://`, la
page ne s'ouvre pas : remplace simplement par `https://`.

## 11. Onglet « 🔔 Alertes » : recevoir les alertes TradingView

TradingView ne permet pas à une autre application de lire ses analyses. Ce
qu'il permet : écrire ton analyse sur TradingView (en Pine Script ou avec
une simple alerte de prix), et quand elle se déclenche, **TradingView prévient
ton app**. Les alertes reçues s'affichent dans cet onglet.

**Pour que ça marche, trois conditions côté TradingView et côté réseau** :
1. un abonnement TradingView qui inclut les « webhooks » (selon leur page
   tarifs de septembre 2026 : Premium ou Ultimate) et la double
   authentification activée sur ton compte ;
2. ton app doit être joignable depuis internet, en HTTPS. Le plus simple et le
   plus sûr est un tunnel (Cloudflare Tunnel, ngrok) : il n'ouvre aucune porte
   sur ta box ;
3. sur TradingView, dans l'alerte, coche « Webhook URL », colle l'adresse de
   ton app suivie de `/api/tv-webhook`, et colle le modèle de message affiché
   dans l'onglet en y mettant ton secret.

**Le secret** est dans le fichier `.env` (`TRADINGVIEW_WEBHOOK_SECRET`). Sans
lui, toute alerte est refusée. Il n'est jamais enregistré avec les alertes.

**Protection contre les essais de secret** : si quelqu'un envoie 10 alertes
avec un secret faux en 15 minutes, son adresse est bloquée 15 minutes pour
les alertes (ton dashboard, lui, reste accessible). Cela marche aussi
derrière un tunnel. Conséquence à connaître : si tu as mal recopié le
secret dans TradingView, ses alertes sont refusées, puis bloquées un
quart d'heure — corrige le secret et attends 15 minutes, ou relance le
serveur pour lever le blocage tout de suite. Le bouton « Envoyer une alerte
de test » n'est jamais bloqué.

**Par défaut, une alerte ne passe aucun ordre** : elle est seulement notée.
Si tu veux qu'une alerte « buy » ou « sell » passe un ordre, mets
`TRADINGVIEW_AUTO_ORDERS=1` dans `.env`. L'ordre est alors passé **en argent
fictif**, dans ton **panier Manuel** uniquement (jamais dans les bots), et
limité à 100 USDT par alerte (réglable). La colonne « Suite donnée » te dit
ce qui s'est passé pour chaque alerte : aucun ordre (et pourquoi), exécuté,
ou refusé (et pourquoi).

Le bouton **« Envoyer une alerte de test »** simule une alerte depuis l'app,
pour vérifier que tout fonctionne sans compte TradingView.

## 12. L'Espace Trading : ton trading à la main, sans aucun bot

Ouvre-le depuis l'onglet **Manuel** avec le lien **« Ouvrir l'Espace
Trading »**. Tout ce que tu y fais concerne ton **panier Manuel** (le capital
que tu y as versé) : les bots n'y touchent jamais, et la page ne touche jamais
aux bots.

**Choisir ce que tu regardes** — la paire en haut à gauche (BTC/USDT,
ETH/USDT…), puis l'unité de temps (1m, 5m, 15m, 1h, 4h, 1d). Molette pour
zoomer, glisser pour se déplacer, survol pour lire une bougie. Changer de
paire ou d'unité de temps recentre le graphique sur le cours. Tes achats et
tes ventes passés apparaissent en flèches sur le graphique, et une ligne
pointillée marque ton prix d'achat.

**Acheter ou vendre tout de suite** — dans le panneau de droite : un montant
en USDT et « Acheter », ou « Tout vendre ».

**Poser un ordre à la souris** — clique sur le graphique, à la hauteur du prix
voulu :
- **au-dessus du cours** : « Vendre si le cours monte à … » (prise de profit) ;
- **en dessous** : « Vendre si le cours descend à … » (stop), ou « Acheter si
  le cours descend à … » — pour le montant indiqué dans le panneau.

**Protéger ta position** — stop-loss, objectif et trailing stop, en
pourcentage (vide = désactivé). Une ligne grise montre le seuil avant que tu
enregistres. Ces réglages restent actifs pour ta prochaine position sur la
même paire.

**Qui surveille tes ordres ?** Le serveur de l'application, toutes les
20 secondes (pastille « surveillant actif » en haut). Ce qu'il faut savoir :
- si le serveur est **arrêté** (PC éteint), rien n'est surveillé : tes ordres
  et protections reprennent à son redémarrage, mais ce qui s'est passé
  entre-temps n'est pas rattrapé ;
- un mouvement plus bref que 20 secondes peut passer inaperçu, et l'ordre part
  au prix du marché, qui peut différer un peu du seuil ;
- chaque ordre est listé à droite : en attente (avec **Annuler**), exécuté,
  ou refusé avec la raison.

## 13. L'Atelier de backtest : voir chaque trade, régler une stratégie

Ouvre-le depuis l'onglet **Test** du dashboard (lien « Ouvrir l'Atelier de
backtest »). Il rejoue une stratégie sur l'historique avec le **même moteur que
tes bots**, et te montre chaque achat et chaque vente sur un graphique
TradingView.

**Lancer un backtest**
- En haut : la paire, l'unité de temps (5m à 1d) et la période. Fin vide = jusqu'à
  aujourd'hui (les cours sont complétés automatiquement jusqu'à la dernière bougie).
- « Charger les réglages d'un bot » reprend exactement la configuration d'un de tes
  bots (stratégie, risque, frais, surveillance des sorties).
- Panneau de droite : les réglages de la stratégie, la gestion du risque (stop-loss,
  objectif, trailing stop dans les deux sens, verrou de gain, sortie partielle),
  les coûts, le capital.

**Lire le résultat**
- Les cartes du haut : rendement, ce qu'aurait donné « garder l'actif », baisse
  maximale, nombre de trades, part de gagnants, gain et perte moyens, rapport
  gains/pertes, temps passé en position, coûts payés.
- Le graphique : flèches bleues (montantes, sous la bougie) = achats, flèches
  vertes ou rouges = sorties gagnantes ou perdantes ; flèches violettes
  (descendantes, au-dessus de la bougie) = ventes à découvert ; bandes colorées = périodes où la stratégie détenait
  l'actif ; lignes fines = les niveaux de la stratégie (moyenne mobile, horizons du
  vote de momentum, POC / VAH / VAL du Volume Profile...). Chaque élément se masque
  avec les cases au-dessus du graphique.
- **Voir un trade** : clique une ligne du tableau, ou clique dans une bande colorée,
  ou utilise les flèches gauche / droite du clavier (Échap pour revenir à toute la
  période). Le graphique zoome sur le trade et affiche son prix d'achat, son prix de
  vente, son stop et son objectif, avec une fiche : dates, durée, motif de sortie,
  résultat.
- Sous le graphique : la courbe de ton capital (bleue), celle de « garder l'actif »
  (grise) et celle du backtest précédent (orange), pour comparer un réglage au
  précédent. Le tableau « Par semestre » montre si le résultat tient dans le temps.

**Les ventes à découvert**
Vendre à découvert, c'est parier sur la baisse : on vend d'abord, on rachète plus
tard, et on gagne si le prix a baissé entre les deux. Pour le Volume Profile, la
case « Ventes à découvert » ajoute les schémas « vente » de ton document (rejet
du POC par le haut, retour dans la zone par le dessus, cassure du VAL). Le stop
est alors **au-dessus** du prix d'entrée et l'objectif **en dessous**.
- Le tableau des trades a une colonne « Sens » (achat ou vente), et la fiche d'un
  trade dit « Vente » puis « Rachat ».
- Deux cartes s'ajoutent en haut : le résultat des achats et celui des ventes,
  séparés, pour voir lequel des deux sens rapporte.
- C'est possible en backtest et chez un courtier qui le permet (CFD chez
  Capital.com). Ton compte Binance actuel, au comptant, le refuse : un bot qui
  tenterait une vente à découvert verrait l'ordre rejeté, sans risque.

**Volume Profile : quand le stop est trop loin**
L'objectif d'un trade Volume Profile vaut 2 fois la distance au stop. Si le stop est
très loin, l'objectif l'est aussi, et le bot peut rester bloqué des jours sur un seul
trade. Trois réglages (tous à 0 = comportement d'origine) :
- « Stop au plus loin à » : distance maximale du stop. Au-delà, avec « cap », le stop
  est rapproché à cette distance et l'objectif suit (2 fois) ; avec « skip », le
  trade est ignoré.
- « Stop fixe » et « Objectif fixe » : des niveaux en % du prix d'entrée, quel que
  soit le pattern.
Mesuré sur 2025-2026 : seul « cap » à 1 - 1,5 % améliore le résultat ; ignorer ces
trades, ou des niveaux fixes comme -0,5 % / +1 %, donnent moins bien.

**Volume Profile : tenir compte des coûts**
Avec un spread ou une commission, un objectif « 2 fois le risque » ne rapporte plus
2 fois ce que coûte une perte. Deux réglages, qui utilisent les coûts du courtier
choisi :
- « Objectif repoussé pour couvrir spread et commission » : l'objectif est éloigné
  juste assez pour que, coûts déduits, le gain reste 2 fois la perte.
- « Stop au moins à N fois les coûts » : un trade dont le stop est trop près du prix
  est ignoré, car les coûts en mangeraient l'essentiel.
Mesuré sur 2025-2026 : repousser l'objectif seul n'aide pas (il est atteint moins
souvent). Ignorer les stops trop proches aide nettement : avec « Stop au plus loin à
1,5 % » et « au moins 10 fois les coûts », la stratégie gagne sur 6 à 7 périodes sur
12 au lieu de 2 à 4. Elle reste perdante sur DOGE et proche de zéro sur BTC.

**Régler une stratégie : le balayage**
Choisis un réglage dans « Balayer un réglage », écris les valeurs à essayer
(ex. `200, 300, 500`), puis « Balayer » : un backtest par valeur, avec le résultat
de chaque semestre. « Appliquer » reprend la valeur et relance le backtest complet.
Préfère un réglage dont les **voisins marchent aussi** (un plateau) à un réglage
seul qui brille : celui-là a souvent juste eu de la chance sur la période.

**Les coûts : choisis ton courtier**
La liste « Courtier », en haut des coûts, remplit toute seule la commission, le
spread et le financement de nuit pour la paire choisie : Capital.com (sans ou avec
levier), Trade Nation, NinjaTrader, Binance, Interactive Brokers. Sous la liste, une
note dit d'où vient chaque valeur, avec un lien vers la page du courtier. Les
courtiers CFD ne publient le spread que pour le Bitcoin : pour les autres cryptos,
la valeur est **estimée** et la note le signale. Si tu as renseigné ta clé API
démo Capital.com, les valeurs de Capital.com sont **lues en direct** (spread du
moment). Tu peux toujours retoucher un champ : la liste passe alors en « Saisie
libre ». Un bandeau te prévient si le courtier n'autorise pas la vente à découvert
ou ne propose pas la paire.

Ce que veut dire chaque coût :
- *Commission* : 0 chez les courtiers « sans commission ».
- *Spread* : l'écart entre prix d'achat et prix de vente, c'est là que ces courtiers
  se paient. L'atelier en compte la moitié à chaque achat et à chaque vente.
- *Financement par nuit* : sur les CFD, garder une position d'un jour sur l'autre
  coûte un pourcentage de sa valeur. Pour une stratégie qui garde ses positions
  plusieurs semaines, c'est souvent le coût principal. Il y a deux taux : un pour
  les achats, un pour les ventes à découvert. Celui des ventes peut être négatif :
  dans ce cas, c'est toi qui **reçois** ce montant chaque nuit.
Avec les trois à zéro, un bandeau te rappelle que le résultat est optimiste.

## Historique des changements de l'interface

| Date | Changement |
|---|---|
| 2026-09-10 | Version initiale : dashboard mono-bot avec statistiques et courbe de capital |
| 2026-09-10 | Ajout des onglets multi-bots + onglet "Analyse (BI)" |
| 2026-09-10 | Ajout du statut en direct (En cours/Arrêté), alerte visuelle si un bot s'arrête, journal des 10 dernières décisions avec écart de prix |
| 2026-09-10 | Ajout de l'onglet "⚙ Gérer les bots" : création de bot via formulaire (serveur de contrôle local) |
| 2026-09-10 | Ajout de Démarrer/Arrêter pour tout bot existant (pas seulement ceux créés via formulaire) depuis le même onglet |
| 2026-09-10 | Ajout de Modifier/Supprimer un bot ; validation stricte des paramètres avant tout lancement (empêche les plantages silencieux) ; détection des symboles inexistants avec suggestion |
| 2026-09-10 | Ajout du filtre de probabilité de hausse (Monte Carlo, optionnel) dans le formulaire de création/modification, et de la statistique correspondante dans la vue d'un bot |
| 2026-09-10 | Correction : un bot modifié pouvait apparaître en double, et un ancien nom restait affiché après renommage. Ajout d'une protection contre le double-clic sur les boutons Démarrer/Lancer |
| 2026-09-10 | Ajout du tableau "Ordres" à côté de la courbe de capital : détail de chaque position (prix d'achat, prix de vente visé, prix de vente réel, raison) |
| 2026-09-10 | Repositionnement du tableau "Ordres" : déplacé dans un panneau à droite de la carte principale (espace auparavant inutilisé), au lieu d'être serré à l'intérieur |
| 2026-09-10 | Ajout du champ "Positions simultanées max" dans le formulaire, et de la statistique "Positions ouvertes" dans la vue d'un bot |
| 2026-09-10 | Ajout des champs "Trailing stop (%)" et "Frais par ordre (%)" dans le formulaire, et de la statistique "Frais payés (cumulés)" dans la vue d'un bot |
| 2026-09-10 | Ajout d'un garde-fou automatique (non désactivable) qui bloque un nouvel achat tant qu'une position ouverte est en perte, suite au constat que "Positions simultanées max" pouvait accumuler des pertes corrélées |
| 2026-09-10 | L'historique des trades et les statistiques survivent désormais aux redémarrages d'un bot (rechargés depuis la base de données), au lieu de repartir de zéro à chaque redémarrage |
| 2026-09-10 | L'outil `optimize` valide désormais chaque candidat sur une période de test distincte de l'entraînement, pour détecter automatiquement le surapprentissage avant de recommander une config |
| 2026-09-11 | Une position ouverte au moment d'une extinction du PC ou d'un crash n'est plus liquidée automatiquement au redémarrage — elle est restaurée à l'identique (sauf tout premier lancement d'un bot) |
| 2026-09-12 | Remplacement de la courbe de capital par un graphique du cours réel du marché, avec chaque position affichée en barre horizontale verte (gain) ou rouge (perte), et des points marquant les achats/ventes exacts |
| 2026-09-12 | Ajout des graduations (prix et dates) sur les axes du graphique de cours, et de boutons pour changer la période affichée (Live, 1 heure, 1 jour, 1 mois, 1 an, 5 ans, 10 ans) |
| 2026-09-12 | Ajout du filtre de tendance (optionnel) dans le formulaire de création/modification, et de la statistique "Régime de tendance" dans la vue d'un bot — étape 1 de la feuille de route performance |
| 2026-09-12 | L'outil `optimize` inclut désormais le filtre de tendance dans sa recherche de paramètres — premier résultat positif obtenu sur la période de validation jamais vue |
| 2026-09-12 | Consolidation des bots de test (étape 4 de la feuille de route) : `Testdodge` supprimé, `TestETH2proba` réécrit pour ne différer de `TestETH` que par le filtre de probabilité, `GAINfoou` corrigé (sizing 100% → 20%) |
| 2026-09-12 | Ajout du sizing par volatilité (optionnel) dans le formulaire de création/modification, et de la statistique "Sizing volatilité" dans la vue d'un bot — étape 2 de la feuille de route performance (résultat mitigé, aucun bot ne l'active à ce jour) |
| 2026-09-12 | Ajout de la sortie partielle (optionnelle) dans le formulaire de création/modification, et des raisons "Trailing stop"/"Sortie partielle" dans le tableau des ordres — étape 3 de la feuille de route performance (compromis risque/rendement, aucun bot ne l'active à ce jour) |
| 2026-09-12 | Ajout de l'onglet "Propositions de réoptimisation" dans "⚙ Gérer les bots" (boutons Appliquer/Rejeter) — étape 5 de la feuille de route performance, feuille de route complète (étapes 1 à 5) |
| 2026-09-12 | Refonte visuelle complète du dashboard : nouvelle palette et typographie (police Inter), en-tête dédié, onglets avec puce de statut par bot, cartes de statistiques avec bordures et espacement retravaillés, graphique de cours avec dégradé sous la courbe, formulaire de création de bot réorganisé en 3 blocs (Général / Gestion du risque / Filtres avancés repliables) pour réduire la surcharge visuelle |
| 2026-09-12 | Ajout du bouton "Lancer la réoptimisation de tous les bots", du sizing ATR dans la recherche de paramètres, et du test A/B groupe auto (applique automatiquement)/control (jamais) visible dans le tableau des propositions — extension de l'étape 5 à la demande de l'utilisateur |
| 2026-09-12 | Passage au panier de capital commun : le champ "Capital alloué" devient "Plafond de mise (panier commun)" dans le formulaire, ajout d'une carte "Panier commun disponible" et de la colonne "Plafond effectif" dans l'onglet "Analyse (BI)", et des statistiques "Plafond de mise effectif"/"Panier commun disponible" dans la vue d'un bot — le plafond de chaque bot s'ajuste désormais automatiquement selon sa performance récente |
| 2026-09-12 | Troisième audit de la flotte : `ETHAV5mn`/`GAINfoou` supprimés (négatifs sur un test rétrospectif de 6 mois), flotte reconstruite en 1 bot par crypto du top 10 par capitalisation (10 bots au total), chacun avec des paramètres validés out-of-sample — 4 des 10 (BNB, SOL, LINK, AVAX) n'ont pas d'edge démontré et tournent avec un plafond de mise réduit |
| 2026-09-12 | Correction de l'utilisation du capital : plafond/taille de position relevés sur les 6 bots à edge validé (capital moyen déployé mesuré +121%, de 8,2% à 18,1% du panier commun) suite au constat que l'essentiel des 3000 restait inutilisé |
| 2026-09-12 | Le réoptimiseur hebdomadaire tourne désormais vraiment tout seul (tâche planifiée Windows) — jusqu'ici il fallait cliquer manuellement sur "Lancer la réoptimisation de tous les bots" pour qu'il se passe quoi que ce soit. Correction au passage d'un bug qui faisait perdre le réglage de taille de position d'un bot dès qu'une proposition était appliquée automatiquement |
| 2026-09-14 | Nettoyage de la vue d'un bot suite à un retour utilisateur ("trop fouillis, redondant, tableau tronqué") : suppression du panneau étroit sur le côté (le tableau "Ordres" y était coupé sur les écrans pas assez larges) au profit d'une page pleine largeur ; fusion de "Capital investi (départ)" et "Plafond de mise effectif" en une seule statistique ; "Panier commun disponible" affiché une seule fois (sous l'heure de mise à jour) au lieu d'être répété sur chaque bot ; nouvelle statistique "Investi actuellement" (montant réellement engagé dans le trade en cours, absente jusqu'ici) ; tableau "Ordres" enrichi de colonnes Quantité/Montant, colonne "TP visé" retirée (toujours vide, aucun bot ne l'utilise), positions ouvertes affichées en premier |
| 2026-09-14 | Ajout de 3 nouvelles options dans le formulaire de création de bot, proposées par l'utilisateur : "Rebond de creux - horaire" et "Rebond de creux - minute" (achat près d'un creux en tendance haussière, verrou de gain à deux seuils, aucun stop-loss volontairement), et "Buy & hold (passif)" (achète une fois, ne revend jamais). Le champ Timeframe se verrouille automatiquement pour les 2 variantes de rebond de creux ; le champ Stop-loss se grise et se vide automatiquement pour les 3 nouvelles options, avec un message expliquant l'absence de stop-loss |
| 2026-09-14 | Refonte complète de la navigation : 4 onglets principaux au lieu d'une barre plate — **Accueil** (statistiques globales, affiché par défaut à l'ouverture, ex-"Analyse (BI)"), **Bot** (détail d'un bot, un sous-onglet par bot), **Configuration** (sous-onglets Supervision et Création, ex-"⚙ Gérer les bots" scindé en deux), et nouvel onglet **Test** avec un sous-onglet **Backtest** : teste un bot précis (type, devise, période, paramètres) directement depuis un formulaire, sans terminal, avec le rapport affiché sur place — même moteur que la commande `backtest_lab` |
| 2026-09-14 | Ajout du bouton "Redémarrer tous les bots (recharge le code)" dans le sous-onglet Supervision : arrête puis relance chaque bot en cours depuis sa config sur disque (positions ouvertes restaurées à l'identique), puis recharge la page — pour que les bots et l'affichage prennent en compte une mise à jour du logiciel sans devoir redémarrer chacun manuellement |
| 2026-09-14 | Correction de comportement de "Rebond de creux" (§5.3), demandée par l'utilisateur après relecture : ne vend plus dès qu'un nouveau plus haut récent est atteint (pouvait clôturer la position pour un gain minuscule) — la seule sortie possible est désormais le verrou de gain, pour un vrai "achète et garde, protégé par le verrou de gain" plutôt qu'une sortie précoce sur simple nouveau plus haut |
| 2026-09-14 | Deuxième correction de "Rebond de creux" (§5.3) le même jour : l'entrée n'exige plus que le prix soit au-dessus de sa propre moyenne glissante (condition de tendance retirée à la demande de l'utilisateur) — achète simplement dès que le prix est proche de son plus bas récent, tendance ou pas |
| 2026-09-14 | Ajout du champ "Positions simultanées max" à l'onglet Test → Backtest (§6.1), demandé par l'utilisateur après avoir constaté qu'une seule position bloquée pouvait immobiliser un bot pendant des mois — permet de tester plusieurs positions en parallèle au lieu d'une seule |
| 2026-09-15 | Idée proposée par l'utilisateur, 2 ajouts : nouveau filtre avancé "Sizing par niveau de prix" (§5.2) dans le formulaire de création de bot — taille de position modulée selon l'écart au prix moyen du mois calendaire, en plus ou en moins ; nouveau champ "Forcer un trade après N heures sans achat" (§5.3) pour "Rebond de creux" — assouplit progressivement le seuil de creux si aucun achat n'a eu lieu depuis N heures |
| 2026-09-15 | "Sizing par niveau de prix" et "Forcer un trade après N heures" (voir ligne précédente) ajoutés aussi à l'onglet Test → Backtest (§6.1), pour pouvoir tester ces deux réglages avant de créer un vrai bot |
| 2026-09-15 | Ajout du champ "Timeframe de surveillance des sorties" à l'onglet Test → Backtest (§6.1), demandé par l'utilisateur suite à un constat réel : un verrou de gain vérifié une seule fois par heure pouvait vendre plusieurs % sous son seuil si le prix chutait vite entre deux vérifications. Vérifie désormais les sorties sur un timeframe plus fin (ex. 5 minutes) sans changer les entrées de la stratégie |
| 2026-09-15 | Le champ "Timeframe de surveillance des sorties" (voir ligne précédente) est ajouté aussi au formulaire de création/modification de bot (§5.2), sur demande explicite de l'utilisateur — fonctionne désormais pour un vrai bot en paper trading, pas seulement en test |
| 2026-09-15 | Ajout du volet repliable "Configuration de ce bot" dans l'onglet Bot (§4), demandé par l'utilisateur pour voir la config d'un bot sans aller dans l'onglet Configuration — avec un bouton "Modifier cette configuration" pour l'éditer et le relancer directement |
| 2026-09-15 | Correction de bug : un bot "Rebond de creux" (sans stop-loss, réglage assumé) plantait dès sa première position ouverte car le calcul du prix cible de stop-loss ne vérifiait pas que le réglage était bien désactivé — touchait `ETHSWING`/`XRP_SWING` en paper trading réel |
| 2026-09-15 | Le champ "Symbole" du formulaire de création/modification de bot (§5.1) et de l'onglet Test → Backtest (§6.1) devient une liste déroulante des 10 cryptos les plus courantes (BTC, ETH, XRP, BNB, SOL, DOGE, ADA, TRX, LINK, AVAX, toutes vs USDT), demandé par l'utilisateur pour éviter les fautes de frappe — une option "Autre..." reste disponible pour saisir librement un autre symbole |
| 2026-09-15 | Onglet Test → Backtest (§6.1) mis en parité avec le formulaire de création de bot, demandé par l'utilisateur ("la config de test n'est pas identique à la config de bot") : ajout du Timeframe (librement réglable, verrouillé pour "Rebond de creux"), de Taille position max/Perte max journalière/Trailing stop/Frais par ordre, de la Sortie partielle (scale-out), du Filtre de tendance (EMA) et du Sizing par volatilité (ATR) — tous testables avant de créer un vrai bot. Le filtre de probabilité (Monte Carlo) reste volontairement absent du backtest (biais de préconnaissance : son calcul se base sur "aujourd'hui", pas sur la période testée) |
| 2026-09-15 | Le stop-loss de "Rebond de creux" redevient réglable (formulaire de création §5.2 et Test → Backtest §6.1), demandé par l'utilisateur après avoir constaté empiriquement le risque concret de positions bloquées des mois en perte latente sans lui. Reste vide/désactivé par défaut (comportement historique inchangé) — une valeur saisie l'active en plus du verrou de gain |
| 2026-09-15 | Ajout du bouton "Exporter ces paramètres vers un nouveau bot" sous le rapport de l'onglet Test → Backtest (§6.1), demandé par l'utilisateur pour ne pas avoir à retaper à la main une config qui a donné un bon résultat en test — bascule vers Configuration → Création avec le formulaire pré-rempli |
| 2026-09-15 | Ajout d'une barre de progression pendant l'exécution d'un backtest (§6.1), demandée par l'utilisateur — animée pendant le téléchargement/une simulation unique, avec un vrai pourcentage par sous-période en mode "Sous-périodes" > 1 |
| 2026-09-16 | Ajout de la stratégie "Creux vs moyenne (5 min, sans verrou)" dans le formulaire de création (§5.1/5.3), proposée par l'utilisateur après observation du graphique en direct — détecte un creux comme un écart à la moyenne mobile (pas une proximité à un plus bas glissant), Timeframe verrouillé sur 5 minutes, Stop-loss rendu obligatoire (pas de verrou de gain pour cette stratégie) |
| 2026-09-16 | "Positions simultanées max" (formulaire de création et Test → Backtest) se pré-remplit désormais à 10 dès que "Creux vs moyenne" est sélectionné, suite à un constat réel : avec 1 seule position autorisée (défaut générique), cette stratégie restait quasi inactive |
| 2026-09-16 | Ajout de la stratégie "Détecteur de pente (1 min, trailing 5%)" dans le formulaire de création (§5.1/5.3), idée directe de l'utilisateur ("un détecteur de pente... on vend sur le trailing à 5%") — achète sur une chute brutale entre 2 bougies 1 minute consécutives, Timeframe verrouillé sur 1 minute, Trailing stop pré-rempli à 5% (sauf valeur déjà saisie), Stop-loss optionnel comme "Rebond de creux" |
| 2026-09-16 | Nouveau champ "Nombre de bougies pour mesurer la pente" pour "Détecteur de pente" (§5.3), suite à l'observation d'un graphique réel où plusieurs achats étaient en fait partis sur une tendance baissière continue — permet de mesurer la pente sur plus de 2 bougies (2 par défaut, comportement inchangé) pour lisser le bruit d'1 minute |
| 2026-09-16 | Nouvelle case "Limiter à 1 achat par pente continue" pour "Détecteur de pente" (§5.3), constat réel de l'utilisateur ("ça foire pendant les longues pentes") — évite d'empiler un achat à chaque bougie qualifiante sur la même tendance baissière continue ; décochée par défaut |
| 2026-09-16 | Nouveau graphique en chandelles sous le rapport de l'onglet Test → Backtest (§6.1), demandé par l'utilisateur — affiche les vraies bougies avec les achats/ventes marqués, curseurs de zoom ajustables et bascule bougies/courbe ; disponible uniquement pour un test sur une période unique (pas en mode "Sous-périodes" > 1) |
| 2026-09-16 | Mesure de pente au clic sur ce nouveau graphique (§6.1), demandé par l'utilisateur ("cliquer sur 2 bougies... sans bouton") — 2 clics suffisent : le 1er pose un point, le 2e calcule et affiche la variation de clôture entre les deux, avec un segment tracé entre les points sur le graphique |
| 2026-09-16 | Nouveau champ "Type de compte" dans le formulaire de création (§5.2), demandé par l'utilisateur ("configurer des bots qui peuvent investir avec une PEA ou un CTO") — "Actions (paper trading Interactive Brokers)" permet de créer un bot sur une vraie action en argent fictif, en plus des bots crypto existants. Nécessite TWS/IB Gateway installé (voir l'encadré §5.2) ; nouvelle stratégie "Rebond de creux - journalier" avec fenêtre de tendance réglable |
| 2026-09-17 | Le champ Symbole affiche désormais une liste déroulante de 11 actions courantes (TotalEnergies, Orange, Société Générale, Renault, Air France-KLM, ArcelorMittal, Air Liquide, LVMH, L'Oréal, Sanofi, BNP Paribas) quand "Type de compte" = "Actions", demandé par l'utilisateur ("que je puisse sélectionner les actions avec une liste") — "Autre..." reste disponible pour un ticker non listé, comme pour les cryptos |
| 2026-09-23 | **Graphique des bots en chandeliers**, comme dans l'onglet Test, demandé par l'utilisateur. Chaque bougie montre l'ouverture, le plus haut, le plus bas et la clôture de la période (verte si le cours a monté, rouge s'il a baissé). Les achats sont des **triangles verts**, les ventes des **triangles rouges**, et un cercle entoure l'achat d'une position encore ouverte. Valable en vue Live comme sur toutes les périodes |
| 2026-09-20 | **Dashboard accessible depuis tout appareil de la maison** (préparation Raspberry Pi). La page trouve désormais son serveur toute seule, quel que soit l'appareil qui l'ouvre. Un **mot de passe** est obligatoire pour les autres appareils : sans lui, refus avec explication ; avec lui, le navigateur le demande une fois. Voir §9 |
| 2026-09-19 | **Nouvel onglet « 🖐 Manuel »**, demandé par l'utilisateur ("une interface de trade manuel, bouton achat, vente avec un panier à part", en paper). Panier à capital propre, ordres réels sur le testnet, estimation avant envoi, positions avec gain latent, historique. Voir §8 |
| 2026-09-18 | **Onglet Investissement repensé**, demandé par l'utilisateur ("une interface digne de ce nom pour visualiser les actions achetées, le cours des actions... avec des boutons pour vendre plus tôt, reset le panier, augmenter le plafond"). Le tableau de chiffres laisse la place à un **graphique comparatif** des six lignes (toutes ramenées à 0 % au début de la période, seule façon de comparer des cours de 7 € et de 400 €) avec un sélecteur 1 mois à 5 ans, et à **une carte par action** : cours, gain calculé sur le prix de revient réel frais compris, courbe miniature avec ce prix en pointillés, et barre d'allocation réelle vs cible. Trois nouvelles actions : **vendre la moitié ou tout** d'une ligne, **remettre le panier à zéro** (sauvegarde l'historique, ne vend rien), et **ajuster le plafond mensuel** par − / + ou montant exact. Le tableau d'avant reste accessible, replié. Voir §7.1 bis |
| 2026-09-18 | **Correction d'un défaut sérieux du bouton « Exécuter réellement »**, découvert parce que tu l'avais cliqué. Interactive Brokers avait bien acheté 1 action TotalEnergies et 1 Société Générale, mais renvoyait à tort « ordre annulé » — le bot a donc enregistré deux ordres rejetés, un portefeuille vide et 200 € de liquidités qu'il n'avait plus. Le suivi affichait donc du faux. Le bot croit désormais les **exécutions** du courtier plutôt que le statut annoncé, et signale l'incohérence quand elle se produit. À savoir aussi : le **compte paper ne facture aucune commission**, alors que le vrai courtier en prend 3 € minimum par ordre — tes résultats en paper sont donc meilleurs que la réalité, de ce montant. Voir §7 |
| 2026-09-18 | **Frais réels du courtier mesurés**, après branchement du vrai compte Interactive Brokers. Le minimum par ordre est de **3,00 €** et non 1,25 € comme estimé jusqu'ici, et la taxe française de 0,4 % à l'achat était absente des calculs. Conséquences visibles : le **rééquilibrage est désactivé** dans le bot d'investissement (mesuré perdant de 2 à 4 points de rendement par an sur quatre dates de départ, car il vend ce qui monte et paie des frais aux deux bouts) — tu ne verras donc plus de ventes dans le suivi ; le champ **Frais minimum** affiche désormais 3,00 € ; le **port IBKR** passe à 4002 (IB Gateway). Voir §7 |
| 2026-09-17 | **Nouvel onglet principal « 💰 Investissement »**, demandé par l'utilisateur ("créer une fenêtre séparée dans le dashboard pour pouvoir gérer tout ça") — gère les bots d'investissement régulier (versements mensuels sur une allocation cible, sans stop-loss), avec deux sous-onglets : **Suivi** (total versé, valeur, gain, rendement annualisé, baisse maximale subie, frais, allocation réelle vs cible ligne par ligne, et deux boutons « Simuler le passage du jour » / « Exécuter réellement ») et **Réglages** (créer, modifier ou supprimer un bot : allocation, versement mensuel, bande de rééquilibrage, frais, port IBKR). Voir §7 |
| 2026-09-17 | Nouvelle strategie **« Régime de tendance »** dans le formulaire de création (§5.1/5.3), demandée par l'utilisateur (« un modèle rentable en haussier, et si possible aussi en baissier ») — le bot reste investi tant que le cours est au-dessus de sa tendance de fond et passe **tout en liquidités** dès qu'il repasse dessous, contrairement au « Filtre de tendance » qui bloquait seulement les nouveaux achats sans jamais fermer une position. Trois réglages : fenêtre de tendance, marge pour entrer, marge pour sortir (les marges évitent le va-et-vient coûteux autour de la ligne). Stop-loss optionnel : la sortie normale est le retournement de tendance. Mesuré sur ETH : +34,8 % en test hors échantillon contre -35,1 % pour un simple achat conservé, et quasi plat en marché baissier au lieu de -41 %. Gagner de l'argent quand ça baisse reste impossible (le bot ne peut qu'acheter), l'objectif est de ne plus subir |
| 2026-09-18 | **Rafraîchissement de l'interface**, demandé par l'utilisateur (« rendre l'interface graphique plus jolie, moderne et intuitive »). Cinq changements visibles : (1) le contenu occupe désormais toute la largeur de l'écran au lieu d'être bloqué à 900 px — les tableaux ne sont plus comprimés et respirent, alors que l'en-tête s'étalait déjà sur 1360 px ; (2) les valeurs ne se coupent plus en deux lignes dans les tableaux (« +0,00 » puis « % »), et une alternance de teinte aide à suivre une ligne du regard ; (3) les chiffres clés (capital, gain, valeur) sont plus grands et plus lisibles ; (4) chaque intertitre de section porte un petit filet coloré pour se repérer en balayant la page, et les longs paragraphes d'aide apparaissent en encart plutôt que noyés dans le texte courant ; (5) **une légende explique enfin la pastille verte/rouge** à côté de chaque bot (« actif » / « arrêté »), avec le compte des bots en marche et une infobulle précisant qu'un bot est considéré actif s'il a envoyé des données il y a moins de 3 minutes. Ajout aussi d'une icône d'onglet. Les formulaires restent volontairement bornés en largeur : étalés sur tout l'écran, leurs champs se dispersaient sur six colonnes |
| 2026-09-26 | **Connexion chiffrée (HTTPS) possible pour ouvrir le dashboard depuis un autre appareil.** Le mot de passe et les ordres ne voyagent plus en clair sur le réseau de la maison une fois un certificat créé (une commande) ; l'adresse commence alors par `https://`, et le navigateur affiche un avertissement la première fois, à accepter. Sans certificat, rien ne change. Voir §9 |
| 2026-09-26 | **Graphique TradingView et onglet « 🔔 Alertes »**, demandés par l'utilisateur. Le graphique de l'onglet Bot utilise désormais la bibliothèque de TradingView : zoom à la molette, déplacement, et valeurs de la bougie survolée. Nouvel onglet Alertes : reçoit les alertes envoyées par TradingView, avec les instructions pour les brancher, un bouton de test, et la liste des alertes reçues. Une alerte ne passe aucun ordre sauf si tu l'actives (ordres fictifs, panier Manuel, plafonnés). Voir §4.2 et §11 |
| 2026-09-26 | **Ordres d'achat au clic et zones sur le graphique des bots**, demandés par l'utilisateur. Un clic sur le graphique propose d'acheter si le cours descend sous le prix cliqué ; le bot surveille et achète lui-même, avec les mêmes protections que sa stratégie. Trois cases à cocher affichent ou masquent les zones : stop-loss et objectifs, seuils de la stratégie, ordres en attente. Nouveau tableau « Ordres manuels sur ce bot » avec bouton Annuler. Voir §4.2 |
| 2026-09-26 | **Nouvelle page « Espace Trading »**, demandée par l'utilisateur, accessible depuis l'onglet Bot. Graphique avec choix de l'unité de temps (1 minute à 1 jour), ordres de vente posés d'un clic (prise de profit au-dessus du cours, stop en dessous) ou d'achat, et panneau de réglages (stop-loss, trailing stop, objectif, verrou de gain...) avec aperçu des lignes sur le graphique avant d'appliquer. Voir §12 |
| 2026-09-26 | **Correction du lien « Ouvrir l'espace de trading »** : quand le dashboard était ouvert comme fichier (ce que font les bots au démarrage), le lien menait à une page introuvable (« Impossible d'accéder à votre fichier »). Il pointe désormais vers le serveur, et s'ouvre dans un nouvel onglet |
| 2026-09-26 | **L'Espace Trading devient indépendant des bots**, à la demande de l'utilisateur. Il pilote désormais ton panier Manuel, paire par paire : ordre immédiat, ordres posés à la souris, stop-loss, objectif et trailing stop surveillés par le serveur toutes les 20 secondes. Le lien passe de l'onglet Bot à l'onglet Manuel. Voir §12 |
| 2026-09-26 | **Espace Trading : le graphique se recentre quand tu changes de paire** (passer du Bitcoin à l'Ethereum gardait l'échelle du Bitcoin si tu l'avais déplacée à la souris). Le nombre de décimales s'adapte aussi au prix (DOGE à 5 décimales) |
| 2026-09-27 | **Trailing stop « % du gain rendu »** : dans le formulaire d'un bot, deux nouveaux champs. « Sens du trailing stop » permet de choisir entre l'ancien fonctionnement (X % sous le plus haut) et la part du gain rendue (achat 2000, plus haut 2100, 50 % : vente à 2050). « Armement » fixe le gain à atteindre avant que ce trailing s'active. Enregistrer un bot depuis le formulaire conserve désormais ce réglage. Voir §5.2 |
| 2026-09-27 | **Protection contre les essais de mot de passe en série** pour l'accès au dashboard depuis un autre appareil : après 10 mots de passe faux en 15 minutes, l'appareil est bloqué 15 minutes. Ouvrir la page sans avoir encore tapé le mot de passe ne compte pas comme un échec, et la machine du serveur n'est jamais bloquée. Voir §9 |
| 2026-09-28 | **Protection contre les essais de secret sur les alertes TradingView** : après 10 alertes au secret faux en 15 minutes, l'adresse d'où elles viennent est bloquée 15 minutes (pour les alertes seulement, pas pour le dashboard). Aucun changement visible dans le dashboard. Voir §11 |
| 2026-10-09 | **Atelier de backtest** (lien dans l'onglet Test) : chaque trade sur un graphique TradingView, réglages de la stratégie, du risque et des coûts (commission, spread, financement de nuit), balayage d'un réglage avec le résultat par semestre, chargement des réglages d'un bot. Le champ « Frais par ordre » d'un nouveau bot vaut désormais 0 (courtiers sans commission). Voir §13 |
| 2026-10-09 | **Ventes à découvert dans l'Atelier de backtest** : nouvelle case « Ventes à découvert » pour le Volume Profile (schémas de vente de ton document), flèches violettes au-dessus de la bougie pour ces ventes, colonne « Sens » dans le tableau des trades, fiche « Vente / Rachat », deux cartes qui séparent le résultat des achats et des ventes, et un second taux de financement de nuit pour les ventes (négatif = tu reçois). Les libellés du stop-loss et de l'objectif parlent désormais d'« écart au prix d'entrée » (valable dans les deux sens). |
| 2026-10-09 | **Volume Profile : stop trop loin** - trois nouveaux réglages dans l'Atelier (« Stop au plus loin à » avec « cap » ou « skip », « Stop fixe », « Objectif fixe »), à 0 par défaut. Ton bot Volume Profile n'est pas modifié. Voir §13 |
| 2026-10-09 | **Atelier de backtest : choix du courtier** - une liste « Courtier » remplit automatiquement commission, spread et financement de nuit (Capital.com, Trade Nation, NinjaTrader, Binance, Interactive Brokers), avec la source de chaque valeur et les estimations signalées ; lecture en direct chez Capital.com si ta clé démo est renseignée. Voir §13 |
| 2026-10-09 | **Volume Profile selon les coûts** - deux réglages dans l'Atelier : « Objectif repoussé pour couvrir spread et commission » et « Stop au moins à N fois les coûts ». Désactivés par défaut ; ton bot n'est pas modifié. Voir §13 |
