"""Graph nodes: input guard, Router (supervisor), Knowledge, Support, Human Escalation, Critic, finalize.

Control flow is decided by the Router model at run time, one tool call per step, inside hard bounds:
a step budget, a duplicate-delegation check, one escalation per turn and a capped number of critic rounds.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langgraph.types import interrupt

from src.agents import prompts
from src.agents.checks import (
    LANGUAGE_NAMES,
    conversation_language,
    evidence_text,
    fabricated_urls,
    language_mismatch,
    unsupported_numbers,
    urls_in,
)
from src.agents.state import AgentState
from src.db.ops_store import ALLOWED_ACTIONS, OPEN_STATUSES
from src.llm.base import LLMResponse
from src.observability import Spans
from src.runtime import Runtime
from src.security.auth import Principal
from src.security.guardrails import (
    REFUSALS,
    check_input,
    check_output,
    neutralize_delimiters,
    sanitize_untrusted,
)
from src.tools.registry import KNOWLEDGE_TOOLS, SUPPORT_TOOLS, TOOLS, ToolContext, run_tool, tool_specs

logger = logging.getLogger(__name__)

MAX_TASK_CHARS = 600


def llm_step(rt: Runtime, spans: Spans, **kwargs: Any) -> LLMResponse:
    """One model call, timed and accounted (tokens, cost, degradation) in the trace and the metrics."""
    started = time.perf_counter()
    response = rt.llm.complete(**kwargs)
    role = kwargs["role"]
    spans.add(
        "llm",
        role=role,
        model=response.model or rt.llm.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        ms=int((time.perf_counter() - started) * 1000),
        tool_calls=[c.name for c in response.tool_calls],
        degraded=response.degraded,
    )
    rt.metrics.inc("llm_calls_total", role=role)
    rt.metrics.inc("llm_tokens_total", response.input_tokens, direction="input")
    rt.metrics.inc("llm_tokens_total", response.output_tokens, direction="output")
    if response.degraded:
        rt.metrics.inc("llm_degraded_calls_total", role=role)
    return response


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_memory(state: AgentState) -> str:
    parts: list[str] = []
    if state.get("summary"):
        parts.append(f"<conversation_summary>\n{state['summary']}\n</conversation_summary>")
    history = state.get("history") or []
    if history:
        lines = "\n".join(f"{m['role']}: {m['content']}" for m in history)
        parts.append(f"<conversation_history>\n{lines}\n</conversation_history>")
    return "\n".join(parts) if parts else "<conversation_history>\n(first message of this conversation)\n</conversation_history>"


def render_observations(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "<observations>\n(none yet)\n</observations>"
    body = "\n".join(f"[{i}] {_dump(o)}" for i, o in enumerate(observations, start=1))
    return f"<observations>\n{body}\n</observations>"


def _language(state: AgentState) -> str | None:
    return conversation_language(state["message"], state.get("history"))


def language_rule(language: str | None) -> str:
    """The reply language is detected in code and stated outright: evidence in Portuguese must not pull the answer there."""
    if not language:
        return "Reply language: the language of the merchant's message."
    name = LANGUAGE_NAMES[language]
    return (
        f"Reply language: {name}. The merchant wrote in {name}, so everything addressed to the merchant must be in {name}, "
        "whatever language the observations are in. Keep product names and codes as they are."
    )


def _events(state: AgentState, spans: Spans) -> list[dict[str, Any]]:
    return [*(state.get("events") or []), *spans.items]


def _caller(principal: Principal) -> str:
    if principal.is_merchant:
        return "authenticated merchant"
    return (
        "anonymous visitor (not signed in; account tools will refuse). If the message is about their own account, "
        "the answer must tell them to sign in to see it"
    )


class Nodes:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    # --- input guard ----------------------------------------------------------------------------------

    def guard(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("guard")
        principal = Principal.from_dict(state["principal"])
        with spans.timed("guardrail_input") as extra:
            verdict = check_input(state["message"], principal, self.rt.llm, self.rt.settings.guardrail_reasoning_effort)
            extra.update(verdict.as_dict())
        if not verdict.allowed:
            self.rt.metrics.inc("guardrail_blocks_total", category=verdict.category, layer=verdict.layer)
        return {"guard": verdict.as_dict(), "events": _events(state, spans)}

    # --- Router Agent ---------------------------------------------------------------------------------

    def supervisor(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("router")
        settings = self.rt.settings
        principal = Principal.from_dict(state["principal"])
        steps = state.get("steps", 0)
        observations = list(state.get("observations") or [])
        feedback = state.get("critic_feedback") or []
        force_finish = steps >= settings.max_supervisor_steps

        prompt_parts = [
            render_memory(state),
            f"Caller: {_caller(principal)}",
            f"<merchant_message>\n{neutralize_delimiters(state['message'])}\n</merchant_message>",
            render_observations(observations),
            language_rule(_language(state)),
        ]
        if feedback:
            prompt_parts.append(
                "<critic_feedback>\nYour previous draft was rejected:\n"
                + f"<draft_answer>\n{state.get('draft', '')}\n</draft_answer>\n"
                + "\n".join(f"- {issue}" for issue in feedback)
                + "\nFix every issue. Gather more evidence if the fix needs it; otherwise finish with a corrected answer.\n</critic_feedback>"
            )
        prompt_parts.append(
            f"Step {steps + 1} of at most {settings.max_supervisor_steps}."
            + (" The step budget is used up: call finish now with the best grounded answer you can give." if force_finish else "")
        )

        response = llm_step(
            self.rt,
            spans,
            role="supervisor",
            instructions=prompts.SUPERVISOR_INSTRUCTIONS,
            prompt="\n\n".join(prompt_parts),
            tools=prompts.SUPERVISOR_TOOLS,
            tool_choice="finish" if force_finish else "required",
            context={
                "message": state["message"],
                "history": state.get("history") or [],
                "authenticated": principal.is_merchant,
                "observations": observations,
                "critic_feedback": feedback,
                "draft": state.get("draft", ""),
                "force_finish": force_finish,
            },
        )
        update: dict[str, Any] = {"steps": steps + 1, "degraded": bool(state.get("degraded")) or response.degraded}
        call = response.tool_calls[0] if response.tool_calls else None
        args = call.arguments if call else {}
        name = call.name if call else "finish"

        def bounce(note: str) -> None:
            observations.append({"agent": "router", "note": note})
            update.update(next="supervisor", observations=observations)

        if name == "finish" or force_finish:
            answer = str(args.get("answer") or "").strip() if name == "finish" else ""
            answer = answer or (response.text.strip() if call is None else "") or prompts.LOW_CONFIDENCE_FALLBACK
            confidence = str(args.get("confidence") or "low") if name == "finish" else "low"
            if answer == prompts.LOW_CONFIDENCE_FALLBACK:
                confidence = "low"
                self.rt.metrics.inc("low_confidence_fallbacks_total")
            update.update(draft=answer, confidence=confidence, next="critic", plan=[])
            spans.add("decision", action="finish", step=steps + 1, forced=force_finish, confidence=confidence)
        else:
            plan = [str(p)[:200] for p in (args.get("remaining_plan") or [])][:6]
            update["plan"] = plan
            spans.add(
                "decision",
                action=name,
                step=steps + 1,
                thought=str(args.get("thought", ""))[:400],
                task=str(args.get("task") or args.get("question") or "")[:MAX_TASK_CHARS],
                remaining_plan=plan,
            )
            if name in ("delegate_knowledge", "delegate_support"):
                agent = "knowledge" if name == "delegate_knowledge" else "support"
                task = str(args.get("task") or "").strip()[:MAX_TASK_CHARS] or state["message"]
                if any(o.get("agent") == agent and o.get("task", "").casefold() == task.casefold() for o in observations):
                    bounce(f"Refused: you already delegated this exact task to the {agent} agent. Use that observation, change the task, or finish.")
                else:
                    update.update(next=agent, pending={"task": task})
            elif name == "escalate_to_human":
                if not principal.is_merchant:
                    bounce("Refused: a human-review ticket needs a signed-in merchant. Tell the caller to sign in or use the official support channels.")
                elif any(o.get("agent") == "escalation" for o in observations):
                    bounce("Refused: this turn was already escalated once. Use the operator's decision above and finish.")
                else:
                    update.update(
                        next="escalation",
                        pending={
                            "reason": str(args.get("reason") or "unresolved"),
                            "question": str(args.get("question") or "")[:MAX_TASK_CHARS],
                            "proposed_action": str(args.get("proposed_action") or "none"),
                        },
                    )
            else:
                bounce(f"Refused: unknown action '{name}'.")
        update["events"] = _events(state, spans)
        return update

    # --- specialists ----------------------------------------------------------------------------------

    def _run_specialist(
        self,
        spans: Spans,
        *,
        role: str,
        instructions: str,
        task: str,
        allowed: tuple[str, ...],
        report_tool: dict[str, Any],
        ctx: ToolContext,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        """Bounded tool loop: the model picks tools, reads the results, reconsiders, and finally reports."""
        max_steps = self.rt.settings.max_specialist_tool_steps
        tool_results: list[dict[str, Any]] = []
        seen: set[str] = set()
        repeated = False
        degraded = False
        for step in range(max_steps + 1):
            # A tool without parameters can only ever return the same thing, so it is offered once. When nothing
            # is left to call, or the model has just repeated itself, the only move left is to report.
            offered = tuple(n for n in allowed if TOOLS[n].properties or not any(s.startswith(f"{n}:") for s in seen))
            last = step == max_steps or repeated or not offered
            body = "\n".join(f"[{i}] {_dump(r)}" for i, r in enumerate(tool_results, start=1)) or "(no tool calls yet)"
            response = llm_step(
                self.rt,
                spans,
                role=role,
                instructions=instructions,
                prompt=(
                    f"Caller: {_caller(ctx.principal)}\n<task>\n{neutralize_delimiters(task)}\n</task>\n\n"
                    f"<observations>\n{body}\n</observations>\n\n"
                    + (
                        "No further tool calls are available: call report now."
                        if last
                        else f"Tool step {step + 1} of at most {max_steps}. Every result so far is in <observations>; "
                        "call a tool only for something they do not already contain, otherwise call report."
                    )
                ),
                tools=[report_tool] if last else [*tool_specs(offered), report_tool],
                tool_choice="report" if last else "required",
                context={"task": task, "tool_results": tool_results, "authenticated": ctx.principal.is_merchant, "last": last},
            )
            degraded = degraded or response.degraded
            if not response.tool_calls:
                return {"answer": response.text, "findings": response.text}, tool_results, degraded
            for call in response.tool_calls:
                if call.name == "report":
                    return dict(call.arguments), tool_results, degraded
                if last:
                    spans.add("tool", tool=call.name, arguments=call.arguments, ms=0, error="tool_budget_exhausted")
                    continue
                signature = f"{call.name}:{_dump(call.arguments)}"
                if signature in seen:
                    # not executed and not recorded as evidence: the first result is already in the observations
                    repeated = True
                    spans.add("tool", tool=call.name, arguments=call.arguments, ms=0, error="duplicate_call")
                    continue
                else:
                    seen.add(signature)
                    result = run_tool(ctx, call.name, call.arguments, allowed)
                spans.add("tool", tool=call.name, arguments=call.arguments, ms=result.pop("_ms", 0), error=result.get("error"))
                tool_results.append({"tool": call.name, "arguments": call.arguments, "result": result})
        return {}, tool_results, degraded

    def _ctx(self, state: AgentState) -> ToolContext:
        return ToolContext(self.rt, Principal.from_dict(state["principal"]), state.get("thread_key", ""), state.get("turn_id", ""))

    def knowledge(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("knowledge")
        task = state["pending"]["task"]
        report, tool_results, degraded = self._run_specialist(
            spans,
            role="knowledge",
            instructions=prompts.KNOWLEDGE_INSTRUCTIONS,
            task=task,
            allowed=KNOWLEDGE_TOOLS,
            report_tool=prompts.KNOWLEDGE_REPORT,
            ctx=self._ctx(state),
        )
        # Citation validity is enforced here, not requested in a prompt: only URLs a tool returned survive.
        known = {u.rstrip("/") for u in urls_in(_dump(tool_results))}
        claimed = [str(u) for u in (report.get("sources") or [])]
        sources = [u for u in claimed if u.rstrip("/") in known or u.startswith("internal://")]
        observation: dict[str, Any] = {
            "agent": "knowledge",
            "task": task,
            "report": {
                "answer": str(report.get("answer") or ""),
                "confidence": str(report.get("confidence") or "low"),
                "gaps": str(report.get("gaps") or ""),
                "sources": sources,
            },
            "evidence": tool_results,
        }
        dropped = [u for u in claimed if u not in sources]
        if dropped:
            observation["dropped_citations"] = dropped
            self.rt.metrics.inc("fabricated_citations_dropped_total", len(dropped))
        return {
            "observations": [*(state.get("observations") or []), observation],
            "degraded": bool(state.get("degraded")) or degraded,
            "events": _events(state, spans),
        }

    def support(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("support")
        task = state["pending"]["task"]
        report, tool_results, degraded = self._run_specialist(
            spans,
            role="support",
            instructions=prompts.SUPPORT_INSTRUCTIONS,
            task=task,
            allowed=SUPPORT_TOOLS,
            report_tool=prompts.SUPPORT_REPORT,
            ctx=self._ctx(state),
        )
        proposed = str(report.get("proposed_action") or "none")
        observation = {
            "agent": "support",
            "task": task,
            "report": {
                "findings": str(report.get("findings") or ""),
                "follow_up_for_knowledge": str(report.get("follow_up_for_knowledge") or ""),
                "needs_human_approval": bool(report.get("needs_human_approval")),
                "proposed_action": proposed if proposed in ALLOWED_ACTIONS else "none",
            },
            "evidence": tool_results,
        }
        return {
            "observations": [*(state.get("observations") or []), observation],
            "degraded": bool(state.get("degraded")) or degraded,
            "events": _events(state, spans),
        }

    # --- Human Escalation Agent -----------------------------------------------------------------------

    def escalation(self, state: AgentState) -> dict[str, Any]:
        """Write the brief and open the ticket. Kept separate from the interrupt so a resume never re-runs the model."""
        spans = Spans("escalation")
        settings = self.rt.settings
        principal = Principal.from_dict(state["principal"])
        pending = state["pending"]
        observations = state.get("observations") or []

        response = llm_step(
            self.rt,
            spans,
            role="escalation",
            instructions=prompts.ESCALATION_INSTRUCTIONS,
            prompt=(
                f"{render_memory(state)}\n\n<merchant_message>\n{neutralize_delimiters(state['message'])}\n</merchant_message>\n\n"
                f"{render_observations(observations)}\n\nReason for escalation: {pending['reason']}\n"
                f"Decision needed: {pending['question']}\nProposed action: {pending['proposed_action']}\n\n"
                f"{language_rule(_language(state))} (applies to message_to_merchant)"
            ),
            tools=[prompts.ESCALATION_BRIEF],
            tool_choice="human_review_brief",
            context={"message": state["message"], "pending": pending, "observations": observations},
        )
        brief = response.tool_calls[0].arguments if response.tool_calls else {}
        # A write action reaches the ticket only if the Support Agent derived it from account data this turn.
        # The Router cannot introduce one on its own, whatever the conversation told it to do.
        backed = {o["report"]["proposed_action"] for o in observations if o.get("agent") == "support"}
        proposed = pending["proposed_action"] if pending["proposed_action"] in ALLOWED_ACTIONS and pending["proposed_action"] in backed else None
        ticket = self.rt.ops.open_ticket(
            idempotency_key=f"{state['thread_key']}:{state['turn_id']}",
            thread_key=state["thread_key"],
            merchant_id=principal.user_id,
            reason=pending["reason"],
            question=str(brief.get("question_for_operator") or pending["question"])[:1000],
            context=str(brief.get("summary") or state["message"])[:2000],
            proposed_action=proposed,
            ttl_seconds=settings.hitl_timeout_seconds,
        )
        self.rt.metrics.inc("escalations_total", reason=pending["reason"])
        spans.add("ticket_opened", ticket_id=ticket["ticket_id"], reason=pending["reason"], proposed_action=proposed)
        interim = str(brief.get("message_to_merchant") or "").strip() or "A human specialist is now reviewing your case."
        # This text reaches the merchant while the turn is paused, so it gets the same output guard as a final answer.
        interim, verdict = check_output(interim, principal)
        if not verdict.allowed:
            interim = "A human specialist is now reviewing your case."
        spans.add("guardrail_output", **verdict.as_dict())
        if verdict.category != "safe":
            self.rt.metrics.inc("guardrail_output_interventions_total", category=verdict.category)
        return {
            "ticket_id": ticket["ticket_id"],
            "interim_message": f"{interim} (ticket {ticket['ticket_id']})",
            "degraded": bool(state.get("degraded")) or response.degraded,
            "events": _events(state, spans),
        }

    def human_review(self, state: AgentState) -> dict[str, Any]:
        """Pause until a human decides. On resume, the ticket row, not the resume payload, is the source of truth."""
        ticket_id = state["ticket_id"]
        interrupt({"ticket_id": ticket_id, "message": state.get("interim_message", "")})

        spans = Spans("escalation")
        principal = Principal.from_dict(state["principal"])
        ticket = self.rt.ops.get_ticket(ticket_id) or {}
        status = ticket.get("status", "UNKNOWN")
        operator_message, _ = sanitize_untrusted(str(ticket.get("operator_message") or ""))
        observation: dict[str, Any] = {
            "agent": "escalation",
            "ticket_id": ticket_id,
            "ticket_status": status,
            "decision": ticket.get("decision") or "none",
            "decided_by": "human operator" if ticket.get("resolved_by") else None,
            "operator_message": operator_message,
            "proposed_action": ticket.get("proposed_action"),
        }
        if status == "APPROVED" and ticket.get("proposed_action"):
            observation["action_result"] = self.rt.ops.execute_approved_action(ticket_id, principal.user_id or "")
        elif status == "TIMED_OUT":
            observation["note"] = "No operator answered within the review window. Nothing was executed. The ticket stays on record."
        elif status in OPEN_STATUSES:
            observation["note"] = "The ticket is still open; no decision was recorded. Nothing was executed."
        self.rt.metrics.inc("human_decisions_total", decision=str(observation["decision"]))
        spans.add("human_decision", ticket_id=ticket_id, status=status, executed=bool(observation.get("action_result", {}).get("executed")))
        return {"observations": [*(state.get("observations") or []), observation], "events": _events(state, spans)}

    # --- Critic ---------------------------------------------------------------------------------------

    def critic(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("critic")
        settings = self.rt.settings
        draft = state.get("draft", "")
        observations = state.get("observations") or []
        rounds = state.get("critic_rounds", 0)
        memory = render_memory(state)
        evidence = evidence_text(observations, state["message"], memory)
        suspicious_numbers = unsupported_numbers(draft, evidence)
        invented_urls = fabricated_urls(draft, observations, state["message"], memory)
        expected_language = _language(state)
        wrong_language = language_mismatch(draft, expected_language)

        response = llm_step(
            self.rt,
            spans,
            role="critic",
            instructions=prompts.CRITIC_INSTRUCTIONS,
            prompt=(
                f"{memory}\n\n<merchant_message>\n{neutralize_delimiters(state['message'])}\n</merchant_message>\n\n"
                f"{render_observations(observations)}\n\n<draft_answer>\n{draft}\n</draft_answer>\n\n"
                f"Automatic checks: numbers in the draft not found in the evidence: {suspicious_numbers or 'none'}; "
                f"URLs in the draft not returned by any tool: {invented_urls or 'none'}. "
                f"{language_rule(expected_language)}"
            ),
            tools=[prompts.CRITIC_REVIEW],
            tool_choice="review",
            context={
                "message": state["message"],
                "draft": draft,
                "observations": observations,
                "unsupported_numbers": suspicious_numbers,
                "fabricated_urls": invented_urls,
            },
        )
        args = response.tool_calls[0].arguments if response.tool_calls else {}
        if not response.tool_calls:
            # No review came back. Silence is not approval: fall back to what can be verified without a model.
            unverified = bool(suspicious_numbers or invented_urls or not draft.strip())
            args = {
                "verdict": "revise" if unverified else "approve",
                "grounded": not unverified,
                "issues": [f"The number {n} is not supported by the evidence." for n in suspicious_numbers],
            }
            self.rt.metrics.inc("critic_unavailable_total")
        review = {
            "round": rounds + 1,
            "verdict": "revise" if args.get("verdict") == "revise" else "approve",
            "grounded": bool(args.get("grounded", True)),
            "complete": bool(args.get("complete", True)),
            "issues": [str(i)[:400] for i in (args.get("issues") or [])][:6],
            "needs_more_evidence": str(args.get("needs_more_evidence") or "")[:400],
        }
        if invented_urls:  # hard rule: a citation no tool returned is never acceptable
            review["verdict"], review["grounded"] = "revise", False
            review["issues"].append(f"Remove these citations, no tool returned them: {', '.join(invented_urls)}")
        # hard rule, when a model wrote the draft: the offline policy is extractive and cannot translate
        if wrong_language and expected_language and not (response.degraded or state.get("degraded")) and self.rt.llm.name != "offline":
            review["verdict"] = "revise"
            review["issues"].append(
                f"Rewrite the whole answer in {LANGUAGE_NAMES[expected_language]}: the merchant wrote in "
                f"{LANGUAGE_NAMES[expected_language]} but the draft is in {LANGUAGE_NAMES[wrong_language]}. Keep the facts unchanged."
            )

        update: dict[str, Any] = {
            "reviews": [*(state.get("reviews") or []), review],
            "degraded": bool(state.get("degraded")) or response.degraded,
        }
        if review["verdict"] == "approve":
            update["next"] = "finalize"
        elif rounds < settings.max_critic_rounds:
            issues = list(review["issues"]) or ["The draft is not fully supported by the observations."]
            if review["needs_more_evidence"]:
                issues.append(f"Research needed before answering: {review['needs_more_evidence']}")
            update.update(next="supervisor", critic_feedback=issues, critic_rounds=rounds + 1)
            self.rt.metrics.inc("critic_revisions_total")
        else:
            # Quality gate held after every allowed revision: refuse to send an ungrounded answer.
            update["next"] = "finalize"
            if not review["grounded"]:
                update.update(draft=prompts.LOW_CONFIDENCE_FALLBACK, confidence="low")
                self.rt.metrics.inc("low_confidence_fallbacks_total")
        spans.add("review", **review, outcome=update["next"])
        update["events"] = _events(state, spans)
        return update

    # --- finalize: output guard + memory ----------------------------------------------------------------

    def finalize(self, state: AgentState) -> dict[str, Any]:
        spans = Spans("finalize")
        settings = self.rt.settings
        principal = Principal.from_dict(state["principal"])
        guard = state.get("guard") or {}
        blocked = guard.get("allowed") is False

        if blocked:
            answer, status = REFUSALS.get(guard.get("category", ""), REFUSALS["unsafe_output"]), "blocked"
            remembered_user = f"[message withheld from memory: blocked as {guard.get('category')}]"
        else:
            answer, verdict = check_output(state.get("draft") or prompts.LOW_CONFIDENCE_FALLBACK, principal)
            status = "completed"
            remembered_user = neutralize_delimiters(state["message"])[:1000]
            spans.add("guardrail_output", **verdict.as_dict())
            if verdict.category != "safe":
                self.rt.metrics.inc("guardrail_output_interventions_total", category=verdict.category)

        sources: list[str] = []
        for observation in state.get("observations") or []:
            if observation.get("agent") == "knowledge":
                for url in observation["report"]["sources"]:
                    if url not in sources:
                        sources.append(url)

        history = [
            *(state.get("history") or []),
            {"role": "user", "content": remembered_user},
            {"role": "assistant", "content": answer[:1500]},
        ]
        summary = state.get("summary", "")
        degraded = bool(state.get("degraded"))
        if len(history) > settings.history_compact_after:
            older, history = history[: -settings.history_keep_messages], history[-settings.history_keep_messages :]
            response = llm_step(
                self.rt,
                spans,
                role="summarizer",
                instructions=prompts.SUMMARIZER_INSTRUCTIONS,
                prompt=(
                    f"<conversation_summary>\n{summary or '(empty)'}\n</conversation_summary>\n\n<conversation_history>\n"
                    + "\n".join(f"{m['role']}: {m['content']}" for m in older)
                    + "\n</conversation_history>"
                ),
                context={"summary": summary, "messages": older},
            )
            summary = response.text.strip()[:1500] or summary
            degraded = degraded or response.degraded
            spans.add("memory_compacted", folded_messages=len(older), kept=len(history))
            self.rt.metrics.inc("memory_compactions_total")

        return {
            "answer": answer,
            "status": status,
            "sources": sources,
            "history": history,
            "summary": summary,
            "turn_count": state.get("turn_count", 0) + 1,
            "degraded": degraded,
            "events": _events(state, spans),
        }
