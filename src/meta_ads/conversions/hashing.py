"""SHA-256 hashing of normalized PII for Meta Advanced Matching.

Normalization must match Meta's rules exactly or match rate collapses:
email → trim + lowercase; phone → digits with country code, no '+'/spaces.
"""

from __future__ import annotations

import hashlib
import re


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_phone(phone: str) -> str:
    # Meta wants digits only, including country code (E.164 without the '+').
    digits = re.sub(r"\D", "", phone)
    return digits


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_email(email: str) -> str:
    return _sha256(normalize_email(email))


def hash_phone(phone: str) -> str:
    return _sha256(normalize_phone(phone))
