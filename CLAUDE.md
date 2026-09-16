# Instructions de collaboration - Trading Bot

## Directive permanente

**Être force de proposition d'innovation et apporter des idees a l'utilisateur.**

Concretement, avant de simplement executer une demande a la lettre :
- Signaler les limites ou risques que je remarque dans l'existant, meme si on ne me le demande pas (ex: capital partage entre instances, delai avant premier signal).
- Proposer 1-2 idees concretes et pertinentes en lien avec la demande en cours (nouvelle metrique, garde-fou, strategie, visualisation), sans les implementer sans validation si elles sortent du perimetre demande.
- Rester bref : une idee proposee clairement vaut mieux que cinq noyees dans le texte.
- Ne jamais bloquer la demande initiale pour placer une idee : la livrer d'abord, proposer ensuite.

## Documentation a maintenir a jour

**A chaque modification du contenu genere par `src/tradingbot/reporting/dashboard.py`** (HTML/CSS/JS de `dashboard.html`) : ajouter une ligne dans le tableau "Historique des changements de l'interface" en fin de [docs/MANUEL_UTILISATEUR.md](docs/MANUEL_UTILISATEUR.md), et mettre a jour les sections concernees du manuel (nouveaux boutons, nouveaux champs, nouveau comportement). Le manuel s'adresse a un utilisateur non technique : pas de jargon de code, expliquer l'effet visible et son sens.

**A chaque evolution fonctionnelle ou architecturale notable** (nouvelle strategie, nouveau composant, exigence realisee, garde-fou ajoute suite a un incident) : repercuter le changement dans [docs/STB.md](docs/STB.md) (besoin/exigences) et/ou [docs/STC.md](docs/STC.md) (conception/architecture), avec un incrementement de version et une ligne dans leur tableau d'historique respectif. Ces documents suivent le cycle en V du projet et doivent rester le reflet fidele de ce qui est reellement construit.

## Contexte du projet

Bot de trading crypto developpe en cycle en V (voir docs/STB.md et docs/STC.md).
Marche pilote : crypto (Binance testnet). Architecture multi-instance : une
config YAML = un bot independant, son propre verrou anti-doublon
(`bot_{name}.lock`), et ses donnees affichees dans un dashboard partage
(`dashboard.html` + `dashboard_data/`). Depuis v0.18 (STB/STC), tous les bots
piochent dans un **panier de capital commun** (`data/shared_pool.db`, voir
`shared_pool.py` et STC section 3.5 revisee) plutot que d'avoir un capital
isole : `capital_allocated` en config est desormais un plafond de mise
dynamique, ajuste automatiquement selon la performance recente du bot
(EF-37), pas un budget qui lui serait exclusivement reserve.

Points de vigilance connus (a garder en tete avant de proposer des changements) :
- Toutes les instances partagent le MEME compte testnet reel (memes cles API) ET
  desormais le meme panier de capital virtuel commun : plus aucune isolation de
  capital entre bots, seule la reservation atomique SQLite (`shared_pool.py`)
  empeche un decouvert quand plusieurs bots achetent en meme temps.
- Le mode reel (argent reel) n'existe pas encore : seuls backtest et paper sont implementes.
- Les strategies actuelles sont volontairement simples (SMA cross, scalp sur dip) :
  bonnes pour valider le pipeline, pas pour juger d'une vraie edge de marche.
