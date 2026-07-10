"""Caption compliance lint for IG auto-boost.

The brief's hard guardrails (brand/brief.md in melia-montage, mirrored in
research/06-strategy-2026.md) ban absolute claims in paid placements:
guaranteed anything, yield/ROI promises, residency/visa promises, and
"private beach" (the beach is public). Organic captions are written by hand
and sometimes slip — so anything the auto-boost job would put money behind is
linted first. One hit → the media is recorded `skipped_lint` and never
boosted; a human rewrites the caption or boosts manually.

Languages covered (the funnel's audience mix): RU / EN / DE / PL / SR / HE /
TR / UA / SQ. Patterns are stems, case-insensitive, with a leading word
boundary so substrings inside harmless words ("croissant" vs "ROI",
"Detroit") never trip.
"""

from __future__ import annotations

import re

# rule label -> pattern. No trailing \b on purpose: stems must match their
# inflections ("гарантия", "guaranteed", "prinosi", "Renditen", "מובטחת").
_RULES: dict[str, str] = {
    "guarantee": (
        r"\b(?:guarantee|guaranteed|гарант\w*|garantiert|gwarantowan\w*"
        r"|garantovan\w*|garantuar|מובטח)"
    ),
    "yield_roi": (
        r"\b(?:yield|ROI|passive income|доходност\w*|пассивн\w* доход"
        r"|prinos|dochód pasywny|Rendite(?!r)|randıman)"
    ),
    "residency": (
        r"\b(?:residence permit|golden visa|ВНЖ|вид на жительство"
        r"|Aufenthalt\w*|boravišn\w*|אשרת)"
    ),
    "private_beach": (
        r"\b(?:private beach|частн\w+ пляж|privatstrand|prywatn\w+ plaż\w+"
        r"|privatna plaža)"
    ),
}

_COMPILED: dict[str, re.Pattern[str]] = {
    label: re.compile(pattern, re.IGNORECASE) for label, pattern in _RULES.items()
}


def lint_caption(text: str) -> list[str]:
    """Compliance-lint a caption; [] means clean (safe to put money behind).

    Each hit is returned as ``"<rule>:<matched fragment>"`` — the fragment goes
    into `meta.ig_boost_state.lint_hits` so the skip is explainable later.
    """
    hits: list[str] = []
    for label, pattern in _COMPILED.items():
        m = pattern.search(text or "")
        if m:
            hits.append(f"{label}:{m.group(0)}")
    return hits
