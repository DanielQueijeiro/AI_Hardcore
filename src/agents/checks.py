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


# --- completeness: what the evidence says a complete answer cannot drop ------------------------------
#
# Asking a model "is this draft complete?" got "yes" for drafts that dropped the Wi-Fi step (g12) and the
# rental prices (g01). These checks extract, from the evidence rather than from the draft, the items a
# complete answer must account for, so the Critic has to rule on each one instead of skimming.

_STEP_MARK = re.compile(r"(?<![\w(])(\d{1,2})\)\s+")
_PRODUCT_NAME = re.compile(r"\bGet [A-ZÀ-Ý][\wÀ-ÿ]+")
_CLAUSE_SPLIT = re.compile(r"[.,](?!\d)|[;()]|\b(?:versus|vs\.?|and)\b", re.I)
_PRICE_VALUE = re.compile(r"R\$\s?(\d[\d.,]*\d(?:\s+(?:thousand|million|mil))?)", re.I)
_COMPARE_OR_PRICE = re.compile(
    r"differ|compar|\bvs\b|versus|better|which (one|should)|cost|price|how much|rent|\bfee|"
    r"diferen|melhor|cuesta|precio|pre[cç]o|quanto|aluguel|alquiler|\btaxa|tarifa",
    re.I,
)
_AMOUNT = re.compile(r"R\$\s?\d")
MAX_CHECKLIST_ITEMS = 8


def _product_amounts(text: str, name: str) -> list[str]:
    """R$ amounts that belong unambiguously to `name`.

    Splits on clause boundaries (including 'versus'/'vs'/'and') and keeps only clauses where `name` is the sole
    product mentioned, so comparative sentences ("R$ 79.90 for the Get Clássica versus R$ 129.90 for the Get Smart")
    never attribute one product's price to another.
    """
    amounts: list[str] = []
    for clause in _CLAUSE_SPLIT.split(text):
        names = set(_PRODUCT_NAME.findall(clause))
        if names == {name}:
            amounts.extend(_PRICE_VALUE.findall(clause))
    return list(dict.fromkeys(amounts))


def evidence_passages(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Knowledge-base passages the specialists actually retrieved this turn (raw tool results)."""
    passages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        for call in observation.get("evidence") or []:
            for row in (call.get("result") or {}).get("results") or []:
                if not isinstance(row, dict) or not row.get("text"):
                    continue
                key = str(row.get("chunk_id") or row["text"])  # the same chunk returned by two searches counts once
                if key not in seen:
                    seen.add(key)
                    passages.append(row)
    return passages


def procedure_steps(text: str) -> list[list[str]]:
    """Numbered procedures written inline ("1) restart ...; 2) connect ..."), three steps or more each."""
    runs: list[list[re.Match[str]]] = []
    for mark in _STEP_MARK.finditer(text):
        number = int(mark.group(1))
        if number == 1:
            runs.append([mark])
        elif runs and number == len(runs[-1]) + 1:
            runs[-1].append(mark)
    procedures = []
    for run in (r for r in runs if len(r) >= 3):
        steps = []
        for i, mark in enumerate(run):
            end = run[i + 1].start() if i + 1 < len(run) else len(text)
            step = text[mark.end() : end]
            if i + 1 == len(run):  # the last step ends with its sentence
                step = re.split(r"(?<=[.!?])\s", step, maxsplit=1)[0]
            steps.append(step.strip(" ;,.\n"))
        procedures.append(steps)
    return procedures


def _tokens(text: str) -> set[str]:
    from src.rag.index import tokenize  # local: keeps this module importable without the retrieval stack

    return set(tokenize(text))


def evidence_checklist(message: str, draft: str, observations: list[dict[str, Any]], *, compare_text: bool = True) -> list[dict[str, Any]]:
    """Items from the evidence a complete answer must include or deliberately leave out.

    Each item has `found_in_draft`: True or False when the draft's words can be compared with the evidence's
    (`compare_text`, i.e. an English draft against the English corpus), None when they cannot. Only items not
    found (or not checkable) are returned; the Critic rules on each.
    """
    passages = evidence_passages(observations)
    draft_tokens = _tokens(draft)
    items: list[dict[str, Any]] = []

    # A human decision this turn is the first thing the answer must convey (g15, s21: a rejection never stated,
    # and "I can't connect you to a person" right after a person answered).
    for observation in observations:
        if observation.get("agent") != "escalation":
            continue
        note = str(observation.get("operator_message") or "")[:200]
        executed = bool((observation.get("action_result") or {}).get("executed"))
        decision = {
            "reject": "The human operator did NOT approve the proposed action; nothing was changed. The draft must say so "
            "plainly, give the operator's note, and stay on the problem the merchant asked about.",
            "answer": "A human specialist answered in this conversation. The draft must relay their answer and must not "
            "say that a person cannot be reached or that it cannot connect the merchant to one.",
            "approve": "The human operator approved the action. "
            + ("A service order was created: the work is ordered or scheduled, not finished." if executed else "Nothing was executed yet."),
        }.get(str(observation.get("decision")))
        if decision:
            items.append({"item": f"{decision} Operator's note: {note or '(none)'}", "found_in_draft": None})

    for passage in passages:
        for steps in procedure_steps(str(passage["text"])):
            step_tokens = [_tokens(s) for s in steps]
            found: list[bool | None] = []
            for i, tokens in enumerate(step_tokens):
                others = set().union(*(t for j, t in enumerate(step_tokens) if j != i))
                distinctive = tokens - others
                found.append(
                    None if not compare_text else (not distinctive or len(distinctive & draft_tokens) / len(distinctive) >= 0.5)
                )
            # A procedure is in play when the draft follows part of it or cites its source. When the draft's words
            # cannot be compared (another language), only the citation can tell; a retrieved but unused procedure
            # would otherwise be listed for every answer that merely shares a search with it (s11).
            source = str(passage.get("source_url", ""))
            cited = bool(source) and source.rstrip("/") in draft
            if not cited and (not compare_text or not any(found)):
                continue
            items += [
                {"item": f"Step {i + 1} of the procedure in {source}: {step}", "found_in_draft": f}
                for i, (step, f) in enumerate(zip(steps, found, strict=True))
                if f is not True
            ]

    text = " ".join(str(p["text"]) for p in passages)
    folded_message = _fold(message)
    asked = sorted({n for n in _PRODUCT_NAME.findall(text) if _fold(n) in folded_message})
    if asked and (len(asked) >= 2 or _COMPARE_OR_PRICE.search(message)) and not _AMOUNT.search(draft):
        for name in asked:
            amounts = _product_amounts(text, name)
            if amounts:
                items.append(
                    {"item": f"Price the evidence states for {name}: " + ", ".join(f"R$ {a}" for a in amounts), "found_in_draft": False}
                )
    return items[:MAX_CHECKLIST_ITEMS]


def _fold(text: str) -> str:
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
