"""Deterministic stand-in for the model, behind the same port.

Three uses: CI and tests without network or cost, a no-key demo, and graceful degradation when the
provider is down (ResilientLLM falls back to it and the response is flagged `degraded`).

It is a rule policy, not intelligence: it reads the structured `context` every agent passes alongside its
prompt and answers with the same typed tool calls a model would produce. Answers are extractive (sentences
lifted from tool results), so they stay grounded but are less fluent and less adaptive than the model path.
"""

from __future__ import annotations

import re
from typing import Any

from src.llm.base import LLMResponse, ToolCall
from src.rag.index import fold, tokenize

_POSSESSIVE = r"\b(my|our|minha|meu|nossa|nosso|mi|nuestra|nuestro)\b"
_MACHINE = r"(card machine|machine|maquininha|maquina|terminal|pos\b|datafono)"
_MONEY_ACCOUNT = re.compile(
    r"\b(yesterday|ontem|ayer)\b|\bwhen will\b.*\b(deposited|paid|credited|receive)\b"
    r"|\bquando\b.*\b(cai|recebo|receber|depositad)\w*|\bcuando\b.*\b(recibo|recibir|deposit)\w*"
    r"|" + _POSSESSIVE + r"\s+(settlements?|payouts?|deposits?|balance|statement|repasse|extrato|saldo)\b"
)
_POS_ACCOUNT = re.compile(
    _POSSESSIVE + r"\s+(\w+\s+)?" + _MACHINE + r"|\b(it|ele|ela)\b.*\b(offline|connect|conecta)\w*|\b(still|ainda|continua|sigue)\b.*\boffline\b"
)
_TICKET = re.compile(r"\b(ticket|chamado|protocolo|solicitud|my request)\b")
_HUMAN = re.compile(
    r"\b(human|person|atendente|humano|pessoa|persona|representative|operator|real agent)\b"
    r"|\b(talk|speak|falar|hablar)\b.*\b(someone|alguem|alguien|specialist|especialista)\b"
)
_FX = re.compile(r"\b(euro|eur|dollar|dolar|usd|pound|gbp|exchange rate|cotacao|cambio|currency)\b")
_WEATHER = re.compile(r"\b(weather|forecast|previsao do tempo|clima|temperature|temperatura|rain|chuva)\b")
_CONNECT = re.compile(r"\b(connect\w*|internet|offline|conect\w*|sinal|signal|wi-?fi|rede|network)\b")
_DECLINE = re.compile(r"\b(declin\w*|recusad\w*|rechazad\w*|negad\w*|error|erro)\b")
_DOMAIN_WORDS = (
    """getnet get maquininha machine pix link crediario antecipacao receivable advance fee taxa rate settlement
    recebimento pos terminal card cartao tef conta account chargeback rental aluguel installment parcelado
    parcelamento whatsapp smart classica mini tap boleto debit credit debito credito support suporte phone
    telefone sale venda payment pagamento offline_gprs_timeout err_51_issuer_decline pos_key_sync_warn code
    decline merchant lojista""".split()
)
_DOMAIN = frozenset(tokenize(" ".join(_DOMAIN_WORDS))) | frozenset(_DOMAIN_WORDS)


def _on_domain(text: str) -> bool:
    return bool(_DOMAIN.intersection(tokenize(text)) or _DOMAIN.intersection(re.findall(r"[a-z0-9_]+", fold(text))))


def _is_account(text: str) -> bool:
    return bool(_MONEY_ACCOUNT.search(text) or _POS_ACCOUNT.search(text) or _TICKET.search(text))


def _public_part(message: str) -> str:
    """Decompose a compound message: the clause that is a product question rather than an account lookup."""
    clauses = [
        c.strip()
        for c in re.split(r"\?|;|,?\s+(?:and|e|y)\s+(?=what|how|which|qual|como|cu[aá]l|quanto|cu[aá]nto)", message)
        if c.strip()
    ]
    if len(clauses) < 2:
        return ""
    return next((c for c in clauses if not _is_account(fold(c)) and _on_domain(c)), "")
