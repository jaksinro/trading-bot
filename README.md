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

### Backtester une action (Yahoo Finance) au lieu de la crypto

En plus de la crypto (ccxt), le backtest peut utiliser Yahoo Finance comme
source de donnees pour une action : `exchange: yfinance` et un ticker Yahoo
en `symbol` (ex. `TTE.PA` pour TotalEnergies sur Euronext Paris), voir
`config/TTE_SWING_TEST.yml`. **Bougies journalieres uniquement** (`timeframe:
1d`) - l'historique intrajournalier Yahoo Finance est trop limite (~2 ans)
pour un backtest fiable. `optimize.py`/`reoptimizer.py` restent crypto/binance
uniquement (voir plus bas pour le paper trading actions via Interactive Brokers).

```bash
.venv/Scripts/python -m tradingbot.run_backtest config/TTE_SWING_TEST.yml
```

Recherche de parametres menee sur TotalEnergies puis 5 autres actions
(Orange, Societe Generale, Renault, Air France-KLM, ArcelorMittal) :
`dip_bounce` ne bat quasiment jamais le buy & hold sur une action en
tendance haussiere forte, mais devient credible (protection de capital via
stop-loss/trailing, pas une meilleure selection d'entrees) sur une action en
baisse ou chahutee - `config/RNO_SWING_TEST.yml` (Renault) et
`config/AF_SWING_TEST.yml` (Air France-KLM) reprennent les meilleurs
reglages trouves sur leur periode de test out-of-sample.

### Scanner multi-actions (surveille plusieurs actions, achete le creux le plus profond)

```bash
.venv/Scripts/python -m tradingbot.multi_symbol_scanner --universe TTE.PA,ORA.PA,GLE.PA,RNO.PA,AF.PA,MT.AS,AI.PA,MC.PA,OR.PA,SAN.PA,BNP.PA --since 2020-01-01 --capital 1000
```

Surveille un panier d'actions en parallele (meme regle `dip_bounce` pour
chacune) et achete celle dont le creux est le plus profond en cas de
signaux multiples le meme jour. **Backtest uniquement** - module autonome
(`multi_symbol_scanner.py`), pas d'integration dashboard/paper trading dans
ce lot.

Recherche "carte blanche" de parametres (sweep de 972 combinaisons,
train/test 70/30 par symbole, classement par P&L REALISE plutot que
rendement total - un premier classement naif par rendement total etait
trompeur, domine par des positions encore ouvertes profitant d'un test se
terminant en plein marche haussier).

Reglage retenu et defaut actuel : **trailing stop 10%, sans take-profit**
(`trend_ma_period=10`, `dip_threshold_pct=1%`, `stop_loss_pct=12%`,
`max_concurrent_positions=5`, `max_position_size_pct=33%`). Un take-profit
fixe plafonne le gain de chaque trade et, apres la vente, `dip_bounce` ne
peut plus revenir dans une hausse soutenue (plus de creux a acheter) : le
capital dort en cash pendant que l'action monte. Le trailing laisse courir
les positions gagnantes jusqu'au retournement.

Chiffres mesures : periode complete 2020-2026 **+138,27% contre +108,55%**
pour le panier egal-pondere achete et garde, avec un P&L **realise** de
+1354,65 pour seulement +28,00 de non-realise (la performance est bien
encaissee, contrairement au premier backtest ou 0% des trades clos etaient
gagnants), et **+10,05% contre -4,58%** pour le marche sur la moitie
baissiere de la periode de test. **Constat honnete** : sur la tranche de
test stricte (out-of-sample), le scanner est a egalite, legerement en
dessous du buy&hold (+42,83% contre +44,43%) - aucun edge prouve sur le
rendement pur. Ce qui est demontre : les gains sont reellement realises et
la tenue en marche baissier est nettement meilleure. Comme partout ailleurs
dans ce projet, cette famille de strategies protege le capital plutot que
de battre un buy&hold haussier.

