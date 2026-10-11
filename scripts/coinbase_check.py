"""Verifie ce que le compte Coinbase permet pour le bot (EF-113), en LECTURE SEULE.

Contexte (2026-10-11) : l'utilisateur choisit Coinbase pour trader le Volume
Profile en reel, achats ET ventes a decouvert. Coinbase a deux offres de
derives, et on ne sait pas laquelle un compte francais peut trader par API :
- les contrats europeens ("perpetual-style", echeance 5 ans) de Coinbase
  Financial Services Europe, via l'API Advanced Trade (api.coinbase.com) ;
- la passerelle mondiale Deribit (drb.coinbase.com/api/v2, JSON-RPC 2.0), qui
  liste ETH_USDC-PERPETUAL (regle en USDC, taille 0,0001 ETH, frais 0,015 %
  maker / 0,035 % taker) pour les "clients non americains eligibles".

Ce script ne passe AUCUN ordre. Sans cle : le cours, le spread et le
financement du contrat ETH_USDC-PERPETUAL (donnees publiques). Avec la cle
(a creer soi-meme sur le portail developpeur Coinbase, droits "Voir" et
"Trader", JAMAIS "Transferer") dans .env :
    COINBASE_API_KEY_NAME=organizations/.../apiKeys/...
    COINBASE_API_PRIVATE_KEY="-----BEGIN EC PRIVATE KEY-----\\n...\\n-----END EC PRIVATE KEY-----\\n"
il affiche aussi les droits de la cle, les contrats a terme que l'API Advanced
Trade montre a ce compte, et si la passerelle Deribit accepte la cle.

Usage : python scripts/coinbase_check.py
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

GATEWAY = "https://drb.coinbase.com/api/v2"
GATEWAY_HOST = "drb.coinbase.com"
INSTRUMENT = "ETH_USDC-PERPETUAL"


# ------------------------------------------------------------------ passerelle Deribit
def gateway_get(method: str, token: str | None = None, **params) -> dict:
    headers = {"User-Agent": "tradingbot-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{GATEWAY}/{method}?{urllib.parse.urlencode(params)}", headers=headers)
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode() or "{}") or {"error": {"code": e.code}}


def gateway_auth(jwt: str) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "public/auth",
                       "params": {"grant_type": "coinbase_cdp", "token": jwt}}).encode()
    req = urllib.request.Request(f"{GATEWAY}/public/auth", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": "tradingbot-check"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode() or "{}") or {"error": {"code": e.code}}


# ------------------------------------------------------------------ jeton CDP (cle Coinbase)
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def cdp_jwt(key_name: str, private_key: str, uri: str | None = None) -> str:
    """Jeton signe par la cle CDP : ES256 (cle EC au format PEM) ou EdDSA (cle Ed25519 en base64)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    private_key = private_key.replace("\\n", "\n").strip()
    if "BEGIN" in private_key:
        key = serialization.load_pem_private_key(private_key.encode(), password=None)
        alg = "ES256"
    else:
        key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key)[:32])
        alg = "EdDSA"
    now = int(time.time())
    header = {"alg": alg, "kid": key_name, "nonce": secrets.token_hex(16), "typ": "JWT"}
    payload = {"iss": "cdp", "sub": key_name, "nbf": now, "exp": now + 120}
    if uri:
        payload["uri"] = uri
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}".encode()
    if alg == "ES256":
        r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    else:
        signature = key.sign(signing_input)
    return f"{signing_input.decode()}.{_b64url(signature)}"


