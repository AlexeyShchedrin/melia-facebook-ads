"""Crypto helpers: Fernet token storage + HMAC signing for the CRM ingest call."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from meta_ads.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().fb_token_encryption_key.get_secret_value()
    if not key:
        raise RuntimeError(
            "FB_TOKEN_ENCRYPTION_KEY is not set. Generate with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError(
            "Failed to decrypt Meta token — encryption key may have changed."
        ) from exc


def hmac_sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def hmac_verify(payload: bytes, signature: str, secret: str) -> bool:
    return hmac.compare_digest(hmac_sign(payload, secret), signature)


def sign_ingest(body: bytes) -> str:
    """Signature header value for POST → CRM /api/ads/meta/lead-ingest.

    Mirrors google-ads' `X-Ads-Signature` (CRM → ads-api), but in the opposite
    direction: fb-worker signs the resolved lead so the CRM route can trust it.
    """
    secret = get_settings().fb_ingest_hmac_secret.get_secret_value()
    if not secret:
        raise RuntimeError("FB_INGEST_HMAC_SECRET is not set — cannot sign CRM ingest.")
    return f"sha256={hmac_sign(body, secret)}"


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
