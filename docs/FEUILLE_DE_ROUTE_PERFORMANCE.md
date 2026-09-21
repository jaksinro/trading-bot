# Feuille de route : amélioration de la performance et du rendement

| | |
|---|---|
| **Version** | 0.15 |
| **Date** | 2026-09-14 |
| **Statut** | Étapes 1 à 5 intégrées et testées, étape 5 étendue (bouton "tout réoptimiser", ATR dans la grille, fréquence hebdomadaire, test A/B auto/control) — résultats du test A/B à suivre dans le temps. Étape 4bis : second passage de consolidation (8→5 bots) + reoptimisation + augmentation de l'utilisation du panier commun. Étape 4ter : flotte reconstruite en 1 bot par crypto du top 10 par capitalisation (10 bots). Étape 4quater : correction de l'utilisation du capital sur les 6 bots validés (capital moyen déployé +121%). Étape 6 (robustesse/fiabilité de l'edge) : toutes les pistes traitées, en pause faute de bénéfice net démontré. Étape 7 (market making natif) : testée, résultat négatif. Étape 8 (funding rate arbitrage, Phase A backtest) : testée, résultat non concluant. Étape 9 (rebond de creux sans stop-loss + buy & hold, proposée par l'utilisateur) : implémentée, intégrée au dashboard, résultat empirique mitigé |

## Principe de suivi

**Une étape à la fois.** Chaque étape doit être intégrée, testée (tests unitaires + backtest comparatif avant/après) et validée par l'utilisateur avant de passer à la suivante. On ne cumule pas plusieurs changements non validés — sinon, en cas de dégradation de performance, on ne saurait pas lequel des changements en est la cause.

Pour chaque étape, la validation attend :
1. Les tests unitaires passent (suite complète, pas de régression).
2. Un backtest comparatif (même période, mêmes paires) montre l'effet du changement — chiffré, pas juste "ça a l'air d'aller".
3. Le retour de l'utilisateur après revue des résultats.

Seulement après ce feu vert, l'étape suivante démarre.

---

## Étape 1 — Filtre de tendance / régime de marché

**Objectif** : éviter de trader à contre-courant d'une tendance de fond. `sma_cross` peut whipsaw en marché plat, `scalp_dip` peut acheter des creux pendant une chute continue ("catching a falling knife").

**Changement** : nouveau composant `TrendFilter` (moyenne mobile exponentielle longue période, ex. EMA200) — un achat n'est autorisé que si le prix actuel est au-dessus de l'EMA (régime haussier). Optionnel et désactivé par défaut, comme le filtre de probabilité existant (EF-18), pour ne rien changer aux instances existantes tant qu'il n'est pas explicitement activé.

**Validation avant de passer à l'étape 2** :
- ✅ Tests unitaires du `TrendFilter` (calcul EMA, détection régime haussier/baissier) — 32 tests ajoutés (`test_trend_filter.py`, `test_engine_trend_filter.py`, `test_trend_status_and_build.py`, extensions `test_control_server.py`/`test_warm_up_price_history.py`). Suite complète : 192 tests passent.
- ✅ Backtest comparatif effectué, depuis 2024-01-01 (~2,6 ans de données réelles Binance), EMA200→EMA50 (adapté pour rester réactif sur les timeframes courts testés) :

| Scénario | Sans filtre | Avec filtre EMA50 |
|---|---|---|
| BTC/USDT `sma_cross` (config réelle `btc_sma_cross_v1`) | -6,45 % (DD 10,21 %, 471 trades) | **-1,45 % (DD 6,33 %, 324 trades)** |
| DOGE/USDT `scalp_dip`, 5 positions simultanées (config réelle `doge_scalp_v1`, cas CT-08) | -434,58 % (DD 434 %, 10310 trades) | **-65,98 % (DD 68,29 %, 1683 trades)** |
| DOGE/USDT `scalp_dip`, 1 position (config réaliste) | -222,69 % (DD 222,77 %, 5508 trades) | **-41,92 % (DD 43,22 %, 1028 trades)** |

**Constat honnête (1er backtest, paramètres par défaut non optimisés)** : le filtre réduit systématiquement le nombre de trades (÷4 à ÷6) et le drawdown dans les 3 scénarios — il bloque bien une partie significative des achats à contre-courant. Mais aucune des deux stratégies n'était rentable sur cette période réelle 2024-2026 avec des paramètres par défaut arbitraires, filtre ou pas. Les pourcentages DOGE (au-delà de -100 %) révèlent aussi une limite préexistante du simulateur de backtest, sans lien avec le filtre de tendance : le dimensionnement des ordres (`size_for_signal`) est basé sur le capital de départ fixe, pas sur le cash réellement disponible (choix assumé pour le multi-positions, STC §3.12) — sur un test très long avec une stratégie perdante, le cash simulé peut devenir très négatif, ce qu'un exchange réel empêcherait. La comparaison relative (avec/sans filtre) reste valide, mais les pourcentages absolus de ces 2 scénarios DOGE ne doivent pas être pris au pied de la lettre. *(Piste pour une prochaine feuille de route : plafonner le dimensionnement au cash réellement disponible.)*

**Suite immédiate — le filtre de tendance intégré à l'optimiseur (EF-30 + EF-19/EF-26)** : plutôt que de rester sur des paramètres par défaut arbitraires, `optimize.py` a été étendu pour inclure le filtre de tendance (EMA 50/100/200, ou désactivé) comme dimension de recherche, avec la même validation out-of-sample (70% entraînement / 30% validation) que l'existant. Résultat sur BTC/USDT + DOGE/USDT (3 ans, 480 combinaisons par paire) :

| # | Config | Entraînement | Validation (jamais vue) |
|---|---|---|---|
| 1 | DOGE/USDT sma_cross(20,100), stop_loss 2%, **trend_ema=200** | +25,05 % | **+1,83 %** (DD 2,7%, 27 trades) |
| 3 | BTC/USDT sma_cross(15,100), stop_loss 2%, **trend_ema=200** | +9,09 % | **+0,14 %** (DD 1,9%, 29 trades) |

**Résultat clé** : c'est la première fois qu'un backtest out-of-sample produit un rendement **positif** sur données jamais vues — les 4 meilleures configs du classement utilisent toutes le filtre de tendance (EMA100 ou EMA200). Modeste (+1,83% et +0,14% sur la période de validation) et l'écart train/validation reste un signe de surapprentissage à surveiller, mais c'est un vrai edge mesuré, pas juste "moins de perte". Config DOGE écrite dans `config/optimized_dogeusdt_sma_cross.yml` — **attention, ce fichier est aussi celui du bot `optimized_dogeusdt_sma_cross` actuellement en cours d'exécution** ; le bot tourne encore sur l'ancienne config tant qu'il n'est pas redémarré.

