"""Jeton signe par la cle Coinbase (EF-113) : verifiable avec la cle publique, sans reseau."""
import base64
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("coinbase_check", ROOT / "scripts" / "coinbase_check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def b64d(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_es256_token_is_signed_by_the_ec_key():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption()).decode().replace("\n", "\n")   # comme dans .env
    token = check.cdp_jwt("organizations/o/apiKeys/k", pem, uri="POST drb.coinbase.com/api/v2/public/auth")
    head, body, sig = token.split(".")
    header, payload = json.loads(b64d(head)), json.loads(b64d(body))
    assert header["alg"] == "ES256" and header["kid"] == "organizations/o/apiKeys/k"
    assert payload["iss"] == "cdp" and payload["exp"] - payload["nbf"] == 120 and payload["uri"].startswith("POST ")
    raw = b64d(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    key.public_key().verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))   # leve si faux


def test_eddsa_token_with_an_ed25519_key():
    key = ed25519.Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    token = check.cdp_jwt("k", base64.b64encode(raw + pub).decode())
    head, body, sig = token.split(".")
    assert json.loads(b64d(head))["alg"] == "EdDSA" and "uri" not in json.loads(b64d(body))
    key.public_key().verify(b64d(sig), f"{head}.{body}".encode())
