"""Evaluation metrics. All deterministic; the LLM judge lives in eval/judge.py and is reported separately."""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from src.agents.checks import (
    conversation_language,
    detect_language,
    evidence_text,
    fabricated_urls,
    numbers_in,
    unsupported_numbers,
    urls_in,
)

# --- retrieval ------------------------------------------------------------------------------------


def matches(selector: str, doc_id: str, section: str) -> bool:
    """A relevance label is 'doc_id' or 'doc_id::substring of the section heading'."""
    wanted_doc, _, wanted_section = selector.partition("::")
    return doc_id == wanted_doc and wanted_section.casefold() in section.casefold()


def relevance_vector(ranked: list[tuple[str, str]], relevant: list[str]) -> list[int]:
    return [int(any(matches(sel, doc, section) for sel in relevant)) for doc, section in ranked]


def hit_at_k(ranked: list[tuple[str, str]], relevant: list[str], k: int) -> float:
    return float(any(relevance_vector(ranked[:k], relevant)))


def recall_at_k(ranked: list[tuple[str, str]], relevant: list[str], k: int) -> float:
    found = sum(1 for sel in relevant if any(matches(sel, doc, section) for doc, section in ranked[:k]))
    return found / len(relevant) if relevant else 0.0


def reciprocal_rank(ranked: list[tuple[str, str]], relevant: list[str]) -> float:
    for position, flag in enumerate(relevance_vector(ranked, relevant), start=1):
        if flag:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked: list[tuple[str, str]], relevant: list[str], k: int) -> float:
    gains = relevance_vector(ranked[:k], relevant)
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return min(1.0, dcg / ideal) if ideal else 0.0


# --- answers --------------------------------------------------------------------------------------


_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"), "-")
_QUOTES = {ord("\u2019"): "'", ord("\u2018"): "'", ord("\u201c"): '"', ord("\u201d"): '"'}


def _fold(text: str) -> str:
    """Case, accents and typography folded away: models write "Wi\u2011Fi" and "couldn\u2019t", datasets write "wi-fi" and "couldn't"."""
    text = text.translate(_DASHES).translate(_QUOTES)
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _search(pattern: str, text: str) -> bool:
    return bool(re.search(_fold(pattern), _fold(text)))


def fact_coverage(answer: str, facts: list[list[str]]) -> tuple[float, list[int]]:
    """Each fact is a list of acceptable phrasings (regex, accent- and case-insensitive).

    This is how correctness is checked without brittle string matching: the dataset states the atomic
    facts a right answer must carry ("48", "R$ 129.90") and every wording or language that carries them.
    """
    if not facts:
        return 1.0, []
    missing = [i for i, alternatives in enumerate(facts) if not any(_search(alt, answer) for alt in alternatives)]
    return 1 - len(missing) / len(facts), missing


def forbidden_hits(answer: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if _search(p, answer)]


def numeric_groundedness(answer: str, observations: list[dict[str, Any]], *context: str) -> tuple[float, list[str]]:
    """Share of the numbers stated in the answer that appear in the evidence the agents actually collected."""
    stated = numbers_in(answer)
    if not stated:
        return 1.0, []
    unsupported = unsupported_numbers(answer, evidence_text(observations, *context))
    return 1 - len(unsupported) / len(stated), unsupported


def citation_validity(answer: str, observations: list[dict[str, Any]], *context: str) -> tuple[float, list[str]]:
    """Share of URLs in the answer that some tool returned. A URL from nowhere is a fabricated citation."""
    cited = {u.rstrip("/") for u in urls_in(answer)}
    if not cited:
        return 1.0, []
    fabricated = fabricated_urls(answer, observations, *context)
    return 1 - len(fabricated) / len(cited), fabricated


def language_match(turns: list[str], answer: str) -> tuple[bool, str | None, str | None]:
    """Is the answer in the language the merchant wrote in? Undetectable on either side counts as a match."""
    expected = conversation_language(turns[-1], [{"role": "user", "content": t} for t in turns[:-1]])
    actual = detect_language(answer)
    return (expected is None or actual is None or expected == actual), expected, actual


def gold_source_hit(sources: list[str], gold: list[str]) -> float | None:
    if not gold:
        return None
    normalized = {s.rstrip("/") for s in sources}
    return float(any(g.rstrip("/") in normalized for g in gold))


def includes_all(actual: list[str], expected: list[str]) -> bool:
    return all(item in actual for item in expected)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
