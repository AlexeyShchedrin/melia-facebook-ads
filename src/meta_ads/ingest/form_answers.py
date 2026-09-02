"""Custom-question answers for the CRM ingest payload (pipeline B).

Meta hands a lead's answers over as bare option keys -- `budget: budget_2`,
`expo_meeting: meeting_4` -- and keeps the human-readable question and option
labels on the form object only. Managers need to see what the visitor actually
said, so every CRM payload carries `answers`: the lead's non-identity fields
with both labels resolved from the form's question definitions.

Question definitions are cached in meta.leadgen_form_questions (one Graph read
per form, ever -- instant forms are immutable once published) plus an
in-process memo. A form whose questions cannot be fetched still ships its
answers, just without labels; the CRM then falls back to the raw keys.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from meta_ads.channels.meta.leadforms import get_form_questions

logger = logging.getLogger(__name__)

# Identity fields the CRM maps to name / phone / email -- never an "answer".
# Both the form's own keys and the aliases field_data_to_map adds are listed.
IDENTITY_KEYS = frozenset(
    {
        "full_name",
        "first_name",
        "last_name",
        "email",
        "e-mail",
        "work_email",
        "phone",
        "phone_number",
        "work_phone",
        "work_phone_number",
    }
)
# Meta's own link to the Messenger thread on conversational forms: it arrives
# as a CUSTOM question named inbox_url, but nobody typed it.
SYSTEM_KEYS = frozenset({"inbox_url"})

Answer = dict[str, str | None]


def is_answer_key(key: str) -> bool:
    """A field the visitor answered, as opposed to who they are."""
    k = key.strip().lower()
    if k in IDENTITY_KEYS or k in SYSTEM_KEYS:
        return False
    return not k.startswith(("phone", "email", "work_"))


def build_answers(
    fields: Mapping[str, str], questions: Sequence[Mapping[str, Any]] | None
) -> list[Answer]:
    """Label the lead's non-identity fields against the form's questions.

    Ordered as the form asks them; keys the definition does not list (hand-built
    forms, unknown aliases) are appended without a label. A choice question
    resolves the option key to its label, a free-text question echoes the
    visitor's text, and an option key the form does not know (the Lead Ads
    Testing Tool sends dummy text) leaves value_label empty so the CRM shows
    the raw value instead of guessing."""
    by_key: dict[str, Mapping[str, Any]] = {}
    for q in questions or []:
        key = q.get("key")
        if isinstance(key, str) and key and key not in by_key:
            by_key[key] = q
    remaining = {k: v for k, v in fields.items() if isinstance(k, str) and is_answer_key(k)}
    out: list[Answer] = []
    for key, q in by_key.items():
        if key in remaining:
            out.append(_label(key, remaining.pop(key), q))
    for key, value in remaining.items():
        out.append(_label(key, value, None))
    return out


def _label(key: str, value: str, question: Mapping[str, Any] | None) -> Answer:
    label: str | None = None
    value_label: str | None = None
    if question is not None:
        label = question.get("label") or None
        options = question.get("options") or []
        if options:
            for opt in options:
                if isinstance(opt, Mapping) and opt.get("key") == value:
                    value_label = opt.get("value") or None
                    break
        else:
            value_label = value
    return {"key": key, "label": label, "value_key": value, "value_label": value_label}


class FormQuestionsCache:
    """form_id -> Graph `questions`, memoized in-process and persisted in
    meta.leadgen_form_questions.

    `get` never raises: a Graph or DB failure is logged and yields None, and
    the next lead of that form tries again. DB touches run under a SAVEPOINT
    so a failure cannot poison the resolver's transaction (which still has
    the CRM POST and the processed_inbound record ahead of it)."""

    def __init__(self) -> None:
        self._memo: dict[str, list[dict[str, Any]]] = {}

    async def get(
        self, session: AsyncSession | None, form_id: str, page_id: str | None = None
    ) -> list[dict[str, Any]] | None:
        memo = self._memo.get(form_id)
        if memo is not None:
            return memo
        if session is not None:
            stored = await self._load(session, form_id)
            if stored is not None:
                self._memo[form_id] = stored
                return stored
        form = await self.fetch(session, form_id, page_id)
        return self._memo.get(form_id) if form is not None else None

    async def fetch(
        self, session: AsyncSession | None, form_id: str, page_id: str | None = None
    ) -> dict[str, Any] | None:
        """Read the form from Graph and cache it (memo + DB). None on failure."""
        try:
            form = await get_form_questions(form_id, page_id)
        except Exception:  # noqa: BLE001
            logger.warning("form questions: could not fetch form %s", form_id, exc_info=True)
            return None
        questions = [dict(q) for q in form.get("questions") or [] if isinstance(q, Mapping)]
        self._memo[form_id] = questions
        if session is not None:
            await self._store(session, form_id, page_id, form, questions)
        return form

    async def _load(self, session: AsyncSession, form_id: str) -> list[dict[str, Any]] | None:
        try:
            async with session.begin_nested():
                row = (
                    await session.execute(
                        text(
                            "SELECT questions FROM meta.leadgen_form_questions WHERE form_id = :f"
                        ),
                        {"f": form_id},
                    )
                ).first()
        except Exception:  # noqa: BLE001
            logger.warning("form questions: cache read failed for form %s", form_id, exc_info=True)
            return None
        if row is None or not isinstance(row[0], list):
            return None
        return [dict(q) for q in row[0] if isinstance(q, Mapping)]

    async def _store(
        self,
        session: AsyncSession,
        form_id: str,
        page_id: str | None,
        form: Mapping[str, Any],
        questions: list[dict[str, Any]],
    ) -> None:
        try:
            async with session.begin_nested():
                await session.execute(
                    text(
                        "INSERT INTO meta.leadgen_form_questions "
                        "(form_id, page_id, name, locale, questions, fetched_at) "
                        "VALUES (:f, :p, :n, :l, CAST(:q AS jsonb), now()) "
                        "ON CONFLICT (form_id) DO UPDATE SET "
                        "page_id = EXCLUDED.page_id, name = EXCLUDED.name, "
                        "locale = EXCLUDED.locale, questions = EXCLUDED.questions, "
                        "fetched_at = now()"
                    ),
                    {
                        "f": form_id,
                        "p": page_id,
                        "n": (form.get("name") or None),
                        "l": (form.get("locale") or None),
                        "q": json.dumps(questions, ensure_ascii=False),
                    },
                )
        except Exception:  # noqa: BLE001
            logger.warning("form questions: cache write failed for form %s", form_id, exc_info=True)
