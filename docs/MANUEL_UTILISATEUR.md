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

La page se rafraîchit **automatiquement toutes les 15 secondes**. Pas besoin d'actualiser manuellement, sauf si tu viens de mettre à jour le logiciel lui-même (voir §9).

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
| **Cours du marché & positions** | Graphique du prix réel de la crypto, avec chaque position affichée en barre horizontale : verte si gagnante, rouge si perdante (calculé au prix actuel tant qu'elle reste ouverte). Un point vert marque l'achat, un point rouge la vente — voir §4.2 |
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
- **La ligne** : le cours réel de la crypto tradée.
- **Une barre horizontale par position**, allant du moment de l'achat au moment de la vente (ou jusqu'à maintenant si la position est encore ouverte) : **verte si la position est gagnante**, **rouge si elle est perdante** (pour une position encore ouverte, calculé par rapport au prix actuel — la couleur peut donc changer d'un rafraîchissement à l'autre).
- **Un point vert** à l'endroit exact de l'achat, **un point rouge** à l'endroit exact de la vente.
- **Les axes gradués** : l'axe vertical affiche le prix (formaté avec le bon nombre de décimales selon la crypto), l'axe horizontal affiche les dates ou heures, adaptées automatiquement à la période affichée (heures pour "1 jour", mois pour "1 an", années pour "5 ans"/"10 ans").

Ça permet de voir en un coup d'œil si le bot achète au bon moment par rapport aux mouvements réels du marché, plutôt que de deviner à partir d'un chiffre agrégé. Survole une barre ou un point avec la souris pour voir le prix exact (info-bulle).

**Boutons de période** au-dessus du graphique : **Live** (les données en temps réel du bot, granularité fine mais fenêtre courte), **1 heure**, **1 jour**, **1 mois**, **1 an**, **5 ans**, **10 ans**. Les périodes autres que "Live" interrogent l'historique réel du marché (marché spot Binance, pas le testnet dont l'historique est trop court) via le serveur de contrôle — nécessite donc que `python -m tradingbot.control_server` tourne, comme pour créer/modifier un bot. Le résultat est mis en cache une minute pour ne pas surcharger l'exchange si plusieurs onglets sont ouverts sur la même crypto.