# ------------------------------------------------------------------ verifications
def public_market() -> None:
    print(f"== Contrat {INSTRUMENT} (passerelle Coinbase / Deribit, donnees publiques) ==")
    inst = gateway_get("public/get_instrument", instrument_name=INSTRUMENT).get("result") or {}
    tick = gateway_get("public/ticker", instrument_name=INSTRUMENT).get("result") or {}
    if not inst or not tick:
        print("  indisponible (contrat retire ou passerelle injoignable)")
        return
    bid, ask = tick.get("best_bid_price"), tick.get("best_ask_price")
    mid = (bid + ask) / 2 if bid and ask else None
    print(f"  achat {ask} / vente {bid} -> spread {((ask - bid) / mid * 100) if mid else float('nan'):.4f} % "
          f"| prix de marque {tick.get('mark_price')}")
    print(f"  frais : maker {inst.get('maker_commission', 0) * 100:.3f} %, taker {inst.get('taker_commission', 0) * 100:.3f} % "
          f"| taille mini {inst.get('min_trade_amount')} ETH | levier max affiche {inst.get('max_leverage')}")
    print(f"  financement : {tick.get('funding_8h')} sur 8 h (positif = les acheteurs paient), "
          f"instantane {tick.get('current_funding')}")


def with_key(key_name: str, private_key: str) -> None:
    import ccxt

    print("\n== API Advanced Trade (api.coinbase.com) ==")
    ex = ccxt.coinbase({"apiKey": key_name, "secret": private_key.replace("\\n", "\n")})
    try:
        perms = ex.v3PrivateGetBrokerageKeyPermissions()
        print(f"  droits de la cle : voir {perms.get('can_view')}, trader {perms.get('can_trade')}, "
              f"transferer {perms.get('can_transfer')}")
        if perms.get("can_transfer"):
            print("  ATTENTION : cette cle peut TRANSFERER des fonds. Recree-la sans ce droit avant tout usage par le bot.")
    except Exception as e:  # noqa: BLE001 - diagnostic : on affiche et on continue
        print(f"  droits de la cle illisibles : {type(e).__name__}: {str(e)[:200]}")
    try:
        markets = ex.load_markets()
        derivs = [m for m in markets.values() if m.get("base") == "ETH" and (m.get("swap") or m.get("future"))]
        print(f"  contrats a terme ETH visibles par ce compte : {len(derivs)}")
        for m in derivs[:10]:
            print(f"    {m['symbol']:<28} type {m.get('type')} | taille {m.get('contractSize')} | echeance {m.get('expiryDatetime')}")
    except Exception as e:  # noqa: BLE001
        print(f"  liste des contrats illisible : {type(e).__name__}: {str(e)[:200]}")

    print("\n== Passerelle mondiale (drb.coinbase.com, Deribit) ==")
    token = None
    for uri in (None, f"POST {GATEWAY_HOST}/api/v2/public/auth"):
        reply = gateway_auth(cdp_jwt(key_name, private_key, uri))
        token = (reply.get("result") or {}).get("access_token")
        if token:
            break
        err = reply.get("error") or {}
        print(f"  authentification refusee ({'avec' if uri else 'sans'} uri) : {err.get('code')} {err.get('message', '')[:150]}")
    if not token:
        print("  -> ce compte n'a pas acces a la passerelle mondiale (ou la cle n'a pas les droits).")
        return
    print("  authentification acceptee : le compte peut utiliser la passerelle mondiale.")
    summary = gateway_get("private/get_account_summary", token=token, currency="USDC").get("result") or {}
    print(f"  compte USDC : equity {summary.get('equity')}, disponible {summary.get('available_funds')}")
    positions = gateway_get("private/get_positions", token=token, currency="USDC", kind="future").get("result") or []
    print(f"  positions ouvertes sur des futures USDC : {len([p for p in positions if p.get('size')])}")


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    public_market()
    key_name, private_key = os.environ.get("COINBASE_API_KEY_NAME"), os.environ.get("COINBASE_API_PRIVATE_KEY")
    if not key_name or not private_key:
        print("\nCle Coinbase absente de .env : seules les donnees publiques sont affichees.")
        return
    with_key(key_name, private_key)
    print("\nAucun ordre n'a ete passe.")


if __name__ == "__main__":
    main()
