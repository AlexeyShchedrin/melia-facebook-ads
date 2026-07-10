"""boost/lint.py — compliance regexes across the brief's caption languages."""

from __future__ import annotations

import pytest

from meta_ads.boost.lint import lint_caption

# (test id, caption, rule that must trip)
HOT: list[tuple[str, str, str]] = [
    ("en-guarantee", "Guaranteed rental income for 5 years", "guarantee"),
    ("en-yield", "8% net yield on your apartment", "yield_roi"),
    ("en-roi", "The best ROI on the Adriatic coast", "yield_roi"),
    ("en-passive", "Earn passive income by the sea", "yield_roi"),
    ("en-residency", "Golden visa included with every purchase", "residency"),
    ("en-permit", "Residence permit assistance for buyers", "residency"),
    ("en-beach", "Your own private beach residence", "private_beach"),
    ("ru-guarantee", "Гарантированная доходность 8% годовых", "guarantee"),
    ("ru-yield", "Стабильная доходность от аренды", "yield_roi"),
    ("ru-passive", "Пассивный доход у моря", "yield_roi"),
    ("ru-vnzh", "ВНЖ Черногории при покупке", "residency"),
    ("ru-permit", "Оформим вид на жительство", "residency"),
    ("ru-beach", "Частный пляж только для резидентов", "private_beach"),
    ("de-guarantee", "Mieteinnahmen garantiert!", "guarantee"),
    ("de-rendite", "Hohe Rendite am Meer", "yield_roi"),
    ("de-rendite-plural", "Attraktive Renditen ab Tag eins", "yield_roi"),
    ("de-residency", "Aufenthaltserlaubnis inklusive", "residency"),
    ("de-beach", "Eigener Privatstrand für Bewohner", "private_beach"),
    ("pl-guarantee", "Gwarantowany zysk z najmu", "guarantee"),
    ("pl-passive", "Dochód pasywny nad Adriatykiem", "yield_roi"),
    ("pl-beach", "Prywatna plaża tylko dla mieszkańców", "private_beach"),
    ("sr-guarantee", "Garantovan povraćaj ulaganja", "guarantee"),
    ("sr-yield", "Siguran prinos od izdavanja", "yield_roi"),
    ("sr-residency", "Boravišna dozvola uz kupovinu", "residency"),
    ("sr-beach", "Privatna plaža uz rezidenciju", "private_beach"),
    ("he-guarantee", "תשואה מובטחת לחמש שנים", "guarantee"),
    ("he-residency", "אשרת שהייה לרוכשים", "residency"),
    ("tr-yield", "yüksek randıman vaat ediyor", "yield_roi"),
    ("ua-guarantee", "гарантія прибутку для інвесторів", "guarantee"),
    ("sq-guarantee", "kthim i garantuar nga qiraja", "guarantee"),
]


@pytest.mark.parametrize(("caption", "rule"), [(h[1], h[2]) for h in HOT], ids=[h[0] for h in HOT])
def test_hot_captions_trip_the_rule(caption: str, rule: str) -> None:
    hits = lint_caption(caption)
    assert hits, f"expected a lint hit for: {caption!r}"
    assert rule in {h.split(":", 1)[0] for h in hits}


# Real caption phrases from the brief that must NOT trip (installments, dates,
# plain "beach", and substring traps like "croissant" containing "roi").
CLEAN = [
    "20% first installment, keys in 2027",
    "interest-free instalments over 24 months",
    "Q4 2027",
    "Completion in Q4 2027 — flexible payment plan",
    "Fresh croissants at the beach bar every morning",
    "Wide sandy beach a three-minute walk away",
    "Рассрочка 0%, пляж в трёх минутах ходьбы",
    "Renditerechner online verfügbar",  # Rendite(?!r) — the calculator word is out of scope
    "Two pools, a spa and panoramic sea views",
    "",
]


@pytest.mark.parametrize("caption", CLEAN)
def test_clean_captions_pass(caption: str) -> None:
    assert lint_caption(caption) == []


def test_hits_carry_rule_and_fragment() -> None:
    hits = lint_caption("Guaranteed yield and a private beach")
    assert sorted(h.split(":", 1)[0] for h in hits) == ["guarantee", "private_beach", "yield_roi"]
    assert "guarantee:Guarantee" in hits  # fragment kept for ig_boost_state.lint_hits