### Modele de regime de tendance sur ETH (investi en hausse, liquidites en baisse)

```bash
.venv/Scripts/python -m tradingbot.run_backtest config/ETH_TREND_REGIME.yml
```

Reste investi tant que le cours depasse sa tendance de fond, et passe **tout
en liquidites** des qu'il repasse dessous. C'est la difference avec le filtre
de tendance optionnel, qui bloque seulement les nouveaux achats sans jamais
fermer une position - on traversait donc tout le marche baissier en
portefeuille.

**Long-only, donc gagner de l'argent PENDANT une baisse est hors de portee**
(pas de vente a decouvert sur le spot) : l'objectif est de rester plat au
lieu de subir.

Mesure sur ETH/USDT, 6,7 ans de bougies 1h, reglage choisi sur les 70%
d'entrainement puis test regarde une seule fois :

| modele | test (out-of-sample) | baisse max |
|---|---|---|
| buy & hold | -35,17 % | -69,15 % |
| `dip_bounce` (ancien reglage de production) | -62,72 % | -78,26 % |
| **`trend_regime`** | **+54,70 %** | -45,65 % |

Par regime sur tout l'historique : **+61 % par semestre haussier, +0,7 % par
semestre baissier**, contre +83 % / -41 % pour le buy & hold. On cede une
partie de la hausse pour ne plus subir la baisse.

**Deux controles de robustesse** avant de conclure : 41 des 45 reglages de la
grille battent le buy & hold (toutes les fenetres de 3 semaines a 5,5 mois
fonctionnent, seule une fenetre trop courte se fait hacher), et le resultat
survit a une execution decalee d'une bougie (+54,70 % -> +34,83 %), plus
realiste qu'un achat au cours de cloture qui declenche le signal.

**Teste sur 9 autres cryptos**, avec les parametres d'ETH appliques tels
quels (pas de reoptimisation par actif). Retenus et lances en paper :
**BTC/USDT** (+36,3 % en test contre +10,6 % pour le buy & hold) et
**DOGE/USDT** (+141,3 % contre -38,5 %). Ecartes : SOL, LINK et AVAX, qui
battaient le buy & hold **tout en perdant de l'argent** (AVAX detruit 58 % du
capital en faisant "mieux" qu'un marche a -83 %) ; ADA, dont la mediane de
grille est negative (le reglage etait chanceux) ; BNB, XRP et TRX, des actifs
en hausse soutenue ou filtrer le regime ne fait que rater la hausse - sur TRX,
aucun des 45 reglages ne bat le simple achat conserve.

**Le modele n'est donc pas universel** : il ne paie que la ou il y a de vraies
baisses a eviter. Et ces 10 cryptos partagent les memes periodes de marche,
ce qui n'en fait pas 10 validations independantes.

> **Attention au backtest de cette config depuis le dashboard** : sans panier
> de capital commun, le moteur dimensionne sur le capital initial FIGE, donc
> un modele a nombreux allers-retours peut "acheter" plus que son cash et
> afficher un resultat gonfle. En paper trading la taille est correctement
> bornee par le cash disponible. Les chiffres ci-dessus viennent d'un banc
> dedie dimensionnant sur l'equite courante.

### Bot d'investissement regulier (versements programmes + allocation cible)

```bash
.venv/Scripts/python -m tradingbot.dca_allocator --since 2015-01-01 --monthly 200 --weights TTE.PA,ORA.PA,GLE.PA,RNO.PA,AF.PA,MT.AS
```

Contrairement a tous les autres bots du projet, celui-ci **ne cherche pas a
predire le marche**. Raison assumee : aucune recherche de parametres menee
ici (crypto EF-19/EF-26, actions EF-64, scanner EF-66 avec 972
combinaisons) n'a demontre out-of-sample de capacite a battre un panier
diversifie achete et garde. Il automatise donc seulement ce qui fonctionne
sans edge predictif : verser une somme fixe a date fixe, maintenir une
allocation cible, et mesurer honnetement.