_ANAPHORA = re.compile(r"\b(it|that|this|those|these|they|them|same|still|also|ele|ela|isso|ainda|continua|tambien|tambem|eso|sigue|and what about|e o|y el)\b")


def _call(name: str, **arguments: Any) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(id=f"offline_{name}", name=name, arguments=arguments)])


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text) if s.strip()]


class OfflinePolicyLLM:
    name = "offline"
    model = "offline-rule-policy"

    def complete(self, *, role: str, context: dict[str, Any] | None = None, **_: Any) -> LLMResponse:
        handler = getattr(self, f"_{role}", None)
        response = handler(context or {}) if handler else LLMResponse()
        response.model = self.model
        return response

    # --- Router ---------------------------------------------------------------------------------------

    @staticmethod
    def _effective_message(ctx: dict[str, Any]) -> str:
        """Resolve a short follow-up ("it is still offline") against the previous user turn."""
        message = ctx.get("message", "")
        folded = fold(message)
        previous = [m["content"] for m in ctx.get("history", []) if m["role"] == "user" and not m["content"].startswith("[")]
        has_signal = any(p.search(folded) for p in (_MONEY_ACCOUNT, _TICKET, _FX, _WEATHER)) or bool(
            re.search(_POSSESSIVE + r"\s+(\w+\s+)?" + _MACHINE, folded)
        )
        if previous and not has_signal and (_ANAPHORA.search(folded) or (len(folded.split()) <= 8 and not _on_domain(message))):
            return f"{previous[-1]} Follow-up: {message}"
        return message

    def _supervisor(self, ctx: dict[str, Any]) -> LLMResponse:
        message = self._effective_message(ctx)
        text = fold(message)
        observations = ctx.get("observations", [])
        authenticated = bool(ctx.get("authenticated"))
        of = lambda agent: [o for o in observations if o.get("agent") == agent]  # noqa: E731
        support, knowledge, escalation = of("support"), of("knowledge"), of("escalation")
        account = _is_account(text)
        wants_human = bool(_HUMAN.search(text))
        refused = any("Refused" in str(o.get("note", "")) for o in of("router"))

        def finish() -> LLMResponse:
            return _call("finish", answer=self._compose(observations, account, authenticated), confidence="medium")

        if ctx.get("force_finish") or ctx.get("critic_feedback") or escalation or refused:
            return finish()
        if not support and not knowledge:
            if account and authenticated:
                return _call(
                    "delegate_support",
                    thought="The message is about the merchant's own account, so account data comes first.",
                    task=message,
                    remaining_plan=["explain any status or error code with the knowledge base", "escalate if an approval is required", "answer"],
                )
            if wants_human and authenticated:
                return _call(
                    "escalate_to_human",
                    thought="The merchant explicitly asked for a person.",
                    reason="customer_request",
                    question=message,
                    proposed_action="none",
                    remaining_plan=["relay the operator's answer"],
                )
            return _call(
                "delegate_knowledge",
                thought="Public information is needed; no account data is involved or available.",
                task=message,
                remaining_plan=["answer with sources"],
            )
        if support:
            report = support[-1]["report"]
            follow_up = report.get("follow_up_for_knowledge", "")
            public = _public_part(message)
            if (follow_up or public) and not knowledge:
                return _call(
                    "delegate_knowledge",
                    thought="The account data returned a specific code; the knowledge base should explain it before answering."
                    if follow_up
                    else "The message also contains a product question that account data cannot answer.",
                    task=follow_up or public,
                    remaining_plan=["escalate if an approval is required", "answer"],
                )
            if report.get("needs_human_approval") and authenticated:
                return _call(
                    "escalate_to_human",
                    thought="The fix is an action a human must approve.",
                    reason="approval_required",
                    question=f"Approve action '{report['proposed_action']}' for this merchant?",
                    proposed_action=report["proposed_action"],
                    remaining_plan=["report the operator's decision"],
                )
            if wants_human and authenticated:
                return _call(
                    "escalate_to_human",
                    thought="The merchant asked for a person.",
                    reason="customer_request",
                    question=message,
                    proposed_action="none",
                    remaining_plan=["relay the operator's answer"],
                )
        return finish()

    @staticmethod
    def _compose(observations: list[dict[str, Any]], account: bool, authenticated: bool) -> str:
        parts: list[str] = []
        sources: list[str] = []
        if account and not authenticated:
            parts.append("I can only show account data (settlements, card machine status, tickets) to a signed-in merchant. Please sign in and ask again.")
        for obs in observations:
            agent = obs.get("agent")
            if agent == "support" and obs["report"].get("findings"):
                parts.append(obs["report"]["findings"])
            elif agent == "knowledge":
                report = obs["report"]
                if report.get("answer"):
                    parts.append(report["answer"])
                sources.extend(u for u in report.get("sources", []) if u not in sources)
            elif agent == "escalation":
                parts.append(OfflinePolicyLLM._outcome(obs))
        if not parts:
            parts.append("I could not find information to answer that. You can ask me to hand this to a human specialist.")
        if sources:
            parts.append("Sources: " + ", ".join(sources))
        return "\n\n".join(parts)

    @staticmethod
    def _outcome(obs: dict[str, Any]) -> str:
        ticket, decision, note = obs.get("ticket_id"), obs.get("decision"), obs.get("operator_message") or ""
        result = obs.get("action_result") or {}
        suffix = f' Operator note: "{note}"' if note else ""
        if decision == "approve" and result.get("executed"):
            return f"A human specialist reviewed ticket {ticket} and approved the action. Service order {result.get('order_id')} was created for {result.get('action')}.{suffix}"
        if decision == "approve":
            return f"A human specialist approved ticket {ticket}, but the action was not executed ({result.get('error', 'no action attached')}).{suffix}"
        if decision == "reject":
            return f"A human specialist reviewed ticket {ticket} and did not approve the action. Nothing was changed.{suffix}"
        if decision == "answer":
            return f"A human specialist answered ticket {ticket}.{suffix}"
        return f"No human specialist was able to respond to ticket {ticket} in time. Nothing was changed; the ticket remains on record and you can contact Getnet support directly."

    # --- Knowledge Agent ------------------------------------------------------------------------------

    def _knowledge(self, ctx: dict[str, Any]) -> LLMResponse:
        task = ctx.get("task", "")
        text = fold(task)
        results = ctx.get("tool_results", [])
        if not results:
            if _FX.search(text):
                base = "USD" if re.search(r"\b(dollar|dolar|usd)\b", text) else "GBP" if re.search(r"\b(pound|gbp)\b", text) else "EUR"
                return _call("get_fx_rate", base=base, quote="BRL")
            if _WEATHER.search(text):
                city = re.search(r"\b(?:in|em|en)\s+([A-Z][\wÀ-ſ]+(?:\s+[A-Z][\wÀ-ſ]+)*)", task)
                if city:
                    return _call("get_weather_forecast", city=city.group(1))
                return _call("web_search", query=task)
            if _on_domain(task):
                return _call("search_getnet_knowledge", query=task)
            return _call("web_search", query=task)

        searches = [r for r in results if r["tool"] == "search_getnet_knowledge"]
        if searches and len(searches) < 2 and searches[-1]["result"].get("relevance") == "poor" and not ctx.get("last"):
            # reconsider: retry once with the domain terms only before giving up
            keywords = " ".join(dict.fromkeys(tokenize(task, expand=True)))
            if keywords and keywords != fold(searches[-1]["arguments"].get("query", "")):
                return _call("search_getnet_knowledge", query=keywords)
        return _call("report", **self._knowledge_report(task, results))

    @staticmethod
    def _knowledge_report(task: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        last = results[-1]
        tool, data = last["tool"], last["result"]
        if tool == "get_fx_rate":
            if not data.get("available"):
                return {"answer": "The live exchange-rate source could not be reached right now, so I cannot give today's rate.", "sources": [], "confidence": "low", "gaps": "live FX rate"}
            return {
                "answer": f"1 {data['base']} = {data['rate']} {data['quote']} (reference date {data['reference_date']}; {data['source']}).",
                "sources": [data["source_url"]],
                "confidence": "high",
                "gaps": "",
            }
        if tool == "get_weather_forecast":
            if not data.get("available"):
                return {"answer": "The live weather source could not be reached right now, so I cannot give the forecast.", "sources": [], "confidence": "low", "gaps": "live forecast"}
            tomorrow = re.search(r"\b(tomorrow|amanha|manana)\b", fold(task)) and len(data["daily"]) > 1
            day = data["daily"][1 if tomorrow else 0]
            return {
                "answer": (
                    f"Forecast for {data['location']} on {day['date']}: {day['condition']}, high {day['temp_max_c']} C, "
                    f"low {day['temp_min_c']} C, precipitation probability {day['precipitation_probability_pct']}% ({data['source']})."
                ),
                "sources": [data["source_url"]],
                "confidence": "high",
                "gaps": "",
            }
        if tool == "web_search":
            rows = data.get("results") or []
            if not rows:
                return {"answer": "Web search returned nothing usable, so I could not confirm an answer.", "sources": [], "confidence": "low", "gaps": task}
            lines = [f"{r['title']}: {r['snippet']}" for r in rows[:3]]
            return {"answer": "From a web search (third-party sources): " + " | ".join(lines), "sources": [r["url"] for r in rows[:3]], "confidence": "medium", "gaps": ""}

        # search_getnet_knowledge: extractive answer from the best passages across all searches
        passages: dict[str, dict[str, Any]] = {}
        for result in results:
            if result["tool"] == "search_getnet_knowledge":
                for passage in result["result"].get("results", []):
                    current = passages.get(passage["chunk_id"])
                    if current is None or passage["coverage"] > current["coverage"]:
                        passages[passage["chunk_id"]] = passage
        ranked = sorted(passages.values(), key=lambda p: (-p["coverage"], -p["score"]))
        usable = [p for p in ranked if p["coverage"] >= 0.34][:3]
        if not usable:
            return {
                "answer": "The Getnet knowledge base does not cover this, so I could not confirm an answer.",
                "sources": [],
                "confidence": "low",
                "gaps": task,
            }
        terms = set(tokenize(task, expand=True))
        chosen: list[str] = []
        for position, passage in enumerate(usable):
            sentences = _sentences(passage["text"])
            scored = sorted(
                ((len(terms & set(tokenize(s))), -i, s) for i, s in enumerate(sentences)), reverse=True
            )
            keep = {s for score, _, s in scored[: 3 if position == 0 else 2] if score > 0}
            body = " ".join(s for s in sentences if s in keep)
            if not body:
                continue
            label = "Internal troubleshooting guidance (not published Getnet policy)" if passage["origin"] == "internal_runbook_mock" else passage["title"]
            chosen.append(f"{label}: {body}")
        best = usable[0]["coverage"]
        return {
            "answer": "\n".join(chosen),
            "sources": list(dict.fromkeys(p["source_url"] for p in usable if p["source_url"])),
            "confidence": "high" if best >= 0.6 else "medium",
            "gaps": "",
        }

    # --- Customer Support Agent -----------------------------------------------------------------------

    def _support(self, ctx: dict[str, Any]) -> LLMResponse:
        task = ctx.get("task", "")
        text = fold(task)
        results = ctx.get("tool_results", [])
        used = {r["tool"] for r in results}
        wanted: list[str] = []
        if _MONEY_ACCOUNT.search(text) or re.search(r"\b(settlement|deposit|payout|sales|vendas|ventas|money|dinheiro)\w*", text):
            wanted.append("get_settlements")
        if re.search(_MACHINE, text) or _CONNECT.search(text) or _DECLINE.search(text):
            wanted.append("get_pos_diagnostics")
        if _TICKET.search(text):
            wanted.append("list_my_tickets")
        if not wanted:
            wanted.append("get_account_profile")
        for name in wanted:
            if name not in used and not ctx.get("last"):
                return _call(name)

        findings: list[str] = []
        follow_up, needs_human, action = "", False, "none"
        for item in results:
            data = item["result"]
            if data.get("error") == "authentication_required":
                findings = ["The caller is not signed in, so no account data could be read."]
                break
            if data.get("error") or data.get("found") is False:
                findings.append(f"{item['tool']} returned no data ({data.get('error', 'not found')}).")
            elif item["tool"] == "get_settlements":
                lines = [
                    f"- {s['modality']}: gross {s['gross_amount_brl']}, net {s['net_amount_brl']}, cycle {s['settlement_cycle']}, status {s['status']}, when: {s['scheduled_window']}"
                    for s in data["settlements"]
                ]
                findings.append(f"Settlement schedule for {data['reference_period']} (deposit account: {data['deposit_account']}):\n" + "\n".join(lines))
            elif item["tool"] == "get_pos_diagnostics":
                decline = data.get("last_transaction_decline")
                wants_decline = bool(_DECLINE.search(text)) and not _CONNECT.search(text)
                if not wants_decline:
                    findings.append(
                        f"Card machine {data['terminal_id']} ({data['model']}): connectivity status {data['connectivity_status']}; "
                        f"mobile data: {data['sim_4g_state']}; Wi-Fi: {data['wifi_state']}."
                    )
                    if not data["connectivity_status"].startswith("ONLINE"):
                        follow_up = f"What does telemetry status {data['connectivity_status']} mean and what steps fix a card machine that will not connect to the internet?"
                if decline and (wants_decline or not _CONNECT.search(text)):
                    findings.append(
                        f"Last declined transaction on {data['terminal_id']}: {decline['transaction_id']} ({decline['amount_brl']}), "
                        f"code {decline['decline_code']}. Reason: {decline['reason']}"
                    )
                    if wants_decline:
                        follow_up = f"What do decline codes {decline['decline_code']} mean and how are they resolved?"
                        if decline.get("requires_human_approved_action"):
                            needs_human, action = True, "terminal_rekey_or_swap"
                elif wants_decline:
                    findings.append(f"No recent declined transaction is recorded for {data['terminal_id']}.")
            elif item["tool"] == "list_my_tickets":
                rows = data.get("tickets", [])
                findings.append(
                    "Tickets: " + "; ".join(f"{t['ticket_id']} is {t['status']}" + (f" (operator: {t['operator_message']})" if t["operator_message"] else "") for t in rows)
                    if rows
                    else "There are no human-review tickets on record for this merchant."
                )
            elif item["tool"] == "get_account_profile":
                bank = data["bank_account"]
                findings.append(
                    f"Account: {data['business_name']}, {data['city']}-{data['state']}; bank {bank['bank_name']} ({bank['bank_code']}), account ending {bank['account_number']}; "
                    f"receivables advance active: {data['receivables_advance_active']}."
                )
        return _call(
            "report",
            findings="\n".join(findings),
            follow_up_for_knowledge=follow_up,
            needs_human_approval=needs_human,
            proposed_action=action,
        )

    # --- Escalation, Critic, memory -------------------------------------------------------------------

    def _escalation(self, ctx: dict[str, Any]) -> LLMResponse:
        findings = " ".join(o["report"]["findings"] for o in ctx.get("observations", []) if o.get("agent") == "support")
        pending = ctx.get("pending", {})
        return _call(
            "human_review_brief",
            summary=f"Merchant asked: {ctx.get('message', '')} Findings: {findings or 'none recorded.'}"[:1200],
            question_for_operator=pending.get("question", ""),
            message_to_merchant="A human specialist is now reviewing your case. You will get the outcome in this conversation.",
        )

    def _critic(self, ctx: dict[str, Any]) -> LLMResponse:
        issues = [f"The number {n} is not supported by the evidence." for n in ctx.get("unsupported_numbers", [])]
        issues += [f"The URL {u} was not returned by any tool." for u in ctx.get("fabricated_urls", [])]
        if not ctx.get("draft", "").strip():
            issues.append("The draft is empty.")
        return _call(
            "review",
            verdict="revise" if issues else "approve",
            grounded=not issues,
            complete=bool(ctx.get("draft", "").strip()),
            issues=issues,
            needs_more_evidence="",
        )

    def _summarizer(self, ctx: dict[str, Any]) -> LLMResponse:
        asked = [m["content"][:140] for m in ctx.get("messages", []) if m["role"] == "user" and not m["content"].startswith("[")]
        merged = " ".join(filter(None, [ctx.get("summary", ""), "Earlier the merchant asked: " + " | ".join(asked) if asked else ""]))
        return LLMResponse(text=merged[-900:])
