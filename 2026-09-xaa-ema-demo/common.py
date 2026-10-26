"""Shared helpers: configuration, key handling and JWT pretty-printing."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise SystemExit(f"Missing required setting {name} (see .env.example)")
    return value.rstrip("/") if name.endswith(("_ISSUER", "_URL")) else value


# Grant and token type URNs (RFC 8693, RFC 7523, draft-ietf-oauth-identity-assertion-authz-grant)
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
TOKEN_TYPE_ID_JAG = "urn:ietf:params:oauth:token-type:id-jag"
TOKEN_TYPE_ID_TOKEN = "urn:ietf:params:oauth:token-type:id_token"
TOKEN_TYPE_REFRESH = "urn:ietf:params:oauth:token-type:refresh_token"
ID_JAG_TYP = "oauth-id-jag+jwt"


def load_or_create_rsa_key(path: Path) -> rsa.RSAPrivateKey:
    """Load a PEM private key, generating one on first run."""
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return key


def decode_unverified(token: str) -> tuple[dict, dict]:
    """Split a JWT into (header, payload) WITHOUT verifying it. For display only."""

    def b64(part: str) -> dict:
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))

    header, payload, _ = token.split(".")
    return b64(header), b64(payload)


def show_jwt(label: str, token: str) -> None:
    header, payload = decode_unverified(token)
    print(f"\n── {label} " + "─" * max(0, 60 - len(label)))
    print("header: ", json.dumps(header, indent=2))
    print("payload:", json.dumps(payload, indent=2))
