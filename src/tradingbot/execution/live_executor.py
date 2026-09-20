"""LiveExecutor (EF-69) - ARGENT REEL sur Binance.

Premier chemin d'execution du projet qui engage de l'argent reel. Tout le
reste (backtest, testnet Binance, paper IBKR) est fictif. Ce module est donc
concu autour d'un principe unique : **plusieurs garde-fous INDEPENDANTS,
chacun capable de refuser seul**, verifies A LA CONSTRUCTION puis a chaque
ordre. Un seul verrou qu'on oublie de cocher ne suffit jamais a engager de
l'argent.

Classe SEPAREE de `PaperExecutor` volontairement : celui-ci force
`set_sandbox_mode(True)` en dur et fait tourner le bot de validation. Le
modifier pour y ajouter une bascule "reel" ferait passer la protection d'un
fait structurel (impossible d'atteindre le vrai marche) a une condition
qu'un bug pourrait inverser.

Les garde-fous, dans l'ordre ou ils s'appliquent :

1. **Drapeau d'activation explicite** (`BINANCE_LIVE_TRADING_ENABLED`) qui
   doit valoir exactement `oui-je-veux-trader-avec-de-l-argent-reel`. Pas
   `1`, pas `true` : une valeur qu'on ne peut pas poser par accident, ni
   heriter d'un `.env` copie d'un autre projet.
2. **Cles API sans droit de retrait.** Verifie aupres de Binance
   (`sapi/v1/account/apiRestrictions`) que la cle ne peut pas retirer de
   fonds. Une cle avec retrait autorise qui fuite, c'est le compte vide -
   et c'est la seule protection que l'utilisateur ne peut pas ajouter apres
   coup.
3. **Plafond par ordre** (`max_order_notional`), obligatoire et strictement
   positif. Aucune valeur par defaut : oublier de le regler doit empecher le
   demarrage, pas ouvrir la vanne.
4. **Interrupteur d'arret** : la simple presence du fichier
   `STOP_LIVE_TRADING` a la racine bloque tout ordre. Un fichier plutot
   qu'un reglage, pour pouvoir arreter le bot sans dashboard, sans API et
   sans redemarrage.
5. **Coupe-circuit de perte journaliere** (`max_daily_loss`) : au-dela de
   cette perte REALISEE sur la journee, plus aucun ordre d'achat ne passe.
   Distinct de `RiskManager.max_daily_loss_pct` (qui raisonne en pourcentage
   du capital simule) : ici c'est un montant absolu, verifie cote executeur,
   donc insensible a une erreur de configuration de la strategie.

Les ventes ne sont JAMAIS bloquees par le coupe-circuit ni par le plafond :
empecher de sortir d'une position serait un garde-fou qui aggrave le risque.
Seul l'interrupteur d'arret les bloque, et c'est un choix explicite de
l'utilisateur.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import ccxt

from tradingbot.execution.base import ExecutionAdapter
from tradingbot.portfolio import Portfolio
from tradingbot.types import OrderResult, Position, Side

LIVE_FLAG_ENV = "BINANCE_LIVE_TRADING_ENABLED"
LIVE_FLAG_EXPECTED = "oui-je-veux-trader-avec-de-l-argent-reel"
STOP_FILE = Path("STOP_LIVE_TRADING")


class LiveTradingRefused(RuntimeError):
    """Levee quand un garde-fou refuse d'engager de l'argent reel."""


class LiveExecutor(ExecutionAdapter):
    def __init__(
        self,
        exchange_id: str,
        symbol: str,
        max_order_notional: float,
        max_daily_loss: float,
        api_key: str = "",
        api_secret: str = "",
        exchange=None,
        env: dict | None = None,
        stop_file: Path | None = None,
    ):
        """`exchange`/`env`/`stop_file` sont injectables pour les tests :
        aucun test ne doit pouvoir toucher le vrai marche."""
        environment = os.environ if env is None else env
        self.stop_file = STOP_FILE if stop_file is None else stop_file

        flag = (environment.get(LIVE_FLAG_ENV) or "").strip()
        if flag != LIVE_FLAG_EXPECTED:
            raise LiveTradingRefused(
                f"Trading reel non autorise : {LIVE_FLAG_ENV} doit valoir exactement "
                f"'{LIVE_FLAG_EXPECTED}' dans .env (valeur actuelle : "
                f"{flag or 'absente'}). Ce n'est pas un oubli a contourner - "
                "relis les chiffres du backtest avant d'engager de l'argent."
            )

        if max_order_notional is None or max_order_notional <= 0:
            raise LiveTradingRefused(
                "max_order_notional doit etre strictement positif : c'est le plafond en "
                "monnaie de cotation de CHAQUE ordre. Aucune valeur par defaut n'est "
                "fournie volontairement - l'oublier doit empecher le demarrage."
            )
        if max_daily_loss is None or max_daily_loss <= 0:
            raise LiveTradingRefused(
                "max_daily_loss doit etre strictement positif : au-dela de cette perte "
                "realisee sur la journee, les achats s'arretent."
            )

        self._require_stop_file_absent()

        self.symbol = symbol
        self.base, self.quote = symbol.split("/")
        self.max_order_notional = float(max_order_notional)
        self.max_daily_loss = float(max_daily_loss)
        self._day = self._today()
        self._realised_loss_today = 0.0

        if exchange is not None:
            self.exchange = exchange
        else:
            if not api_key or not api_secret:
                raise LiveTradingRefused(
                    "Cles API reelles manquantes (BINANCE_API_KEY / BINANCE_API_SECRET "
                    "dans .env). Cree-les SANS droit de retrait et restreintes a ton IP."
                )
            exchange_class = getattr(ccxt, exchange_id)
            self.exchange = exchange_class(
                {"apiKey": api_key, "secret": api_secret, "enableRateLimit": True}
            )
            # Pas de set_sandbox_mode : on parle bien au marche reel.

        self._refuse_if_key_can_withdraw()
        self.exchange.load_markets()
        self.portfolio = self._load_portfolio_from_exchange()

    # --- garde-fous ---

    @staticmethod
    def _today() -> str:
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    def _require_stop_file_absent(self) -> None:
        if self.stop_file.exists():
            raise LiveTradingRefused(
                f"Fichier d'arret '{self.stop_file}' present : tout trading reel est "
                "bloque. Supprime-le pour reautoriser."
            )

    def _refuse_if_key_can_withdraw(self) -> None:
        """Une cle API autorisee a retirer des fonds est le pire risque de ce
        mode, et le seul que l'utilisateur ne peut pas corriger apres une
        fuite. On refuse donc de demarrer sans avoir verifie, y compris quand
        la verification elle-meme echoue (on ne suppose jamais que tout va
        bien faute d'information)."""
        fetch = getattr(self.exchange, "sapiGetAccountApiRestrictions", None)
        if fetch is None:
            raise LiveTradingRefused(
                "Impossible de verifier les permissions de la cle API sur cet exchange "
                "(endpoint apiRestrictions indisponible) : demarrage refuse plutot que "
                "de supposer que le retrait est desactive."
            )
        try:
            restrictions = fetch()
        except Exception as e:
            raise LiveTradingRefused(
                f"Verification des permissions de la cle API impossible : {e}. "
                "Demarrage refuse - sans cette garantie, une fuite de cle permettrait "
                "de vider le compte."
            ) from e

        if restrictions.get("enableWithdrawals"):
            raise LiveTradingRefused(
                "Cette cle API autorise les RETRAITS. Refus de demarrer : recree une cle "
                "avec uniquement le trading spot active, et restreins-la a ton IP."
            )
        if not restrictions.get("enableSpotAndMarginTrading"):
            raise LiveTradingRefused(
                "Cette cle API n'autorise pas le trading spot : aucun ordre ne pourrait "
                "aboutir."
            )

    def _reset_day_if_needed(self) -> None:
        today = self._today()
        if today != self._day:
            self._day = today
            self._realised_loss_today = 0.0

    @property
    def realised_loss_today(self) -> float:
        self._reset_day_if_needed()
        return self._realised_loss_today

    def _refuse_buy_reasons(self, quantity: float, price: float) -> str | None:
        notional = quantity * price
        if notional > self.max_order_notional:
            return (
                f"ordre de {notional:.2f} {self.quote} au-dessus du plafond de "
                f"{self.max_order_notional:.2f}"
            )
        if self.realised_loss_today >= self.max_daily_loss:
            return (
                f"perte realisee du jour ({self._realised_loss_today:.2f} {self.quote}) "
                f"au niveau du coupe-circuit ({self.max_daily_loss:.2f})"
            )
        return None

    # --- execution ---

    def _load_portfolio_from_exchange(self) -> Portfolio:
        balance = self.exchange.fetch_balance()
        quote_balance = float(balance.get(self.quote, {}).get("free", 0.0) or 0.0)
        base_balance = float(balance.get(self.base, {}).get("free", 0.0) or 0.0)

        portfolio = Portfolio(starting_capital=quote_balance)
        if base_balance > 0:
            ticker = self.exchange.fetch_ticker(self.symbol)
            portfolio.positions.append(
                Position(
                    quantity=base_balance,
                    avg_entry_price=float(ticker["last"]),
                    lot_id=portfolio._next_lot_id,
                )
            )
            portfolio._next_lot_id += 1
        return portfolio

    def _fits_exchange_limits(self, quantity: float, price: float) -> bool:
        market = self.exchange.market(self.symbol)
        limits = market.get("limits", {})
        min_qty = (limits.get("amount") or {}).get("min")
        min_cost = (limits.get("cost") or {}).get("min")
        if min_qty is not None and quantity < min_qty:
            return False
        if min_cost is not None and quantity * price < min_cost:
            return False
        return True

    def place_order(
        self, side: Side, quantity: float, price: float, timestamp: int,
        reason: str = "", lot_id: int | None = None,
    ) -> OrderResult:
        def rejected(qty: float, why: str) -> OrderResult:
            return OrderResult(
                side=side, quantity=qty, price=price, timestamp=timestamp,
                status="rejected", reason=f"{reason} [refuse: {why}]" if reason else f"refuse: {why}",
            )

        if quantity <= 0:
            return rejected(quantity, "quantite nulle")

        # L'interrupteur d'arret bloque TOUT, achat comme vente : c'est le
        # seul garde-fou dont l'utilisateur assume explicitement qu'il
        # empeche aussi de sortir.
        if self.stop_file.exists():
            return rejected(quantity, f"fichier d'arret '{self.stop_file}' present")

        rounded_quantity = float(self.exchange.amount_to_precision(self.symbol, quantity))
        if rounded_quantity <= 0 or not self._fits_exchange_limits(rounded_quantity, price):
            return rejected(rounded_quantity, "hors limites de l'exchange")

        # Plafond et coupe-circuit ne s'appliquent qu'aux ACHATS : empecher
        # une vente reviendrait a enfermer l'utilisateur dans une position.
        if side is Side.BUY:
            refusal = self._refuse_buy_reasons(rounded_quantity, price)
            if refusal is not None:
                return rejected(rounded_quantity, refusal)

        raw_order = self.exchange.create_order(self.symbol, "market", side.value, rounded_quantity)
        filled_qty = float(raw_order.get("filled") or rounded_quantity)
        avg_price = float(raw_order.get("average") or raw_order.get("price") or price)
        status = "filled" if raw_order.get("status") in (None, "closed") else raw_order["status"]

        result = OrderResult(
            side=side, quantity=filled_qty, price=avg_price, timestamp=timestamp,
            status=status, reason=reason,
        )
        if status == "filled":
            realised_before = self.portfolio.realized_pnl
            self.portfolio.apply_fill(result, lot_id=lot_id)
            realised_delta = self.portfolio.realized_pnl - realised_before
            if realised_delta < 0:
                self._reset_day_if_needed()
                self._realised_loss_today += -realised_delta
        return result

    def get_position(self) -> Position:
        return self.portfolio.position

    def get_positions(self) -> list[Position]:
        return list(self.portfolio.positions)

    def get_balance(self) -> float:
        return self.portfolio.cash