- ✅ Retour utilisateur obtenu sur le 1er backtest (a demandé la clarification perte/gain — répondu, puis a validé la suite avec l'optimiseur).

**Statut** : ✅ étape validée. **Décision utilisateur** : passer directement à l'étape 4, les étapes 2 et 3 sont reportées (pas annulées) — voir statut de la feuille de route en tête de document.

---

## Étape 2 — Sizing basé sur la volatilité (ATR)

**Objectif** : une taille de position fixe (% du capital) prend le même risque en marché calme et en marché agité. Un sizing indexé sur la volatilité réduit l'exposition quand le marché est instable, sans la limiter inutilement quand il est calme.

**Changement** : calcul de l'ATR (Average True Range) sur une fenêtre configurable ; la taille de position est ajustée à la baisse quand l'ATR est élevé par rapport à sa moyenne récente. Reste borné par `max_position_size_pct` (jamais plus que le plafond actuel — seulement moins, en période agitée).

**Validation avant de passer à l'étape 3** :
- ✅ Tests unitaires (`AtrSizer`, `size_for_signal` avec multiplicateur, intégration `Engine`, `build_atr_sizer`/`atr_sizer_status`, réchauffement étendu, validation `control_server`) — 27 tests ajoutés. Suite complète : 227 tests passent.
- ✅ Backtest comparatif effectué (mêmes configs que l'étape 1 + une config à risque connu) :

| Scénario | Sizing fixe | Sizing ATR |
|---|---|---|
| DOGE/USDT sma_cross(20,100)+EMA200 (meilleure config étape 1) | +26,89 % (DD 6,86 %) | +24,22 % (DD 6,87 %) |
| BTC/USDT sma_cross(15,100)+EMA200 (meilleure config étape 1) | +9,23 % (DD 2,65 %) | +7,23 % (DD 2,47 %) |
| DOGE/USDT scalp_dip, 5 positions (config `doge_scalp_v1`, cas CT-08) | -434,58 % (DD 434,03 %) | **-378,48 % (DD 378,70 %)** |

**Constat honnête, différent de l'étape 1** : sur les 2 configs déjà rentables (celles trouvées à l'étape 1), le sizing ATR réduit légèrement le rendement SANS réduire significativement le drawdown — un léger coût sans bénéfice net mesurable ici, car il freine aussi la taille pendant les mouvements volatils profitables, pas seulement les mauvais. Sur la config à risque connu (accumulation de pertes multi-positions, CT-08), il réduit la perte et le drawdown d'environ 13% — un effet réel mais qui atténue un problème déjà mieux traité par le garde-fou anti-accumulation (EF-23) et le filtre de tendance. **Contrairement à l'étape 1, ce n'est pas un gain net clair** : le filtre de tendance avait un effet positif dans tous les scénarios testés, le sizing ATR a un effet mitigé (aide le pire cas, coûte un peu sur les cas déjà bons).
- ⏳ Retour utilisateur — **en attente avant de considérer si le sizing ATR doit être activé sur des bots réels**.

**Statut** : 🟡 intégré et testé, résultat mitigé à discuter avec l'utilisateur avant activation

---

## Étape 3 — Sortie partielle (scale-out)

**Objectif** : actuellement une position se ferme entièrement au premier seuil atteint (stop-loss, take-profit ou trailing stop). Sécuriser une partie des gains à un premier palier tout en laissant courir le reste capture mieux les grandes tendances, sans renoncer à la protection du capital.

**Changement** : `RiskConfig` gagne un seuil de sortie partielle optionnel (ex. vendre 50% du lot à +X%, garder le reste avec le stop-loss/trailing existant). Nécessite d'étendre `Position`/`Portfolio` pour gérer une quantité partiellement vendue sur un même lot.

**Validation** :
- ✅ Tests unitaires (`Portfolio.apply_fill` sortie partielle avec répartition proportionnelle du frais d'entrée, `RiskManager.should_partial_take_profit`, intégration `Engine` — déclenchement unique par lot, stop-loss toujours actif sur le reste) — 14 tests ajoutés. Suite complète : 245 tests passent.
- ✅ Backtest comparatif effectué (mêmes configs que les étapes 1/2) :

| Scénario | Sortie complète | Sortie partielle (palier → fraction) |
|---|---|---|
| DOGE/USDT sma_cross(20,100)+EMA200 | +26,89 % (DD 6,86 %) | +11,79 % (DD 4,61 %) — palier 3% → 50% |
| BTC/USDT sma_cross(15,100)+EMA200 | +9,23 % (DD 2,65 %) | +4,90 % (DD 2,11 %) — palier 3% → 50% |
| DOGE/USDT scalp_dip (config `doge_scalp_v1`, 1 position) | -222,69 % (DD 222,77 %) | -226,08 % (DD 226,22 %) — palier 0,5% → 50% |

**Constat honnête, encore différent des étapes 1 et 2** : sur les stratégies suiveuses de tendance (sma_cross) déjà rentables, la sortie partielle réduit le drawdown d'environ 30-35% mais **réduit aussi le rendement de moitié** — sécuriser la moitié du gain tôt coupe dans les grandes tendances qui font l'essentiel du profit d'une stratégie trend-following. Ce n'est ni un gain net (étape 1) ni un effet mitigé mineur (étape 2), c'est un **vrai compromis risque/rendement** : plus défensif, moins performant. Sur la config scalp_dip déjà perdante, l'effet est légèrement négatif sans compensation. **Décision : reste optionnel et désactivé par défaut** — utile pour un profil plus prudent qui préfère un rendement plus faible avec moins de volatilité, pas une amélioration universelle.
- ⏳ Retour utilisateur — en attente.

**Statut** : ✅ intégré et testé, compromis risque/rendement documenté

---

## Étape 4 — Consolidation des bots de test quasi-identiques

**Objectif** : `TestETH`, `TestETH2proba`, `GAINfoou`, `Testdodge` tournent tous en `scalp_dip` sur DOGE/ETH avec des paramètres proches — le capital et l'attention sont dilués sur des variantes proches au lieu d'accélérer l'accumulation de données statistiquement utiles sur une vraie comparaison A/B.

**Changement** : audit des bots actifs avec l'utilisateur, décision explicite pour chacun (garder comme variante A/B assumée, fusionner, ou arrêter), documentation de la raison d'être de chaque bot restant dans le manuel utilisateur.

**Décisions validées par l'utilisateur et exécutées** :
- `Testdodge` (0 trade depuis le lancement, quasi-doublon de `GAINfoou`) → **supprimé** (`DELETE /api/delete-bot`), historique conservé dans `data/Testdodge.db`.
- `GAINfoou` avait `max_position_size_pct: 1.0` (100% du capital sur une seule position, aucune marge) → **corrigé à 0.2**, redémarré via `update-bot`. Sa position ouverte (2361 DOGE @ 0,0847, lot #3) a été restaurée à l'identique après redémarrage grâce à la persistance EF-27 — vérifié en base (`data/GAINfoou.db`).
- `TestETH2proba` changeait 3 variables à la fois vs `TestETH` (timeframe, taille de position, filtre de probabilité) → **réécrit** pour ne différer de `TestETH` QUE par le filtre de probabilité (même timeframe 5m, même taille 10%) — comparaison A/B désormais valide.
- Rôle de chaque bot restant documenté dans [MANUEL_UTILISATEUR.md](MANUEL_UTILISATEUR.md) §4.1.

**Validation** : revue avec l'utilisateur, pas de critère technique — c'est une décision de portefeuille, pas un changement de code.

**Statut** : ✅ étape validée (2026-09-12) — 9 bots → 8 bots, chacun avec une raison d'être documentée

### Étape 4bis — Second passage de consolidation + reoptimisation (2026-09-12)

**Déclencheur** : une simulation rétrospective d'un mois (panier de capital commun, voir STC section 3.5 révisée) a montré que `TestETH2proba` n'exécutait **aucun** ordre (filtre de probabilité bloquant systématiquement l'achat) et que `TestETH`/`doge_scalp_v1` faisaient strictement doublon avec `ETHAV5mn`/`optimized_dogeusdt_sma_cross` (mêmes paramètres de stratégie). L'utilisateur a aussi observé qu'au pic, moins de 700 des 3000 du panier commun étaient jamais mobilisés simultanément — sous-utilisation du capital disponible.

**Changements** :
1. **Suppression** de `TestETH`, `TestETH2proba`, `doge_scalp_v1` (redondants, voir §4.1 du manuel) — 8 bots → 5 bots.
2. **Reoptimisation** des 5 bots restants via `optimize.py` (grille sma_cross + scalp_dip, validation out-of-sample 70/30 sur 3 ans) : nouveaux paramètres validés pour `btc_sma_cross_v1` (sma_cross 20/75, EMA50) et `btc_sma_cross_fast_v1` (sma_cross 15/100, EMA200, désormais le 2e meilleur candidat BTC plutôt qu'une variante arbitraire) ; `ETHAV5mn` et `optimized_dogeusdt_sma_cross` confirmés déjà optimaux, inchangés côté stratégie. `GAINfoou` (scalp_dip) a reçu un filtre de tendance EMA50 (seul filtre transférable depuis la validation, qui ne teste qu'en 1h — `GAINfoou` reste en 1m pour sa fréquence de trading, donc ses paramètres fins de scalp ne sont pas formellement revalidés à cette granularité, limite documentée).
3. **Augmentation de l'utilisation du panier commun**, à la demande explicite de l'utilisateur : `max_position_size_pct` relevé de 0.10-0.20 à 0.35 sur les 5 bots, `max_concurrent_positions` porté à 2 pour les 4 bots `sma_cross` (protégé par le garde-fou anti-accumulation EF-23, qui bloque déjà un nouvel achat si une position ouverte est en perte), et plafonds de mise (`capital_allocated`) relevés (700/700/1000/400/400, total 3200) pour que la flotte puisse collectivement mobiliser une part bien plus grande des 3000 du panier qu'auparavant (~260 de mise maximale théorique cumulée avant ce changement, ~2100 après).

**Statut** : ✅ appliqué et redéployé en paper trading (2026-09-12) — à valider sur quelques jours/semaines avant de considérer les nouveaux paramètres comme fiables, comme toute config issue de `optimize.py`.

### Étape 4ter — Flotte "top 10 crypto" (2026-09-12)

**Déclencheur** : le test rétrospectif sur 6 mois (étape 4bis) a montré `ETHAV5mn` et `GAINfoou` **négatifs sur l'ensemble de la période** (-159 et -242 cumulés sur 6 fenêtres), même après correction du sizing — leur edge réel est nul ou négatif à leur fréquence de trading. L'utilisateur a demandé leur suppression et une reconstruction systématique : un bot par cryptomonnaie du top 10 par capitalisation (hors stablecoins), chacun optimisé individuellement.

**Changements** :
1. **Suppression** de `ETHAV5mn`, `GAINfoou`, et `btc_sma_cross_fast_v1` (ce dernier pour ne garder qu'1 seul bot par paire, conformément à la demande "1 bot par crypto") — 5 bots → 3 bots restants (`btc_sma_cross_v1`, `optimized_dogeusdt_sma_cross`).
2. **Top 10 retenu** (par capitalisation, hors stablecoins USDT/USDC/etc. qui n'ont pas de mouvement de prix à trader) : BTC, ETH, XRP, BNB, SOL, DOGE, ADA, TRX, LINK, AVAX — tous vérifiés disponibles en paire USDT sur Binance.
3. **Optimisation individuelle** de chaque paire via `optimize.py` (grille sma_cross + scalp_dip, validation out-of-sample 70/30 sur 3 ans). Résultat : **6 des 10 paires ont un edge positif validé** (BTC +0,40%, ETH +0,46%, XRP +0,87%, DOGE +1,83%, ADA +1,53%, TRX +0,92%) — **4 n'en ont PAS** (BNB -0,73%, SOL -2,47%, LINK -2,09%, AVAX -4,94%, malgré un entraînement favorable dans les 4 cas : surapprentissage classique, cf. CT-09).
4. **Décision assumée** : les 4 bots sans edge démontré sont créés quand même (pour respecter la couverture demandée du top 10), mais avec un plafond de mise et une taille de position réduits de moitié (150/15% au lieu de 350/25%) par rapport aux 6 bots validés — l'allocation dynamique du panier commun (STC section 3.5 révisée) les ajustera encore à la baisse automatiquement s'ils continuent de sous-performer en paper trading réel.

**Validation** : suite de tests complète (308 tests) verte, les 10 bots démarrent sans erreur en paper trading. Pas encore de test rétrospectif multi-mois sur cette nouvelle flotte de 10 — à faire en suivi.

**Statut** : ✅ appliqué et redéployé en paper trading (2026-09-12) — 3 bots → 10 bots (1 par crypto du top 10), 4 d'entre eux explicitement marqués "sans edge démontré"

### Étape 4quater — Correction de l'utilisation du capital (2026-09-12)

**Déclencheur** : l'utilisateur a observé, sur le rapport de l'étape 4ter, que l'essentiel des 3000 du panier commun restait inutilisé en permanence ("de l'argent qui dort ce n'est pas bon") — capital moyen déployé mesuré a posteriori : seulement 244,82 (8,2% du panier) sur les 6 derniers mois, avec un pic à 654,85 (21,8%).

**Changement** : plafond de mise et sizing relevés, mais **uniquement sur les 6 bots à edge validé** (`btc_sma_cross_v1`, `eth_sma_cross_v1`, `xrp_sma_cross_v1`, `optimized_dogeusdt_sma_cross`, `ada_sma_cross_v1`, `trx_sma_cross_v1`) : `capital_allocated` 350→500, `max_position_size_pct` 25%→45%, `max_concurrent_positions` 2→3. Les 4 bots sans edge démontré (`bnb`, `sol`, `link`, `avax`) n'ont volontairement PAS été touchés, pour ne pas répéter l'erreur de l'étape 4bis (amplifier un sizing sur une strategie sans edge avait couté cher).

**Résultat mesuré** (rejeu des 6 derniers mois, même période, avant/après) :
- Capital moyen déployé : 244,82 → **541,80** (+121%)
- Pic de capital déployé : 654,85 → **1807,64**
- P&L sur la période : +90,59 (+3,02%) → **+237,90 (+7,93%)**

Sur l'échantillon de 6 mois aléatoires (2023-2026), l'effet net est resté proche de zéro (le sizing plus gros amplifie les gains ET les pertes selon la fenêtre) — la correction améliore nettement l'utilisation du capital et la période récente, sans détériorer la robustesse mesurée sur longue période.

**Statut** : ✅ appliqué et redéployé en paper trading (2026-09-12) — capital moyen déployé +121%, P&L 6 mois récents +90,59→+237,90

### Étape 5bis — Automatisation réelle du réoptimiseur + correction d'un bug de sizing (2026-09-12)

**Déclencheur** : l'utilisateur a demandé si les simulations rétrospectives tenaient compte du réoptimiseur hebdomadaire supposé tourner automatiquement. Vérification faite : **rien ne le déclenchait automatiquement** (CT-15 de la STB, connu depuis la conception de l'étape 5 mais jamais résolu) — aucune tâche planifiée sur la machine.

**Changements** :
1. Tâche planifiée Windows créée (`TradingBot-Reoptimizer-Weekly`, tous les vendredis 3h) qui exécute `run_reoptimizer_weekly.bat` → `python -m tradingbot.reoptimizer --all`, journalisé dans `logs/reoptimizer_weekly.log`.
2. Test réel de ce déclenchement (premier run sur la flotte de 10 bots reconstruite) : les groupes A/B se sont ré-équilibrés automatiquement pour les 10 bots actuels (`assign_groups` filtre les bots supprimés et assigne les nouveaux, comportement déjà prévu et fonctionnel).
3. **Bug réel découvert par ce premier run** : l'application automatique (groupe "auto") a écrasé le sizing de position choisi manuellement (`max_position_size_pct`/`max_concurrent_positions`, relevés à l'étape 4quater) sur 3 bots (`avax`, `bnb`, `link`) — `merge_proposal_into_config` remplaçait tout le bloc `risk` alors que `optimize.py` ne fait jamais varier ces deux champs. **Corrigé** : seuls `stop_loss_pct`/`take_profit_pct` sont désormais pris de la proposition (voir STB CT-19, STC §3.23, test `test_merge_proposal_preserves_custom_position_sizing`). Les 3 bots concernés ont été restaurés à leur sizing correct et redémarrés.

**Statut** : ✅ tâche planifiée active (prochaine exécution : vendredi prochain 3h), bug de sizing corrigé et testé, 309 tests verts

---

## Étape 5 — Bot d'auto-réoptimisation périodique

**Objectif** : automatiser la ré-exécution de `optimize.py` au fil du temps pour que la config d'un bot s'adapte aux conditions de marché changeantes, plutôt que de rester figée sur les paramètres trouvés une seule fois.

**Risque identifié (discuté avec l'utilisateur avant de démarrer)** : un ré-optimiseur naïf qui prend systématiquement le meilleur résultat backtest à chaque exécution risque de changer de config en permanence en poursuivant du bruit statistique, sans jamais laisser une config assez longtemps en paper trading pour la valider réellement ("config-shopping").

**Garde-fous à intégrer dès la conception** (pas des options facultatives) :
1. Le nouveau candidat ne remplace l'ancien que s'il bat la config actuelle sur la période de **validation out-of-sample** — jamais juste "le meilleur du jour".
2. Fréquence de ré-optimisation lente (au départ mensuelle, portée à hebdomadaire au maximum à la demande de l'utilisateur — voir extension ci-dessous) pour laisser accumuler de vraies données live entre deux changements.
3. Ne jamais reconfigurer une instance qui a une position ouverte (cohérent avec CT-10 de la STB — le cash reconstruit au redémarrage deviendrait incohérent sinon).
4. **Semi-automatique pour commencer** : le bot propose une nouvelle config + notification, l'humain valide avant tout déploiement réel — pas de bascule automatique en direct dès la première version.

**Réalisé** : nouveau module `reoptimizer.py`, réutilise intégralement `optimize.py` (même grille, même validation out-of-sample 70/30) pour une seule instance à la fois. Les 4 garde-fous de conception sont implémentés comme des fonctions pures testées séparément :
- `is_better_out_of_sample(current, candidate)` : un candidat ne devient une proposition QUE s'il bat la config actuelle sur sa performance de VALIDATION (jamais sur sa performance d'entraînement).
- `is_due_for_reoptimization(last_checked_at, now, interval_days=7)` : au plus une fois par semaine par instance (initialement 30 jours, réduit à la demande de l'utilisateur — voir extension ci-dessous), état persisté dans `proposals/reoptimize_state.json`.
- `has_open_position(name)` : relit `open_positions` en base (EF-27) — refuse de proposer si une position est ouverte (cohérent avec CT-10).
- **Semi-automatique** : le résultat est écrit dans `proposals/{nom}_proposal.json` (+ une config YAML prête), **rien n'est écrit dans `config/`, rien n'est redémarré**. Nouvelle route `GET /api/list-proposals` + `POST /api/apply-proposal` (ne copie que `strategy`/`risk`/`trend_filter` du fichier proposé — conserve le `capital_allocated`/`warmup_candles` déjà choisis par l'utilisateur — et revérifie l'absence de position ouverte au moment d'appliquer, pas seulement au moment de proposer) + `POST /api/dismiss-proposal`. Section "Propositions de réoptimisation" ajoutée dans l'onglet "Gérer les bots" du dashboard, avec boutons Appliquer/Rejeter.

**Validation** :
- ✅ Tests unitaires des 4 garde-fous + `candidate_from_config` + `propose_reoptimization` de bout en bout (position ouverte → skip, fréquence → skip, config actuelle sans edge → proposition écrite, état mis à jour même sans amélioration trouvée) — 15 tests dans `test_reoptimizer.py`, + 3 tests `list_proposals` côté `control_server`. Suite complète : 263 tests passent.
- ✅ Test manuel en conditions réelles : `python -m tradingbot.reoptimizer --name btc_sma_cross_v1` a produit une vraie proposition — config actuelle (sma_cross 10/30) à -1,92% en validation, candidat proposé (sma_cross 15/100 + trend_ema=200, la config gagnante de l'étape 1) à +0,14% en validation. Proposition visible et actionnable dans le dashboard (onglet "Gérer les bots"), vérifié via navigateur.
- ⏳ Retour utilisateur sur la proposition en attente pour `btc_sma_cross_v1` — **à valider ou rejeter depuis le dashboard**, rien n'a été appliqué automatiquement.

**Limite assumée pour cette v1** : pas de planification automatique interne (pas de tâche cron intégrée) — `python -m tradingbot.reoptimizer --name <bot>` (ou `--all`) doit être relancé périodiquement par l'utilisateur (manuellement, via le bouton dashboard décrit ci-dessous, ou via le planificateur de tâches Windows).

### Extension étape 5 : bouton "tout réoptimiser", sizing ATR, fréquence hebdomadaire, test A/B

Suite à la demande de l'utilisateur d'aller plus loin (2026-09-12) :

1. **Bouton "Lancer la réoptimisation de tous les bots"** dans l'onglet "Gérer les bots" — appelle la nouvelle route `POST /api/reoptimize-all`, qui lance `reoptimizer.run_all()` dans un thread en arrière-plan et répond immédiatement (traiter ~8 bots à ~960 combinaisons chacune peut prendre plusieurs minutes). Les résultats apparaissent au fil de l'eau dans la liste des propositions (rafraîchie toutes les 15s).
2. **Sizing ATR ajouté à la grille de recherche** de `optimize.py` (donc du réoptimiseur, qui la réutilise intégralement) : `ATR_SIZING_OPTIONS = [False, True]` — un simple on/off avec les paramètres par défaut, pas une grille fine de périodes ATR (le résultat de l'étape 2 était déjà mitigé, inutile d'explorer finement ses propres hyperparamètres). La grille passe de 480 à **960 combinaisons par paire**.
3. **Fréquence portée à 7 jours** (`REOPTIMIZE_INTERVAL_DAYS = 7`, était 30) — au moins une vérification par semaine par bot, comme demandé.
4. **Test A/B d'efficacité** : chaque bot connu est assigné de façon stable et équilibrée à un groupe "auto" ou "control" (`assign_groups`, persisté dans `proposals/ab_test_groups.json`, jamais réassigné une fois choisi) :
   - Groupe **"control"** : la proposition est générée mais **jamais appliquée** — sert de référence pour mesurer si la réoptimisation change réellement quelque chose.
   - Groupe **"auto"** : une proposition trouvée est **appliquée immédiatement**, sans validation humaine — c'est le sens du test. Les garde-fous out-of-sample et position-ouverte restent actifs ; seul le garde-fou "l'humain valide avant tout déploiement" est levé pour ce groupe, à la demande explicite de l'utilisateur et dans un but de mesure contrôlée (paper trading uniquement, aucun argent réel engagé — voir EF-04).

**Validation** :
- ✅ 25 nouveaux tests (grille `ATR_SIZING_OPTIONS`, wiring `AtrSizer`↔`Engine` dans `optimize.py` ; `assign_groups` stable/équilibré, `merge_proposal_into_config`, `apply_proposal_files`, `run_all` groupe auto vs control dans `reoptimizer.py`). Suite complète : 288 tests passent.
- ✅ Test manuel réel effectué sur les 8 bots via le bouton "Lancer la réoptimisation de tous les bots" :

| Bot | Groupe | Résultat |
|---|---|---|
| doge_scalp_v1 | auto | Aucune amélioration trouvée |
| ETHAV5mn | auto | Aucune amélioration trouvée |
| TestETH | auto | Aucune amélioration trouvée |
| btc_sma_cross_fast_v1 | auto | Ignoré (position ouverte au moment du check) |
| optimized_dogeusdt_sma_cross | control | Aucune amélioration trouvée |
| **TestETH2proba** | **control** | **Proposition trouvée** : `scalp_dip(look=20, seuil=0,3%)` à -19,08 % en validation → `sma_cross(8,100)+trend_ema=200` à **+0,52 %** en validation — en attente de décision manuelle |
| GAINfoou | control | Ignoré (position ouverte au moment du check) |
| btc_sma_cross_v1 | control | Ignoré (déjà vérifié récemment, hors délai des 7 jours) |

**Aucune config n'a été modifiée automatiquement lors de ce premier passage** : les bots du groupe "auto" n'avaient soit aucune amélioration à proposer, soit une position ouverte bloquant la vérification — le mécanisme d'auto-application n'a simplement pas eu l'occasion de se déclencher cette fois-ci. Résultat honnête et attendu (le garde-fou anti-position-ouverte a fonctionné exactement comme prévu) : il faudra plusieurs cycles hebdomadaires pour voir le groupe "auto" réellement diverger du groupe "control".

**Point mineur relevé pendant le diagnostic (CT-15bis)** : un bot "ignoré (position ouverte)" ne mettait pas à jour `last_checked_at` dans `proposals/reoptimize_state.json` — il était donc revérifié à chaque lancement de `run_all`/`--all` plutôt que d'attendre l'intervalle configuré. Sans conséquence pratique (le check est quasi instantané, aucun backtest n'est lancé), mais corrigé le 2026-09-20 : `propose_reoptimization` avance désormais `last_checked_at` (en conservant un `pending_candidate` existant) avant de retourner `status: skipped` pour position ouverte — voir `reoptimizer.py` et le test `test_propose_reoptimization_updates_last_checked_at_when_position_open`.

**Statut** : ✅ intégré et testé — extension appliquée en conditions réelles sur les 8 bots, une proposition réelle en attente de décision utilisateur (`TestETH2proba`)

---

## Étape 6 — Robustesse et fiabilité de l'edge (à définir) — 🔲 non démarrée

**Constat qui motive cette étape** (simulations rétrospectives du 2026-09-12) : l'edge mesuré de la flotte actuelle (`sma_cross` sur 10 paires) est **faible et très instable dans le temps**, pas juste sur telle ou telle config :
- Sur 6 mois pris au hasard entre 2023 et 2026 : P&L quasi nul (-0,14 % en moyenne).
- Sur les 6 derniers mois (période la plus proche de celle utilisée pour valider les paramètres actuels) : +7,93 %.
- Sur le premier semestre 2024 : +10,87 %. Sur le premier semestre 2025 : **-7,25 %**.
- La réoptimisation hebdomadaire (étape 5) peut activement **dégrader** la performance à court terme (Test 3, -46,11 sur 6 mois) : chaque changement améliorait le score de validation au moment de la décision, mais le marché avait déjà changé de régime la semaine suivante — signe de surapprentissage résiduel ("config-shopping"), pas un bug du garde-fou lui-même.

**Diagnostic de fond** : `sma_cross` est l'une des stratégies techniques les plus simples et les plus connues du marché — elle a structurellement peu de chances de garder un edge durable sur un marché aussi arbitré que crypto. Les bons résultats observés (2024, 6 derniers mois) ressemblent davantage à "la stratégie a bien surfé une tendance de marché favorable" qu'à un edge indépendant des conditions de marché.

**Objectif** : ne pas se contenter d'optimiser encore les paramètres de `sma_cross`, mais chercher une **méthode qui rende la flotte robuste et fiable** à travers des régimes de marché variés, pas seulement performante sur la période récente utilisée pour la caler.

**Pistes à investiguer** (les 2 premières sont maintenant réalisées, voir ci-dessous ; les 3 suivantes restent ouvertes) :
1. ✅ **Garde-fous anti-"config-shopping" sur le réoptimiseur** — marge d'amélioration minimale avant d'appliquer une proposition (pas juste "plus grand que").
2. ✅ **Étalonnage face à une référence neutre (buy & hold)** — une proposition doit désormais battre un simple achat-conservation sur la même période, pas seulement la config actuelle.
3. 🔲 **Confirmation sur 2-3 checks hebdomadaires consécutifs avant bascule**, montée en charge progressive du nouveau candidat plutôt qu'un remplacement à 100 % immédiat (réutiliser le mécanisme de multiplicateur déjà existant dans `shared_pool.py`) — non démarré.
4. 🔲 **Sélection par critère ajusté au risque plutôt que par rendement brut** : `optimize.py`/`reoptimizer.py` classent aujourd'hui uniquement sur `total_return_pct` — un critère type Sharpe/Sortino (rendement rapporté à la volatilité ou au drawdown) pénaliserait les configs qui gagnent gros sur un régime favorable mais s'effondrent ailleurs. Non démarré.
5. 🔲 **Validation sur PLUSIEURS fenêtres de test, pas une seule** : le découpage actuel 70/30 ne valide que sur une seule période de validation contiguë (les 30% les plus récents) — une validation glissante sur plusieurs sous-périodes non contiguës (cross-validation temporelle) détecterait mieux une config qui ne marche que dans un seul régime. Non démarré.
6. 🔲 **Diversification de familles de stratégies**, pas seulement de paires — `sma_cross` et `scalp_dip` sont tous deux des stratégies de suivi de tendance/momentum ; une stratégie de retour à la moyenne ou de range trading pourrait compenser sur les périodes où le suivi de tendance échoue (ex : 2025 H1). Non démarré.

**Réalisé (2026-09-12)** :
- `reporting/stats.py::compute_buy_and_hold_return_pct(candles)` — rendement d'un simple achat-conservation sur la période, sans stratégie. Intégré dans `optimize.py::BacktestResult` (champ `benchmark_return_pct`, propriété `beats_benchmark`), calculé automatiquement par `run_one_backtest` sur les mêmes bougies que chaque backtest.
- `reoptimizer.py::is_better_out_of_sample` exige désormais une marge minimale (`MIN_IMPROVEMENT_MARGIN = 0.005`, soit 0,5 point) au lieu d'un simple `>` — un écart de bruit ne déclenche plus de changement.
- `reoptimizer.py::has_edge_over_benchmark(result)` — nouvelle fonction, refuse une proposition qui ne bat pas le buy & hold sur la même période de validation. Combinée à la marge minimale dans `propose_reoptimization` : les deux conditions doivent être vraies pour qu'une proposition soit écrite.
- 12 nouveaux tests (5 pour le benchmark, 7 pour les garde-fous du réoptimiseur). Suite complète : 321 tests passent. Voir STC §3.24 pour le détail technique.

**Revalidation par simulation walk-forward (2026-09-12), 3 périodes indépendantes, avant/après garde-fous** :

| Période | Sans réopt. (statique) | Réopt. — anciens garde-fous | Réopt. — nouveaux garde-fous | Changements appliqués |
|---|---|---|---|---|
| 6 derniers mois | +237,90 | +191,79 | +189,23 | 9 → 5 |
| S1 2025 | -217,51 | -207,63 | -207,63 (identique) | 2 → 2 |
| S1 2024 | +326,02 | *(non testé)* | +326,19 (quasi identique) | 1 |

**Verdict honnête** : les garde-fous réduisent bien le nombre de changements appliqués (-44 % sur les 6 derniers mois, en filtrant les écarts de bruit) et n'empêchent jamais un changement dont l'amélioration est large et réelle (S1 2025 : les 2 changements passent les deux filtres sans être bloqués). **Mais ils ne suffisent pas à eux seuls à rendre la réoptimisation hebdomadaire nettement bénéfique** : sur les 6 derniers mois le résultat reste légèrement pire qu'à paramètres figés (+189,23 vs +237,90), et sur S1 2025/2024 l'effet est quasi nul par rapport au statique. La cause de fond identifiée à la conception (un vrai changement de régime de marché va plus vite que ce qu'une fenêtre de validation glissante peut anticiper) n'est pas résolue par un simple filtrage du bruit — elle demande les pistes 3 à 6 (sélection ajustée au risque, validation multi-fenêtres, confirmation sur plusieurs semaines, diversification de stratégies).

**Statut (mis à jour 2026-09-13)** : au vu du résultat mitigé, l'utilisateur a conclu que les réoptimisations automatiques "ne servent à rien" en l'état — **tous les bots ont été repassés en groupe "control"** dans `proposals/ab_test_groups.json` : le réoptimiseur continue de tourner chaque semaine et d'écrire des propositions (visibilité/données conservées pour continuer à apprendre), mais **plus rien n'est appliqué automatiquement**.

**Pistes 3 à 6, implémentées le même jour** :
- ✅ **Confirmation sur 2 checks consécutifs (piste 3)** : `reoptimizer.py` — un candidat doit regagner la semaine suivante avant d'être proposé/appliqué (`pending_confirmation`).
- ✅ **Sélection ajustée au risque (piste 4)** : `BacktestResult.risk_adjusted_return` (rendement/drawdown) remplace le rendement brut comme critère de tri dans `optimize.py` et `reoptimizer.py`.
- ✅ **Validation multi-fenêtres (piste 5)** : `compute_window_consistency` découpe la validation en 3 sous-périodes ; un candidat positif sur moins de la moitié d'entre elles est rejeté.
- ✅ **Diversification de stratégie (piste 6)** : nouvelle `MeanReversionStrategy` (bandes de Bollinger) intégrée à la grille de recherche. **Vérifiée empiriquement sur les 4 paires sans edge (BNB/SOL/LINK/AVAX) : n'a pas trouvé d'edge non plus** — ses candidats n'atteignent même pas le top 15 à l'entraînement sur ces paires. Implémentée et testée, mais n'a pas (encore) résolu le problème qu'elle visait à traiter.

**Effet secondaire découvert et corrigé** : tester la piste 6 en relançant `optimize.py` a révélé un bug réel — l'outil écrasait silencieusement la config d'un bot déjà déployé quand son nom auto-généré coïncidait (`optimized_dogeusdt_sma_cross`). Corrigé (`write_config_without_overwriting`, écrit à côté au lieu d'écraser).

**Bilan honnête de l'étape 6 à ce stade** : les 6 pistes identifiées ont toutes été implémentées et testées (36 nouveaux tests, 351 au total), mais **aucune n'a démontré d'amélioration nette et robuste** de la fiabilité de l'edge sur les échantillons testés. Ce n'est pas un échec de mise en œuvre — chaque garde-fou fait exactement ce qu'il est censé faire (réduire le bruit, éviter la sur-concentration sur un régime, etc.) — mais le problème de fond identifié dès le départ (`sma_cross` a un edge faible et instable, qui ressemble plus à "surfer une tendance de marché" qu'à un avantage structurel) n'est pas résolu par de meilleurs garde-fous autour d'une stratégie faible. La piste la plus prometteuse restante, non explorée ici : une recherche plus large de stratégies (pas seulement bandes de Bollinger) ou une remise en question du choix même de trader sur un signal technique simple plutôt que d'accepter un edge modeste et se concentrer sur la gestion du risque.

**Statut** : 🟡 en pause — toutes les pistes du backlog traitées, réoptimisation automatique désactivée (groupe "control" partout) en attendant une piste qui démontre un vrai bénéfice

---

## Étape 7 — Market making natif (edge structurel) — 🔴 testé, résultat négatif

**Origine** : suite à une comparaison avec Hummingbot (framework open-source dont le market making est la stratégie phare), décision d'implémenter nativement le CONCEPT (capture de spread bid/ask + gestion d'inventaire) plutôt que d'importer son code — incompatible avec l'architecture de ce projet (ordres limites, carnet d'ordres). Objectif : sortir du pari directionnel (suivi de tendance, retour à la moyenne) qui n'a démontré aucun edge robuste à l'étape 6, en visant un edge de nature différente.

**Implémenté** : `strategies/market_making.py::MarketMakingStrategy` (cotation bid/ask autour du prix, recentrage par l'inventaire), `mm_engine.py::MarketMakingEngine` (moteur dédié, simulation des fills par approximation du high/low de la bougie — limite assumée, ce projet n'a pas de carnet d'ordres historique), intégration complète à `optimize.py`/`run_backtest.py`/`run_paper.py`. Voir STC §3.26 et STB EF-44 pour le détail technique.

**Bug réel trouvé et corrigé pendant la validation (CT-22 de la STB)** : le premier run sur données réelles affichait des rendements absurdes (+15 000 % à +19 000 %) — un bug de comptabilité multi-lots (vente calculée sur l'inventaire total, imputée au coût du lot le plus ancien pour une quantité qu'il n'avait jamais détenue) créait un profit fictif. Corrigé le jour même, testé en régression.

**Vérification empirique (2026-09-13)**, même discipline que l'étape 6 (validation out-of-sample + benchmark buy & hold + consistance multi-fenêtres) sur les 4 paires sans edge connu (BNB/SOL/LINK/AVAX) : **résultat négatif**. Le meilleur candidat par symbole perd entre -22 % et -42 % sur la période de validation (drawdown 23-42 %, consistance négative sur les 3 sous-fenêtres pour les 4 symboles) — aucun candidat ne bat le buy & hold ET n'est consistant. Aucun bot créé.

**Bilan honnête** : implémentation correcte et testée (26 nouveaux tests, 372 au total), mais cette première version simple (spread fixe, skew linéaire, aucune adaptation à la volatilité) n'a pas trouvé d'edge sur ces 4 paires sur cette fenêtre de 3 ans. Piste non explorée ici : élargir le spread en période de forte volatilité (à l'instar de l'ATR sizing, étape 2) pour réduire le risque de sélection adverse en marché fortement trending — les pertes observées (drawdown élevé, consistance négative) sont cohérentes avec ce risque connu du market making naïf en marché directionnel, pas avec un manque de spread capturé.

**Piste "spread adaptatif à la volatilité" — implémentée le 2026-09-21** (tâche planifiée `lecture-du-plan-et-mise-en-place-dune-feature`) : `MarketMakingStrategy` gère désormais en interne un ATR (même mécanique que `analysis/atr_sizer.py`, calculé sur les bougies précédentes seulement — jamais le high/low de la bougie en cours de cotation, pour ne pas se baser sur une information pas encore connue) et élargit son demi-spread proportionnellement au ratio ATR courant/baseline (borné à `max_spread_multiplier`, ne rétrécit jamais sous le spread configuré). Désactivé par défaut (`volatility_adaptive_spread=False`) — comportement historique inchangé pour les configs existantes. Ajouté comme dimension on/off dans la grille `optimize.py` (`MARKET_MAKING_VOLATILITY_ADAPTIVE_SPREAD_OPTIONS`), 6 nouveaux tests unitaires (`tests/test_market_making_strategy.py`, 766 tests au total). **Non encore validé empiriquement** : nécessite un run complet de `optimize.py` (backtest 3 ans, hors scope de cette tâche) pour savoir si cette variante change le verdict négatif ci-dessus — prochaine étape suggérée pour un futur run.

**Statut** : 🔴 testé, résultat négatif sur la version simple — 🟡 variante "spread adaptatif" implémentée et testée unitairement le 2026-09-21, re-validation empirique (nouveau run `optimize.py`) restant à faire

---

## Étape 8 — Funding rate arbitrage (Phase A : backtest uniquement) — 🟡 non concluant

**Origine** : un document de référence sur les stratégies quant crypto (partagé par l'utilisateur) identifie le funding rate arbitrage comme edge structurellement différent — un service rendu au marché (financement de positions à effet de levier), delta-neutre par construction, plutôt qu'un pari directionnel ou une capture de spread. Rendement de référence cité : 5-15%/an réaliste en 2026.

**Décision de scope, assumée dès le départ** : ce projet ne trade que du spot. Une intégration live complète (connecteur perpétuel, marge/effet de levier, moteur à deux jambes spot+perp) est un chantier séparé de l'ampleur d'un nouveau sous-système — hors de portée d'une session. Cette étape se limite donc à la **Phase A : pipeline de données + backtest de validation**, avant tout investissement dans l'exécution live. Voir STC §3.27 et STB EF-45 pour le détail technique.

**Implémenté** : `data_feed.py::fetch_funding_rate_history` (historique de funding via `ccxt`, perpétuels linéaires Binance), `funding_arb.py` (simulation à deux jambes long spot / short perpétuel, entrée/sortie sur moyenne glissante du funding, **P&L de base explicitement mesuré et jamais supposé nul** — c'est précisément le risque que la doc de référence identifie comme le plus sous-estimé). Nuance de garde-fou documentée : le critère "battre un buy & hold" (étape 6) ne s'applique pas à une stratégie delta-neutre par construction — remplacé par rendement ajusté au risque positif + consistance multi-fenêtres.

**Vérification empirique (2026-09-14)** sur BTC/USDT, ETH/USDT, SOL/USDT (3 ans d'historique réel) : **résultat non concluant**.
- **BTC** : échoue les garde-fous — à l'entraînement, le risque de base domine largement le funding collecté (P&L de base -425,70 contre funding collecté +187,53 sur la même période), confirmation empirique directe du risque documenté.
- **ETH** : "passe" les garde-fous tels que définis, mais sur un signal statistiquement faible (2-3 cycles complets en validation seulement, une seule sous-fenêtre sur 3 mesurable).
- **SOL** : légèrement négatif en validation, échoue les garde-fous.

**Bilan honnête** : le funding rate arbitrage tel que modélisé ici (seuils fixes, sans ajustement à la volatilité, sans limite de durée de détention) ne démontre pas un edge robuste sur ces 3 paires sur cette fenêtre — le risque de base domine le résultat, pas le funding lui-même. Cohérent avec le constat de fond de toute la soirée : chaque stratégie testée (sma_cross, mean_reversion, market_making, funding_arb) a un edge faible, instable ou non démontré sur les données réelles disponibles.

**Statut** : 🟡 non concluant — pas de Phase B (exécution live) engagée, edge non confirmé

---

## Étape 9 — Rebond de creux sans stop-loss + bot passif "buy & hold" — 🟡 mitigé, en cours

**Origine** : suite au bilan de l'étape 8 (aucune stratégie testée ce soir n'a d'edge robuste démontré), l'utilisateur propose sa propre logique de trading : acheter près d'un creux récent tant que la tendance de fond reste haussière, tenir SANS stop-loss, sortir soit sur un nouveau plus haut récent, soit via un verrou de gain à deux seuils. En parallèle, ajout d'un bot "buy & hold" passif suite à la discussion sur le trading actif vs passif.

**Implémenté** : `DipBounceStrategy` (une seule fenêtre glissante sert de régime/creux/objectif, agnostique du timeframe), `BuyAndHoldStrategy` (achète une fois, ne revend jamais), `RiskManager.should_profit_lock` (nouveau mécanisme : arme à un premier seuil de gain, vend si le gain retombe à un second seuil plus bas), `RiskConfig.stop_loss_pct` rendu réellement optionnel. Voir STC §3.28 et STB EF-46/EF-47 pour le détail technique.

**Nouveauté de périmètre** : contrairement à `mean_reversion`/`market_making`/`funding_arb` (YAML uniquement), ces 2 stratégies (3 presets : rebond de creux horaire, rebond de creux minute, buy & hold) sont **directement créables depuis le formulaire du dashboard**, à la demande explicite de l'utilisateur.

**Vérification empirique (variante horaire uniquement, 2026-09-14)** sur les 10 symboles de la flotte, 3 ans d'historique réel : **résultat mitigé**.
- 5/10 symboles (ETH, XRP, BNB, LINK, DOGE) passent le filtre mécanique (bat le buy & hold + consistance ≥ 50%) — mais la période testée avait un buy & hold fortement négatif pour la plupart des symboles (ADA -67%, AVAX -63%, DOGE -55%), donc "battre le buy & hold" reflète en grande partie le fait de rester hors marché pendant un effondrement, pas un edge réel.
- Seul TRX (le seul symbole en hausse sur la période, +8,24%) offre un vrai test directionnel : la stratégie y **perd** contre le buy & hold (+0,21% vs +8,24%).
- Taux de réussite élevé (66-83%) mais gains individuels minuscules — cohérent avec un verrou de gain qui se déclenche tôt (+0,4% à +1%).
- **Le risque "pas de stop-loss" s'est concrètement matérialisé** : pire trade à -32,24 sur ADA (-3,2% du capital de test en un seul trade), et une position restée ouverte à la toute fin de la période de validation sur LINK.

**Variante minute non testée empiriquement** : le coût de téléchargement (historique 1m sur 3 ans, ~4h pour 10 symboles) a été annoncé à l'utilisateur, la décision de le lancer a été différée. L'intégration dashboard a été demandée et réalisée malgré ce résultat mitigé, pour permettre l'expérimentation directe.

**Statut** : 🟡 mitigé — implémentée, testée (26 nouveaux tests, 411 au total), disponible dans le dashboard ; résultat empirique horaire pas clairement positif (artefact partiel du régime de marché testé) ; variante minute en attente

---

## Historique

| Date | Changement |
|---|---|
| 2026-09-12 | Création de la feuille de route (4 étapes définies suite à la demande d'amélioration de la performance) |
| 2026-09-12 | Étape 1 validée (filtre de tendance + intégration à l'optimiseur, premier edge positif mesuré). Décision utilisateur : passer directement à l'étape 4 (étapes 2/3 reportées). Ajout de l'étape 5 (bot d'auto-réoptimisation périodique, idée proposée par l'utilisateur) |
| 2026-09-12 | Étape 4 validée : `Testdodge` supprimé, `GAINfoou` corrigé (sizing 100%→20%), `TestETH2proba` réécrit en comparateur A/B propre avec `TestETH`. 9 bots → 8 bots |
| 2026-09-12 | Étape 2 (sizing ATR) intégrée et testée — résultat mitigé (aide le pire cas connu, coûte légèrement sur les configs déjà rentables de l'étape 1). Reprise de l'ordre normal : étape 3 (sortie partielle) suit |
| 2026-09-12 | Étape 3 (sortie partielle) intégrée et testée — compromis risque/rendement réel : -30/35% de drawdown mais rendement divisé par 2 environ sur les stratégies trend-following déjà rentables. Reste désactivée par défaut |
| 2026-09-12 | Étape 5 (bot d'auto-réoptimisation) intégrée et testée — module `reoptimizer.py` semi-automatique avec 4 garde-fous (validation out-of-sample, fréquence lente, position ouverte, humain valide avant tout déploiement). Première proposition réelle générée pour `btc_sma_cross_v1`, en attente de décision utilisateur. Feuille de route complète (étapes 1 à 5) |
| 2026-09-12 | Extension étape 5 (demande utilisateur) : bouton "tout réoptimiser", sizing ATR ajouté à la grille (480→960 combinaisons/paire), fréquence 30→7 jours, test A/B groupe auto (applique automatiquement) vs control (jamais appliqué) pour mesurer l'efficacité réelle |
| 2026-09-12 | Étape 4bis : suite à une simulation rétrospective révélant des bots redondants/inactifs et une sous-utilisation du panier commun, suppression de `TestETH`/`TestETH2proba`/`doge_scalp_v1` (8→5 bots), reoptimisation des 5 restants via `optimize.py`, et augmentation du sizing/plafonds (`max_position_size_pct` 0.10-0.20→0.35, `max_concurrent_positions` 1→2 sur les bots sma_cross) pour mieux mobiliser les 3000 du panier commun |
| 2026-09-12 | Étape 4ter : `ETHAV5mn`/`GAINfoou` supprimés (négatifs sur 6 mois testés, même après correction du sizing) ; flotte reconstruite en 1 bot par crypto du top 10 par capitalisation hors stablecoins (10 bots) via `optimize.py` par paire — 6/10 avec edge validé out-of-sample, 4/10 (BNB/SOL/LINK/AVAX) sans edge démontré, créés avec un plafond réduit pour respecter la couverture demandée |
| 2026-09-12 | Étape 4quater : capital moyen déployé mesuré à seulement 8,2% du panier commun — plafond/sizing relevés sur les 6 bots à edge validé uniquement (capital_allocated 350→500, taille 25%→45%, positions simultanées 2→3), les 4 bots sans edge non touchés. Résultat sur les 6 derniers mois : capital déployé +121%, P&L +90,59→+237,90 |
| 2026-09-12 | Étape 5bis : tâche planifiée Windows créée pour le réoptimiseur hebdomadaire (jusque-là jamais déclenché automatiquement, CT-15). Bug réel corrigé le même jour : une application automatique écrasait le sizing de position choisi manuellement (CT-19) |
| 2026-09-12 | Simulations walk-forward avec réoptimisation hebdomadaire intégrée : P&L dégradé de -46,11 sur les 6 derniers mois (chaque changement améliorait le score de validation au moment de la décision mais pas la performance forward réelle - "config-shopping"). Constat plus large sur la robustesse de l'edge (quasi nul sur mois aléatoires, +10,87% sur S1 2024, -7,25% sur S1 2025) → ajout de l'étape 6 (robustesse/fiabilité) au backlog, non démarrée |
| 2026-09-12 | Étape 6 démarrée : implémentation de 2 des 5 pistes retenues comme prioritaires — marge d'amélioration minimale (`MIN_IMPROVEMENT_MARGIN`, EF-38) et exigence de battre un buy & hold (`has_edge_over_benchmark`, `compute_buy_and_hold_return_pct`, EF-39) dans le réoptimiseur, pour réduire le "config-shopping" démontré empiriquement. 12 nouveaux tests, 321 au total |
| 2026-09-12 | Revalidation des garde-fous par simulation walk-forward sur 3 périodes (6 derniers mois, S1 2025, S1 2024) : réduisent bien le nombre de changements appliqués (9→5 sur 6 mois) sans bloquer les vrais changements de régime (S1 2025 inchangé), mais ne rendent pas la réoptimisation hebdomadaire nettement bénéfique sur la durée — le problème de fond (régime de marché plus rapide que la fenêtre de validation) reste ouvert, pistes 3 à 6 à traiter |
| 2026-09-13 | Décision utilisateur : les réoptimisations automatiques ne sont pas validées, tous les bots repassés en groupe "control" (propositions toujours générées chaque semaine, plus rien n'est appliqué). Pistes 3 à 6 implémentées et testées le même jour (confirmation sur 2 checks, sélection ajustée au risque, consistance multi-fenêtres, nouvelle stratégie `MeanReversionStrategy`) — vérification empirique sur les 4 paires sans edge : `mean_reversion` n'en trouve pas non plus. Bug réel découvert et corrigé au passage (écrasement silencieux de config par `optimize.py`, CT-21). 36 nouveaux tests, 351 au total. Étape 6 mise en pause : toutes les pistes traitées, aucune n'a résolu le problème de fond |
| 2026-09-13 | Étape 7 ajoutée et testée le même jour, suite à une comparaison avec Hummingbot : nouvelle stratégie à edge structurel `MarketMakingStrategy` + moteur dédié `MarketMakingEngine` (cotation bid/ask, simulation par approximation OHLC). Bug réel de comptabilité multi-lots découvert et corrigé pendant la validation (profit fictif, CT-22). Vérification empirique sur les 4 paires sans edge : résultat négatif (-22% à -42% sur validation, aucun candidat ne passe les garde-fous). 26 nouveaux tests, 372 au total. Étape 7 : testée, résultat négatif, aucun bot créé |
| 2026-09-14 | Étape 8 ajoutée suite à la lecture d'un document de référence sur les stratégies quant crypto : pipeline de données funding rate (`fetch_funding_rate_history`) + module `funding_arb.py` (simulation à deux jambes spot+perpétuel, P&L de base explicitement mesuré). Phase A (backtest) uniquement — aucune exécution live, décision de scope assumée dès le départ. Vérification empirique sur BTC/ETH/SOL : résultat non concluant (le risque de base domine le funding collecté sur BTC, ETH ne passe que sur un signal statistiquement faible sur 2-3 cycles). 13 nouveaux tests, 386 au total. Aucune Phase B engagée |
| 2026-09-14 | Étape 9 ajoutée à la demande de l'utilisateur, sa propre logique de trading : `DipBounceStrategy` (rebond de creux en tendance haussière, verrou de gain à deux seuils, aucun stop-loss) et `BuyAndHoldStrategy` (bot passif). Nouveauté de périmètre : ces stratégies (3 presets) sont créables directement depuis le formulaire du dashboard, pas seulement en YAML. Bug de réchauffement prévenu avant qu'il n'existe pour `buy_and_hold` (achat unique qui aurait été déclenché pour de faux pendant le warmup). Vérification empirique (variante horaire) sur les 10 symboles : résultat mitigé — 5/10 passent le filtre mais artefact partiel d'un marché baissier sur la période testée, risque "pas de stop-loss" concrètement observé (pire trade -3,2% du capital de test). Variante minute non testée (coût de téléchargement annoncé, décision différée). 26 nouveaux tests, 411 au total |
