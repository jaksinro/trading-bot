# Trading Bot

Plateforme personnelle de trading algorithmique en Python : backtests sur
données réelles, bots en paper trading (argent fictif), atelier de réglage
trade par trade et tableau de bord web. Crypto (Binance) et actions
(Interactive Brokers), avec une règle de fond : **mesurer honnêtement avant
de croire un résultat** — validation hors échantillon, plusieurs fenêtres
de test, coûts réels inclus.

Projet mené en cycle en V : besoin dans [docs/STB.md](docs/STB.md),
conception et toutes les mesures dans [docs/STC.md](docs/STC.md), guide du
tableau de bord dans [docs/MANUEL_UTILISATEUR.md](docs/MANUEL_UTILISATEUR.md),
installation et commandes dans [docs/GUIDE_TECHNIQUE.md](docs/GUIDE_TECHNIQUE.md).
1 098 tests automatisés.

---

## Ce que fait l'outil

- **Moteur unique** pour le backtest, le paper trading et (à terme) le réel :
  le bot qui passe des ordres exécute exactement le code qui a été mesuré.
- **12 stratégies** : Volume Profile, régime de tendance, vote de momentum,
  rebond sur creux, retour à la moyenne, RSI, market making, etc.
- **Atelier de backtest** façon TradingView : graphique, chaque trade avec
  son entrée, son stop et son objectif, réglages modifiables en direct, et
  choix du courtier qui remplit automatiquement commission, spread et
  financement de nuit.
- **Ventes à découvert** (parier sur la baisse) dans le moteur et les
  backtests, avec stop, objectif et trailing en miroir.
- **Bots multi-instances** : une config YAML = un bot, panier de capital
  commun, persistance complète entre redémarrages, relance automatique,
  tolérance aux coupures réseau.
- **Tableau de bord web** : un onglet par bot, graphique avec achats et
  ventes, création / modification de bots par formulaire, analyse
  comparative, accès depuis tout appareil de la maison (mot de passe, HTTPS
  optionnel, déploiement Raspberry Pi).
- **Outils de contrôle** : recherche de paramètres avec validation
  out-of-sample, réoptimisation périodique avec test A/B, comparaison des
  ordres réellement passés aux signaux attendus, diagnostic de connexion
  courtier.
- **Bot d'investissement régulier** (versements mensuels, allocation cible)
  en paper sur Interactive Brokers.

---

## Résultat phare : la stratégie Volume Profile

La stratégie lit le **profil de volume de la veille** — POC (prix le plus
échangé), zone de valeur (VAH / VAL, 70 % du volume) — calculé **exactement
comme TradingView** (bougies d'une minute, lignes en pas de cotation
entiers, zone de valeur construite ligne à ligne ; vérifié à quelques
dollars près sur une capture réelle). Trois setups, entrée à la clôture de
la bougie qui valide :

1. **Rebond sur le POC** — mèche de rejet puis bougie de confirmation.
2. **Retour dans la zone de valeur** — sortie sous le VAL puis clôture de
   retour dans la zone.
3. **Cassure** — clôture au-dessus du VAH, repli, reprise du plus haut.

Stop propre à chaque trade, objectif à 2 fois le risque (2R).

### Ce qui a fait passer la stratégie de perdante à gagnante

La version initiale, fidèle aux règles d'origine, **perdait** : trop de
trades à stop serré (0,2 – 0,3 %), où le spread et la commission mangent
tout le gain. Deux réglages, mesurés un par un, ont changé le résultat :

- **Stop plafonné à 1,5 %** : un stop de pattern trop loin donnait un
  objectif inatteignable qui bloquait le bot jusqu'à 24 jours ;
  l'immobilisation maximale tombe à ~8 jours.
- **Objectif minimal de 1,5 %** : les petits trades sont ignorés — ils
  perdaient déjà avant même les coûts.