**Aucun stop-loss, volontairement** (a l'inverse du reste du projet) :
vendre parce que ca baisse transforme une baisse temporaire en perte
definitive. Le resultat est mesure en **rendement pondere par les flux**
(un rendement total est denue de sens quand on ajoute de l'argent en cours
de route), avec titres entiers et **frais minimum par ordre** (~1,25 EUR
chez IBKR sur Euronext) - ce plancher est determinant, pas cosmetique :
eclater 200 EUR sur 11 lignes fait des ordres de 18 EUR sur lesquels
1,25 EUR pese 7 %.

Constat honnete, valide sur 6 fenetres temporelles independantes : **les
variantes "intelligentes" d'allocation n'apportent rien de mesurable**
(+15,87 % / +15,75 % / +15,73 % par an sur 11,7 ans selon la variante, soit
0,14 point d'ecart - du bruit). Ce qui pese reellement, ce sont les frais
(2,24 % du total verse) et le cash qui dort, pas la mecanique d'allocation.
A ne pas masquer : **baisse maximale de -50 %** sur la periode, et la
fenetre 2017-2021 perd environ 10 % par an pour toutes les variantes. Le
panier donne en exemple est tres concentre (large caps Euronext
France/Pays-Bas) - le choix de l'allocation, qui reste celui de
l'utilisateur, pese incomparablement plus que ce module.

#### Le faire tourner pour de vrai (paper trading IBKR, argent fictif)

```bash
# Simulation : montre ce que le bot ferait aujourd'hui. N'envoie rien,
# n'enregistre rien, et fonctionne meme sans TWS installe.
.venv/Scripts/python -m tradingbot.run_dca --config config/dca/DCA_EURONEXT.yml
```

```bash
# Passe reellement les ordres sur le compte PAPER (necessite TWS/IB Gateway
# connecte en mode paper, voir la section Interactive Brokers plus bas).
.venv/Scripts/python -m tradingbot.run_dca --config config/dca/DCA_EURONEXT.yml --execute
```

Le bot est pilote par un calendrier : il se lance, agit s'il y a lieu, puis
ressort (il n'a rien a faire 29 jours sur 30). A planifier quotidiennement
plutot qu'a laisser tourner en boucle. Garde-fous :

- **Simulation par defaut** : aucun ordre ne part sans `--execute`, et la
  simulation ne consomme pas le versement du mois.
- **Versement idempotent** : la cle primaire de la table des versements est
  le mois, donc relancer le bot deux fois le meme mois ne peut pas verser
  deux fois - meme apres un plantage en cours de route.
- **Reconciliation avant d'agir** : si les positions du courtier ne
  correspondent pas au registre local, AUCUN ordre ne part et l'ecart est
  affiche.
- **Prix reellement executes** enregistres, pas les prix planifies.
- **Ports du compte reel (7496/4001) refuses par le code**, quelle que soit
  la configuration.

Les decisions ne sont pas reimplementees pour le live : `run_dca.py` appelle
les memes fonctions pures que le backtest, pour que le bot qui passe des
ordres soit exactement celui qui a ete mesure.

#### Depuis le dashboard

L'onglet **💰 Investissement** fait la meme chose sans terminal :

- **Suivi** : total verse, valeur, gain, rendement annualise pondere par les
  flux, baisse maximale subie, frais, et l'allocation reelle de chaque ligne
  face a sa cible (l'ecart passe en rouge hors de la bande). Deux boutons :
  *Simuler le passage du jour* (n'envoie rien, n'enregistre rien) et
  *Executer reellement*. La valorisation affichee utilise les derniers cours
  connus (dernier passage du bot), pas le direct - ce bot n'agit qu'une fois
  par mois.
- **Reglages** : creer, modifier ou supprimer un bot (allocation a poids
  relatifs, versement mensuel, bande de rééquilibrage, frais, port IBKR).
  Supprimer un bot **conserve son historique** de versements et d'ordres.

Les configs de ces bots vivent dans `config/dca/` (et non `config/`, reserve
aux bots mono-symbole pilotes par `run_paper.py`).

> Un dashboard mis a jour n'apparait qu'apres **redemarrage des bots** :
> chaque bot en cours reecrit `dashboard.html` a chaque cycle depuis le
> template embarque dans le code charge a son demarrage. Utilise le bouton
> "Redemarrer tous les bots" de Configuration -> Supervision.

**Hors perimetre** : aucun argent reel ; la connexion IBKR reelle n'a pas pu
etre testee de bout en bout (pas de compte disponible), elle est testee avec
un client factice injecte.

## Valider qu'un bot fait ce que le backtest prevoyait

```bash
.venv/Scripts/python -m tradingbot.validate_paper config/ETH_TREND_REGIME.yml config/BTC_TREND_REGIME.yml config/DOGE_TREND_REGIME.yml
```

Confronte les ordres REELLEMENT passes par un bot aux signaux que sa
strategie aurait produits. Sans cet outil, "le bot tourne" ne dit rien.
Trois defauts sont chiffres :

- **Signaux manques** : la strategie a signale, aucun ordre n'a suivi. Le
  plus grave et le plus silencieux - le bot parait en bonne sante mais n'a
  pas agi (plantage, erreur reseau, fonds insuffisants).
- **Ordres inattendus** : un ordre sans signal correspondant (config
  differente de celle rejouee, ou intervention manuelle sur le compte).
- **Glissement de prix** : ecart entre le prix obtenu et la cloture de la
  bougie qui a declenche le signal - le cout que le backtest ne modelise pas.
  Un chiffre **negatif signifie toujours que le reel a coute**, a l'achat
  comme a la vente.

Un bot sans aucun ordre n'est pas une anomalie : `trend_regime` reste en
liquidites environ 60 % du temps, et l'outil le dit explicitement.

### Diversification des bots : ce qui marche et ce qui ne marche pas

Les trois bots `trend_regime` tournent sur des actifs fortement correles.
Avec des reglages identiques, ils sont dans le **meme etat 72,5 % du temps** -
soit un seul pari en trois emballages.

- **Varier les marges d'entree/sortie** : 72,5 % -> 71,9 %. **Cosmetique**,
  non applique. La correlation vient des actifs, pas des reglages.
- **Varier les fenetres de tendance** (500 / 1000 / 2000 bougies, toutes
  validees sur les 3 actifs) : 72,5 % -> **66,7 %**. Modeste mais reel, et
  surtout les 3 bots ne se trompent plus ensemble si une fenetre s'avere
  mauvaise. **Retenu**, avec une attribution neutre - donner a chaque crypto
  sa meilleure fenetre aurait ete de la selection sur la periode de test.

**Ce qui diversifierait vraiment** : une poche non-crypto. Aucun reglage ne
corrige une correlation qui est une propriete du marche.

## Trading avec de l'ARGENT REEL (socle construit, NON ACTIVE)

Tout le reste de ce projet engage de l'argent fictif. Ce mode-ci engage de
vrai argent, et il n'est **volontairement pas branche** au dashboard ni au
lanceur : `execution/live_executor.py` existe, est teste, mais rien ne
l'appelle. C'est un choix - le rendre atteignable en un clic irait contre son
objet.

**Cinq garde-fous independants, chacun capable de refuser seul**, verifies au
demarrage puis a chaque ordre :

1. `BINANCE_LIVE_TRADING_ENABLED` doit valoir **exactement**
   `oui-je-veux-trader-avec-de-l-argent-reel`. Ni `1`, ni `true` : une valeur
   qu'on ne peut pas poser par accident.
2. **Cle API sans droit de retrait**, verifie aupres de Binance. Le demarrage
   est refuse si la cle peut retirer, et **aussi si la verification echoue** -
   on ne suppose pas que tout va bien faute d'information. Une fuite de cle
   avec retrait est le seul risque impossible a reparer apres coup.
3. **Plafond par ordre** obligatoire, sans defaut : l'oublier empeche le
   demarrage.
4. **Arret d'urgence** : creer un fichier `STOP_LIVE_TRADING` a la racine
   bloque tout ordre immediatement, sans dashboard ni redemarrage.
5. **Coupe-circuit de perte journaliere** en montant absolu.

Le plafond et le coupe-circuit ne bloquent que les **achats** : bloquer une
vente enfermerait dans une position, soit un garde-fou qui aggrave le risque.
Seul l'arret d'urgence bloque aussi les sorties.

> **Avant d'activer, relire les chiffres.** Le modele ETH fait -8,9 % sur 2026,
> 34 % de ses mois hors echantillon sont positifs, sa pire baisse (-49,5 %)
> s'est produite sur des donnees qu'il n'avait jamais vues, et tout son
> avantage historique repose sur un seul marche baissier. Les frais reels, le
> slippage et les filtres d'exchange ne sont pas dans le backtest - et 20
> points de rendement partent deja rien qu'en decalant l'execution d'une
> bougie.

### Verifier la connexion IBKR avant de lancer un bot

```bash
.venv/Scripts/python -m tradingbot.diagnose_ibkr
```

Une commande pour savoir OU ca casse, plutot que de le decouvrir via un bot
qui plante au demarrage. **Ne passe aucun ordre** : le diagnostic lit
seulement. Il verifie, en s'arretant au premier blocage :

1. **Le port** - 7496 et 4001 sont les ports du compte REEL et sont refuses
   avant meme la connexion. Utilise 4002 (IB Gateway paper, defaut) ou 7497
   (TWS paper).
2. **Le compte** - les comptes paper IBKR sont prefixes `DU`. Un compte
   non-`DU` bloque tout : se connecter par erreur a une session reelle doit
   arreter le diagnostic, pas seulement l'annoter.
3. **Chaque ticker** - affiche ce qu'IBKR a REELLEMENT retenu (symbole,
   place, `conId`). C'est ce qui permet de corriger la table de traduction
   `TTE.PA` -> `TTE`/SBF sur des faits. Un ticker en echec n'interrompt pas
   les autres.
4. **Les donnees de marche** - une bougie journaliere par ticker qualifie.

Verifie contre une vraie session paper le 2026-09-18 : les correspondances
de place de cotation sont justes, 10 des 11 actions de l'univers se qualifient
sans modification. **Sanofi est l'exception** : son symbole IBKR est `SAN1`,
pas `SAN` - et `SAN` seul designe **Banco Santander**. La table
`YAHOO_TICKER_TO_IB_SYMBOL` couvre ce cas. Ne "repare" jamais un ticker en
retirant sa place principale : c'est ce forcage qui empeche d'acheter
silencieusement une autre entreprise.

> **Le piege que le diagnostic ne peut pas detecter.** L'option **"Read-Only
> API"** de Configuration globale > API > Parametres est **activee par
> defaut**. Avec elle, la connexion s'etablit, les comptes remontent, les
> prix arrivent - et **tous les ordres sont rejetes**. Le diagnostic passera
> entierement au vert. Decoche-la (le detecter exigerait de tenter un ordre,
> ce que cet outil s'interdit).


> **AVERTISSEMENT sur le scanner multi-actions (mesure le 2026-09-18).** Les
> frais reels d'Interactive Brokers ont ete mesures contre le compte paper :
> **plancher de 3,00 EUR par ordre** sur Euronext Paris, auquel s'ajoute la
> taxe francaise de 0,4 % a l'achat. Soit **3,4 % d'aller-retour sur une
> position de 200 EUR**, avant tout mouvement de cours. Sur les 229 trades du
> backtest, le scanner tombe a **-99,67 % a 1 000 EUR de capital** (les frais
> depassent le capital) contre +107,78 % pour un simple achat-conservation du
> panier. Meme a 100 000 EUR, ou la commission devient negligeable, il ne
> depasse le panier que de 0,7 point par an - dans le bruit. **Ce module est un
> banc de mesure, il ne doit pas etre deploye.** Voir STC §3.57.


> **A savoir avant de lancer un bot actions (constate en reel, EF-76).**
> IB Gateway applique un "prereglage d'ordre" qui **annule tout ordre venu de
> l'API** s'il doit le modifier (code 10349) - le bot declare donc son `tif`
> lui-meme. Plus important : un ordre rapporte "annule" par l'API **peut
> avoir ete execute quand meme** (observe : annonce annule, execute 0,5 s
> plus tard). Le code croit desormais les executions du courtier plutot que
> le statut annonce. Enfin, `IBPaperExecutor` ne reconcilie PAS son
> portefeuille avec les positions reelles du compte : verifie que ton compte
> paper est vide avant de lancer un bot sur un titre, sinon le bot ignorera
> la position existante. Voir STC §3.59.
>
> **Le mode paper ne facture pas les commissions** (constate : 0,00 sur 4
> executions reelles, alors que le courtier chiffre un minimum de 3,00 EUR
> par ordre). Tout resultat paper est donc plus flatteur que le reel, du
> montant exact des frais. Les frais doivent etre modelises dans la config du
> bot, jamais deduits des executions paper. Voir STC §3.60.

## Deployer sur un Raspberry Pi (et ouvrir le dashboard a toute la maison)

Materiel conseille : **Raspberry Pi 5, 8 Go, sur SSD** (NVMe via HAT ou USB 3),
alimentation officielle, boitier ventile. Pas de carte SD comme disque
systeme : les bots ecrivent en continu (SQLite + `dashboard.html` a chaque
cycle), ce qui use une carte SD en quelques mois. Un Pi 4 en 4 Go suffit pour
les bots seuls ; les 8 Go absorbent les backtests.

```bash
git clone https://github.com/jaksinro/trading-bot.git && cd trading-bot
cp .env.example .env && nano .env      # cles testnet + DASHBOARD_PASSWORD
bash scripts/install_pi.sh
```

L'installateur cree l'environnement Python, installe deux services systemd
(`tradingbot-server` puis `tradingbot-bots`) et affiche l'adresse a taper
depuis un telephone : `http://<ip-du-pi>:8765/dashboard.html`.

**Mot de passe obligatoire.** Le serveur ecoute sur le reseau, mais refuse
tout appareil autre que lui-meme tant que `DASHBOARD_PASSWORD` est vide
dans `.env` (403 avec le message qui le dit). Une fois defini, le navigateur
demande l'identifiant (`DASHBOARD_USER`, defaut `trader`) une fois et s'en
souvient.

**HTTPS (recommande).** Sans lui, le mot de passe et les ordres circulent en
clair sur le reseau local. Pour chiffrer :

```bash
bash scripts/generate_dashboard_cert.sh    # certificat auto-signe dans certs/
# puis dans .env :
#   DASHBOARD_TLS_CERT=certs/dashboard.crt
#   DASHBOARD_TLS_KEY=certs/dashboard.key
sudo systemctl restart tradingbot-server
```

L'adresse devient `https://<ip-du-pi>:8765/dashboard.html`. Certificat
auto-signe : chaque navigateur previent une premiere fois ("connexion non
privee"), accepter l'exception. Le certificat couvre `localhost`, le nom du
Pi et ses IP du moment ; si l'IP du Pi change, supprimer `certs/` et relancer
le script (ou lui passer l'IP/le nom voulus en argument). Les scripts de
demarrage automatique detectent HTTPS tout seuls. Meme avec HTTPS, ne pas
exposer le dashboard a Internet (pas de redirection de port sur la box).

**Limite** : IB Gateway (actions) n'existe officiellement qu'en Linux
x86-64. Le Pi porte les cryptos et le dashboard ; les actions restent liees
a une machine x86 (`IBKR_HOST` peut pointer vers elle par le reseau).

## Lancer le mode paper actions (Interactive Brokers, aucun argent reel)

Seul courtier PEA/CTO avec une API publique (la quasi-totalite des courtiers
francais - Bourse Direct, BoursoBank, Fortuneo, Degiro... - n'en ont aucune).
Prealables (hors du controle de ce projet) :

1. Ouvrir un compte Interactive Brokers.
2. Installer TWS ("Trader Workstation") ou IB Gateway, le connecter en mode
   **PAPER** (jamais LIVE tant que l'argent reel n'est pas explicitement voulu).
3. Activer l'API : Configuration globale > API > Parametres.
4. Copier `.env.example` en `.env` et renseigner `IBKR_HOST`/`IBKR_PORT`
   (7497 = TWS paper, 4002 = IB Gateway paper).

Puis creer un bot depuis le dashboard (Configuration > Creation, "Type de
compte" = "Actions (paper trading Interactive Brokers)") - bougies
journalieres uniquement, quantites en actions entieres, panier de capital
separe du panier crypto. Sans TWS/IB Gateway joignable, le bot echoue tout
de suite avec un message clair plutot que de rester bloque silencieusement.

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

Teste des centaines de combinaisons de parametres par paire (sma_cross,
scalp_dip, mean_reversion, market_making, et dip_bounce — stop-loss,
trailing stop, filtre de tendance jusqu'a EMA300, verrou de gain), avec ou
sans filtre de tendance, avec ou sans sizing ATR (selon la strategie) sur
3 ans d'historique 1h, decoupes chronologiquement en 70% entrainement / 30%
test. Avec plusieurs `--symbols`, une seule config est ecrite pour le
(symbole, reglage) gagnant global — pour un reglage propre a CHAQUE crypto,
lancer l'outil une fois par symbole.
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
- [x] Risk manager (taille de position, stop-loss, take-profit, perte max journaliere, anti-accumulation de pertes, trailing stop) — la perte max journaliere n'etait en fait **jamais alimentee par le moteur** jusqu'au 2026-09-18 : configuration presente partout, annoncee ici, testee unitairement, mais inerte. Cablee depuis, avec des tests integres. Attention : une limite a `0` signifie **tolerance zero**, pas desactive, et l'arret ne bloque que les achats (bloquer une vente enfermerait dans une position)
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
- [x] Tests unitaires + integration (1077 tests)
- [x] Bot d'investissement regulier (versements programmes + allocation cible, sans stop-loss), backtest, paper trading IBKR ET onglet dashboard dedie — simulation par defaut, versement idempotent, reconciliation avec le courtier. Constat honnete : les mecaniques d'allocation n'apportent rien de mesurable, les frais et le cash dormant pesent davantage
- [x] Filtre de tendance optionnel (EMA) pour eviter les achats a contre-courant, integre a l'optimizer — voir docs/FEUILLE_DE_ROUTE_PERFORMANCE.md
- [x] Sizing optionnel par volatilite (ATR) — resultat mitige, desormais inclus dans la grille de `optimize`/`reoptimizer`
- [x] Sortie partielle optionnelle (scale-out) — compromis risque/rendement, desactive par defaut sur tous les bots
- [x] Bot d'auto-reoptimisation periodique (`reoptimizer.py`, `--name`/`--all`), bouton dashboard "tout reoptimiser", frequence hebdomadaire, test A/B groupe auto (applique automatiquement) vs control (jamais) pour mesurer l'efficacite reelle
- [x] Strategie **regime de tendance** (ETH) : investie au-dessus de sa tendance, liquidites en dessous - premier resultat out-of-sample positif du projet (+34,8% a execution realiste contre -35,1% pour le buy & hold), robustesse verifiee sur toute la grille de reglages
- [~] Mode reel (argent reel) : socle `LiveExecutor` construit et teste (5 garde-fous independants), **non branche** au dashboard/lanceur - validation en paper en cours avant toute activation
- [ ] Mode live — a venir, hors perimetre tant que le paper n'est pas valide sur plusieurs jours
