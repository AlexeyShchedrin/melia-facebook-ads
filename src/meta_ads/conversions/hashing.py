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


def normalize_name_part(part: str) -> str:
    # Meta fn/ln rule: UTF-8 lowercase, no digits/punctuation/whitespace.
    cleaned = re.sub(r"[\d\s\W_]+", "", part.strip().lower(), flags=re.UNICODE)
    return cleaned


def hash_name_part(part: str) -> str | None:
    norm = normalize_name_part(part)
    return _sha256(norm) if norm else None


def split_full_name(full_name: str) -> tuple[str | None, str | None]:
    """Best-effort (fn, ln) from a free-form full name: first token / last token."""
    tokens = [t for t in full_name.strip().split() if t]
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return tokens[0], None
    return tokens[0], tokens[-1]


def hash_external_id(value: str | int) -> str:
    # Meta recommends hashing external_id; normalization = trim+lowercase.
    return _sha256(str(value).strip().lower())