Mesure sur **ETH, BTC et DOGE × 4 semestres 2025-2026 = 12 fenêtres**
(entrées 15 min, stops et objectifs vérifiés sur bougies d'1 minute) :

| Réglage | Spread 0 | Spread 0,06 % | Spread 0,1 % |
|---|---|---|---|
| Règles d'origine | 5/12 fenêtres gagnantes, somme −68,6 % | 2/12, −194 % | 2/12, −268 % |
| **Plafond 1,5 % + objectif ≥ 1,5 %** | **7/12, médiane +8,1 % / semestre, somme +58,6 %** | **7/12, médiane +6,5 %, somme +11,9 %** | **7/12, médiane +5,4 %** |

Sur l'ETH seul, année par année, comparé au simple fait de garder l'ETH :

| | 2025 | 2026 (au 10/10) |
|---|---|---|
| Garder l'ETH | −10,9 % | −15,6 % |
| **Volume Profile, spread 0** | **+43,3 %** | **+11,3 %** |
| **Volume Profile, spread 0,06 %** | **+28,5 %** | **+4,2 %** |

Gagnante sur deux années où l'ETH baissait, y compris avec un spread
réaliste. Avec les ventes à découvert en plus et sans coûts, la somme des
12 fenêtres monte à **+105 %** (8 fenêtres gagnantes sur 12).

### Les limites, dites franchement

- **DOGE perd** avec coûts (−29 % à 0,06 % de spread) : ETH et BTC portent
  le résultat. La stratégie n'est pas universelle.
- **2026 est nettement moins bon** : marché plus calme (amplitude
  journalière 4,5 % contre 5,9 % en 2025), les gros gagnants à stop large
  ont presque disparu, et **acheter en tendance baissière perd**. Les achats
  en tendance haussière gagnent, eux, chaque année — piste en cours de
  mesure.
- **Les ventes à découvert ne passent pas les coûts** : leur avantage par
  trade est minuscule, seuil de rentabilité vers 0,03 % de spread
  aller-retour, en dessous des spreads crypto courants.
- 12 fenêtres, une seule famille de marchés corrélés : un avantage modeste
  et à confirmer, pas une preuve. La stratégie tourne en paper, pas en réel.

---

## Les courtiers

| Courtier | Usage dans le projet | Vente à découvert |
|---|---|---|
| **Binance** (testnet) | Bots crypto en paper trading, au comptant | Non |
| **Interactive Brokers** | Actions Euronext (PEA/CTO) et bot d'investissement régulier, compte paper | Non (comptant) |
| **Capital.com** | CFD crypto : connecteur compte démo, lecture en direct du spread et du financement de nuit | Oui |
| **Trade Nation** | CFD à spread fixe, profil de coûts dans l'atelier | Oui |
| **NinjaTrader** | Micro-futures CME BTC / ETH, profil de coûts dans l'atelier | Oui |

Interactive Brokers est le seul courtier PEA/CTO qui ouvre une API publique :
Bourse Direct, BoursoBank, Fortuneo ou Degiro n'en proposent aucune.

Garde-fous côté courtier : ports du compte réel IBKR refusés par le code,
comptes non « paper » bloqués, symboles vérifiés (sur IBKR, `SAN` désigne
Banco Santander, pas Sanofi), réconciliation des positions avant tout
ordre, et un mode argent réel construit mais **volontairement non branché**
(cinq garde-fous indépendants, dont une clé API sans droit de retrait).

---

## La vraie difficulté : les commissions et les coûts

Le constat le plus constant du projet : **ce sont les coûts, plus que la
stratégie, qui décident du résultat**. Et ils sont difficiles à modéliser,
parce que chaque courtier facture différemment :

- **Quatre coûts de nature différente** : commission par ordre (en % ou en
  montant fixe), spread (en % ou en *points* par unité, à convertir au cours
  du moment), financement de nuit pour les CFD (différent à l'achat et à la
  vente, parfois un crédit), et taxes.
- **Les minimums par ordre écrasent les petits comptes.** Mesuré sur IBKR :
  plancher de 3,00 € par ordre sur Euronext Paris plus 0,4 % de taxe
  française à l'achat, soit **3,4 % d'aller-retour sur une position de
  200 €** avant tout mouvement de cours. Le scanner multi-actions passe de
  « bat le marché » à **−99,67 %** avec 1 000 € de capital.
- **Les spreads crypto des CFD ne sont presque jamais publiés** : seul celui
  du Bitcoin l'est ; les autres sont estimés, et l'atelier le signale.
- **Le paper trading ne facture pas les commissions** (0,00 constaté sur des
  exécutions IBKR réelles) : un résultat paper est toujours plus flatteur que
  le réel, du montant exact des frais.
- **Un petit spread suffit à tout inverser** : la version d'origine du
  Volume Profile passe de +13,6 % à −122 % avec seulement 0,06 % de spread,
  à cause de ~200 trades par semestre.

D'où les choix de l'outil : un **sélecteur de courtier** dans l'atelier qui
remplit commission, spread et financement à partir de relevés publics
datés (sources affichées, lecture en direct chez Capital.com), des filtres
de stratégie qui écartent les trades trop petits pour couvrir leurs coûts,
et des mesures systématiquement refaites à plusieurs niveaux de spread.

---

## Démarrage rapide

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/python -m tradingbot.control_server
```

Puis ouvrir `dashboard.html`. Commandes détaillées (backtests, paper
trading Binance et IBKR, Raspberry Pi, HTTPS) :
[docs/GUIDE_TECHNIQUE.md](docs/GUIDE_TECHNIQUE.md).

> Projet personnel et éducatif. Aucun résultat passé ne garantit un résultat
> futur ; rien ici n'est un conseil en investissement. Tout tourne en argent
> fictif.