⚠️ Une position clôturée il y a longtemps (bien avant la période affichée) peut apparaître comme une barre qui commence tout au bord gauche du graphique, même si l'achat a eu lieu avant — c'est normal, le graphique n'a simplement pas le détail du cours pour cette période plus ancienne.

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
| Symbole | Paire à trader. Liste déroulante des 10 cryptos les plus courantes (BTC, ETH, XRP, BNB, SOL, DOGE, ADA, TRX, LINK, AVAX, toutes vs USDT) ; choisir "Autre..." fait apparaître un champ texte libre pour une autre paire (ex. `MATIC/USDT`) — doit alors exister réellement sur Binance, une faute de frappe est détectée avec une suggestion automatique |
| Timeframe | Durée d'une bougie (1 minute à 1 jour). Court = plus réactif, plus de bruit ; long = plus stable, plus lent |
| Stratégie | **Croisement de moyennes** (suit une tendance, peu de trades), **Scalp sur creux** (achète les petites baisses, vise des gains rapides et fréquents), **Rebond de creux - horaire/minute** ou **Buy & hold (passif)** — voir §5.3 pour ces 3 dernières |
| Plafond de mise (panier commun) | Limite haute de ce que ce bot peut viser dans le panier de capital commun — pas un budget qui lui serait réservé (voir §3, onglet Accueil) ; s'ajuste automatiquement selon sa performance récente |
| Taille position max (%) | Part du capital investie sur un seul trade |
| Stop-loss (%) | Perte tolérée avant vente automatique. **Absent pour "Buy & hold"** (achat unique, jamais revendu). **Optionnel pour "Rebond de creux"** : vide par défaut (décision historique de cette stratégie — voir §5.3), une valeur saisie l'active exactement comme pour les autres stratégies |
| Take-profit (%) | Gain visé avant vente automatique. **Indispensable pour la stratégie "Scalp sur creux"**, qui n'a pas d'autre moyen de revendre |
| Perte max journalière (%) | Le bot arrête de trader pour la journée s'il atteint ce seuil de perte cumulée |
| Positions simultanées max | Par défaut 1 (comportement historique : une seule position à la fois). Au-delà de 1, le bot peut ouvrir plusieurs positions en parallèle au lieu d'attendre que la précédente se clôture — voir l'avertissement ci-dessous |
| Trailing stop (%) | Optionnel, désactivé par défaut. Stop-loss "suiveur" : au lieu d'un seuil fixe, il remonte au fur et à mesure que le prix monte, pour sécuriser une partie des gains si le prix redescend ensuite. Ex. 3% : si le prix monte de 10%, la vente automatique se déclenche s'il redescend de plus de 3% depuis son plus haut, même si ça reste au-dessus du prix d'achat |
| Frais par ordre (%) | Frais de transaction simulés à chaque achat et vente, par défaut 0,1% (taux standard Binance). Déduit automatiquement du P&L pour un résultat réaliste |
| Timeframe de surveillance des sorties (ex. `5m`) | Optionnel, vide = désactivé. Vérifie le stop-loss/verrou de gain/trailing stop plus souvent que le timeframe du bot (ex. toutes les 5 minutes au lieu d'une fois par heure), sans changer les entrées de la stratégie — doit être plus fin (plus court) que le timeframe choisi plus haut, sinon le formulaire refuse. Corrige un vrai risque : une vérification une seule fois par heure peut vendre bien plus bas que le seuil prévu si le prix chute vite entre deux vérifications. Réutilise le prix déjà récupéré par le bot à chaque cycle, aucune donnée supplémentaire à télécharger en direct |
| Bougies de réchauffement | Historique chargé au démarrage pour que la stratégie ait des données dès le début (évite d'attendre des heures avant le premier signal possible) |

Champs spécifiques au **scalp sur creux** :
- **Lookback** : nombre de bougies utilisées pour calculer la moyenne de référence,
- **Seuil de creux (%)** : chute de prix (par rapport à cette moyenne) qui déclenche un achat.

### 5.3 Rebond de creux et Buy & hold — 2 nouvelles stratégies, proposée par toi pour la première

**Rebond de creux (horaire ou minute)** : achète dès que le prix est proche de son plus bas récent — **aucune condition de tendance requise** (plus haussière ni autre) ; puis **hold jusqu'à être rentable** — la seule vente possible est le **verrou de gain** : une fois qu'un premier seuil de gain est dépassé, le bot vend dès que ce gain retombe à un second seuil (plus bas), ça sécurise un gain déjà acquis sans le figer à un montant fixe. *(Corrections du 2026-09-14, à la demande de l'utilisateur : (1) la version initiale vendait aussi dès qu'un nouveau plus haut récent était atteint, ce qui pouvait clôturer la position pour un gain minuscule avant même que le verrou ait la moindre chance de s'armer — retiré, pour un vrai "achète et garde, protégé par le verrou de gain" ; (2) l'entrée exigeait aussi que le prix soit au-dessus de sa propre moyenne glissante — retiré, l'entrée ne dépend plus que de la proximité au plus bas récent.)* Deux variantes au choix dans le menu Stratégie :
- **Rebond de creux - horaire** : raisonne sur une fenêtre de 24 bougies d'1 heure (24h). Le timeframe se verrouille automatiquement sur "1 heure".
- **Rebond de creux - minute** : la même logique, mais sur une fenêtre de 60 bougies d'1 minute (1h). Le timeframe se verrouille automatiquement sur "1 minute".

Champs spécifiques :
- **Seuil de creux (%)** : à quel point le prix doit être proche du plus bas de la fenêtre pour déclencher un achat,
- **Armement du verrou de gain (%)** : le gain à partir duquel le verrou s'active,
- **Déclenchement du verrou de gain (%)** : le gain, en dessous du précédent, qui déclenche la vente une fois le verrou armé — doit être strictement inférieur au seuil d'armement,
- **Forcer un trade après N heures sans achat (0 = désactivé)** : si aucun achat n'a eu lieu depuis N heures, le seuil de creux s'assouplit progressivement (double à chaque période supplémentaire écoulée sans achat) jusqu'à finir par déclencher un achat — idée proposée par toi, pour éviter qu'un seuil trop strict laisse le bot inactif indéfiniment. Jamais un achat instantané "à tout prix" : juste un seuil de moins en moins strict.

⚠️ **Pas de stop-loss par défaut (vide), pas un oubli — mais réintégré en option** (demande explicite de l'utilisateur, 2026-09-15) : si le champ "Stop-loss" (§5.2) reste vide, une position n'a que le verrou de gain comme porte de sortie et peut rester ouverte indéfiniment, même en perte. Validation empirique (variante horaire, 10 cryptos, 3 ans, voir [FEUILLE_DE_ROUTE_PERFORMANCE.md](FEUILLE_DE_ROUTE_PERFORMANCE.md) étape 9, **avant le retrait de la sortie sur nouveau plus haut** — à revalider avec le comportement actuel) : résultat mitigé, et ce risque s'est concrètement matérialisé (un trade a perdu jusqu'à 3,2% du capital de test en une seule fois, une position est restée ouverte à la fin de la période testée). Renseigner le champ "Stop-loss" active une protection classique en plus du verrou de gain, si le risque de blocage prolongé ne convient pas.

**Buy & hold (passif)** : achète une seule fois, dès le premier cycle, avec "Taille position max" du "Plafond de mise", puis ne revend jamais — pas de stop-loss, pas de take-profit, aucun réglage de stratégie à renseigner. C'est la version "bot" du benchmark buy & hold déjà utilisé pour juger les autres stratégies tout au long de ce projet : utile pour comparer directement, en conditions réelles, le trading actif à la simple détention.

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

Teste un bot précis (type de bot, devise, exchange, période, capital, paramètres) directement depuis le dashboard, sans terminal — c'est le même moteur que l'outil en ligne de commande `backtest_lab` (voir §8.1), juste avec un formulaire à la place des options en ligne de commande.

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

⚠️ Le premier test sur une devise/timeframe jamais utilisée peut prendre du temps (téléchargement de l'historique) — les tests suivants sur la même combinaison sont quasi instantanés (mis en cache localement). Comme pour `optimize`, un bon résultat sur une période passée n'est jamais une garantie pour l'avenir. Le filtre de tendance (EMA) et le sizing ATR démarrent "à froid" en backtest (pas d'historique avant la période testée pour les réchauffer, contrairement au paper trading) — leurs tout premiers effets dans le test peuvent donc différer légèrement d'un bot réel déjà rodé.

---

## 7. Outil complémentaire : trouver une crypto tendance

Ce n'est pas dans le dashboard — à lancer depuis un terminal :

```bash
.venv/Scripts/python -m tradingbot.find_trending
```

Affiche les plus fortes hausses, baisses et volumes du moment sur Binance, avec un exemple de config prêt à copier dans le formulaire de création. Une forte hausse récente n'est pas un signal d'achat — c'est un point de départ pour choisir une crypto à tester.

---

## 8. Outil complémentaire : rechercher les meilleurs paramètres

Toujours en terminal, pas dans le dashboard :

```bash
.venv/Scripts/python -m tradingbot.optimize
```

Teste automatiquement ~960 combinaisons de paramètres par paire pour les deux stratégies (dont le filtre de tendance et le sizing par volatilité activés ou non, voir §5.2), sur 3 ans d'historique, sur BTC/USDT, ETH/USDT et DOGE/USDT (personnalisable avec `--symbols`). Affiche un classement et écrit une config prête à l'emploi pour la meilleure combinaison trouvée, dans `config/optimized_{paire}_{stratégie}.yml` — **rien n'est lancé automatiquement**, tu dois la démarrer toi-même (dashboard ou CLI) une fois que tu l'as revue.

⚠️ **Attention si un bot du même nom tourne déjà** : l'outil écrase le fichier de config sans prévenir. S'il existe un bot `optimized_dogeusdt_sma_cross` par exemple, son fichier YAML est réécrit — le bot déjà lancé continue de tourner avec son ancienne config en mémoire jusqu'à ce que tu le redémarres, mais toute nouvelle modification via le formulaire repartirait de la nouvelle config écrite au disque. Vérifie ce que l'outil a écrit avant de redémarrer un bot existant.

✅ **Validation automatique anti-surapprentissage.** L'outil ne se contente plus de choisir le meilleur résultat sur tout l'historique : il réserve les 30% les plus récents comme période de "test", jamais vue pendant la recherche des paramètres, et classe les candidats sur leur performance **sur cette période de test**, pas sur l'entraînement. Exemple réel rencontré sur DOGE/USDT : le meilleur candidat affichait +23,06% sur la période d'entraînement, mais seulement +0,15% sur la période de test — la preuve concrète que ce résultat d'entraînement était trompeur et que la validation évite de se faire piéger par lui.

✅ **Premier edge positif mesuré (feuille de route performance, étape 1).** En ajoutant le filtre de tendance à la recherche, les meilleures configs trouvées sur BTC/USDT et DOGE/USDT affichent désormais un rendement **positif sur la période de test jamais vue** (jusque-là, même les meilleurs résultats validés étaient légèrement négatifs ou proches de zéro). Reste modeste (+1 à +2%) et à confirmer en paper trading, mais c'est la première fois que la validation anti-surapprentissage de cet outil produit un vrai edge mesuré plutôt qu'une simple réduction de perte.

⚠️ **Ça reste un point de départ, pas une certitude.** Même validé sur une période de test, un résultat historique ne garantit rien pour l'avenir — les conditions de marché changent. **Traite toujours le résultat comme un point de départ à valider en mode paper pendant plusieurs jours, jamais comme une certitude.**

### 8.1 Tester un bot précis sur une période choisie (backtest_lab)

Toujours en terminal — le dashboard propose désormais la même chose via un formulaire (onglet Test → Backtest, voir §6.1), pratique quand tu n'as pas de terminal sous la main. La version terminal reste utile pour scripter/automatiser un test ou en garder une trace exacte rejouable. Contrairement à `optimize` (§8, qui teste des centaines de combinaisons automatiquement) et `reoptimizer` (§8.2 ci-dessous), cet outil sert à tester **un seul bot bien précis**, avec **des paramètres et une période que tu choisis toi-même**, et à obtenir un rapport simple à la fin — utile pour rejouer un test exact plutôt que de laisser des scripts jetables s'accumuler.

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

### 8.2 Réoptimisation automatique périodique (propositions)

**Depuis le dashboard**, dans l'onglet "⚙ Configuration" → sous-onglet "Supervision", clique sur **"Lancer la réoptimisation de tous les bots"** en haut de la section "Propositions de réoptimisation". Ça vérifie tous les bots en une fois (peut prendre plusieurs minutes) ; les résultats apparaissent au fil de l'eau dans le tableau juste en dessous, rafraîchi automatiquement toutes les 15s.

**En ligne de commande**, pour un seul bot ou tous les bots :

```bash
.venv/Scripts/python -m tradingbot.reoptimizer --name mon_bot
.venv/Scripts/python -m tradingbot.reoptimizer --all
```

Vérifie si un bot existant pourrait être amélioré : relance la même recherche que l'outil `optimize` (§8, y compris le sizing ATR maintenant inclus dans la recherche), mais compare le résultat à la config **actuellement déployée** de ce bot précis, sur la même période de validation.

**Deux groupes de bots, pour mesurer si ça sert vraiment à quelque chose** : chaque bot est classé une fois pour toutes dans un groupe "auto" ou "control" (visible dans le tableau des propositions), à parts égales :
- Groupe **"control"** : la proposition apparaît normalement dans le tableau avec les boutons **Appliquer**/**Rejeter** — c'est toi qui décides.
- Groupe **"auto"** : dès qu'un candidat fait mieux que la config actuelle sur la période jamais vue, il est **appliqué automatiquement, sans te demander** — le bot est redémarré avec la nouvelle config tout seul. Ça permet de comparer dans le temps si les bots réoptimisés automatiquement font vraiment mieux que ceux qu'on laisse tranquilles.

⚠️ **Pourquoi c'est acceptable ici et pas ailleurs** : ce projet tourne entièrement en paper trading (aucun argent réel, voir §1) — c'est ce qui rend raisonnable de laisser une moitié des bots changer de config toute seule pour les besoins du test. Si un mode avec de l'argent réel voit le jour un jour, ce comportement automatique ne devra pas être repris tel quel.

⚠️ **Points à connaître** :
- L'outil refuse de proposer un changement (pour les deux groupes) si le bot a une position ouverte (le calcul du cash au redémarrage deviendrait faux, voir §4).
- Il ne revérifie pas plus d'une fois par semaine par bot, même si tu relances la vérification plus souvent entre-temps — pas de "chasse au meilleur résultat" permanente.
- **Cet outil ne se lance pas tout seul** : clique le bouton ou relance la commande toi-même de temps en temps (une fois par semaine est suffisant vu la fréquence ci-dessus), ou programme-la via le planificateur de tâches Windows si tu veux l'automatiser complètement côté vérification.

---

## 9. Dépannage

| Problème | Solution |
|---|---|
| Les onglets "Configuration" ou "Test" affichent une erreur de connexion | Le serveur de contrôle n'est pas lancé — double-clique sur `start_control_server.bat` |
| Je viens de mettre à jour le logiciel mais le dashboard n'a pas changé | Recharge la page (F5) — le rafraîchissement automatique ne recharge que les données des bots, pas la structure de la page. Si ça persiste, un bot déjà lancé avant la mise à jour écrase peut-être le fichier avec l'ancienne version : redémarre-le. Si tu viens de mettre à jour le serveur de contrôle lui-même (nouvelles routes, ex. l'onglet Test), redémarre aussi `start_control_server.bat` — il ne recharge pas son code tout seul |
| Un bot que je viens de créer ne démarre pas | Le formulaire affiche l'erreur exacte (paramètre incohérent, symbole introuvable...) — corrige et relance |
| Je ne sais pas si un bot tourne vraiment | Regarde le badge "En cours"/"Arrêté" — il se base sur la dernière écriture du bot, remise à jour au moins toutes les minutes |
| L'onglet Test → Backtest affiche un menu "Type de bot" vide | Le serveur de contrôle tourne encore avec une ancienne version (avant l'ajout de l'onglet Test) — redémarre `start_control_server.bat` |

---

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
