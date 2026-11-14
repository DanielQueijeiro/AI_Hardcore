"""Deterministic answer checks shared by the Critic (runtime) and the evaluation harness (offline).

They need no model, so they run on every turn and in CI. They are deliberately narrow: numbers and
citations are the claims a payments assistant must never get wrong, and both can be verified exactly.
"""

from __future__ import annotations

import json
import re
from typing import Any

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_URL = re.compile(r"https?://[^\s)\]>\"'*,]+")
_LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")


# Identifiers the system itself mints (ticket and service-order ids). They are not numeric claims.
_SYSTEM_ID = re.compile(r"\b(?:TKT-\d{6}-[0-9A-F]{6}|SO-[0-9A-F]{8})\b", re.I)

# Function words that tell English, Portuguese and Spanish apart. Words shared across languages
# ("a", "no", "do", "as", "me") are left out on purpose; product names never appear here, so an English
# answer full of "crediário" and "Get Clássica" is still detected as English.
_LANGUAGE_WORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        """the is are you your and of to in for with this that will can how what when my it be not have has from was
        does which there an if or by at on we they their should would please yesterday today these those been were
        but about into than then here still any i now also only why where who whose""".split()
    ),
    "pt": frozenset(
        """o os um uma da dos das e em na nos nas para por com que não nao você voce é são sao está esta meu minha seu
        sua ao à pelo pela também tambem até ate como qual quando onde mais se foi ser tem isso ou já ja ainda sem
        sobre pode posso seus suas essa esse ele ela às aos estão estao estou quantas quantos quais têm tenho temos podem
        vocês voces""".split()
    ),
    "es": frozenset(
        """el la los las un una del y en para por con que usted es son está esta mi su al también tambien hasta como
        cuál cual cuándo cuando dónde donde más se fue ser tiene eso ya lo le puede puedo hay sin sobre sus ese
        esa él ella cuántas cuantas cuánto cuanto qué pero están estan estoy cuántos cuantos cuáles cuales quién quien
        tienen tengo tenemos pueden ustedes""".split()
    ),
}
LANGUAGE_NAMES = {"en": "English", "pt": "Portuguese", "es": "Spanish"}


def detect_language(text: str) -> str | None:
    """'en', 'pt' or 'es' when the function words make it clear; None when the text is too short or mixed."""
    words = re.findall(r"[^\W\d_]+", _URL.sub(" ", text).lower())
    if not words:
        return None
    scores = {lang: sum(w in vocabulary for w in words) for lang, vocabulary in _LANGUAGE_WORDS.items()}
    ranked = sorted(scores.items(), key=lambda item: -item[1])
    (best, top), (_, second) = ranked[0], ranked[1]
    if top < 2 or top - second < max(1, round(0.25 * top)):
        return None
    return best


def conversation_language(message: str, history: list[dict[str, str]] | None = None) -> str | None:
    """Language to answer in: the current message's, else the most recent earlier user message's."""
    detected = detect_language(message)
    if detected:
        return detected
    for entry in reversed(history or []):
        if entry.get("role") == "user" and not entry.get("content", "").startswith("["):
            detected = detect_language(entry["content"])
            if detected:
                return detected
    return None


def language_mismatch(answer: str, expected: str | None) -> str | None:
    """The language the answer is written in, when it is clearly not the expected one; otherwise None."""
    if not expected:
        return None
    actual = detect_language(answer)
    return actual if actual and actual != expected else None


def _normalize_number(token: str) -> str:
    token = re.sub(r"[.,]0+$", "", token)
    return re.sub(r"[.,]", "", token).lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    """Numeric claims worth verifying: two or more significant digits (fees, amounts, phones, dates, codes)."""
    text = _LIST_MARKER.sub(" ", _SYSTEM_ID.sub(" ", _URL.sub(" ", text)))
    return {n for n in (_normalize_number(t) for t in _NUMBER.findall(text)) if len(n) >= 2}


def unsupported_numbers(answer: str, evidence: str) -> list[str]:
    """Numbers stated in the answer that appear nowhere in the evidence the agents collected."""
    supported = numbers_in(evidence)
    haystack = re.sub(r"[.,\s]", "", evidence)
    return sorted(n for n in numbers_in(answer) if n not in supported and n not in haystack)


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".;:") for u in _URL.findall(text)]


def evidence_text(observations: list[dict[str, Any]], *extra: str) -> str:
    return json.dumps(observations, ensure_ascii=False, default=str) + "\n" + "\n".join(extra)


def tool_urls(observations: list[dict[str, Any]], *context: str) -> set[str]:
    """URLs that a tool actually returned (plus any in the given context, e.g. earlier turns).

    Only raw tool results count. What an agent wrote in its report does not, otherwise a model could
    launder an invented URL into "evidence" simply by mentioning it.
    """
    raw = json.dumps([o.get("evidence", []) for o in observations], ensure_ascii=False, default=str)
    return {u.rstrip("/") for u in urls_in(" ".join((raw, *context)))}


def fabricated_urls(answer: str, observations: list[dict[str, Any]], *context: str) -> list[str]:
    known = tool_urls(observations, *context)
    return sorted({u for u in urls_in(answer) if u.rstrip("/") not in known})
