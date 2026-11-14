# 0006. Model-driven Router loop with bounded autonomy and a Critic

Status: accepted (supersedes 0001 and 0005)

The first version routed with state flags: `Router -> Support -> Knowledge -> END`. It was predictable and easy to test, and it could not reconsider anything: a poor retrieval, an unexpected telemetry code or a compound question all followed the same fixed path. The review scored that as a state machine, correctly.

The Router is now a loop driven by the model. Each step it makes exactly one typed function call (`delegate_knowledge`, `delegate_support`, `escalate_to_human`, `finish`) after reading every observation so far, and each delegation carries its reasoning and remaining plan. Specialists run their own tool loops and return a typed report plus raw tool results. A Critic reviews the draft against the evidence and can send it back, in which case the Router may gather more evidence before rewriting.

Autonomy is bounded in code, not in prompts: a Router step budget after which the call is forced to `finish`, refusal of duplicate delegations, a specialist tool budget, one escalation per turn, a cap on critic rounds after which an ungrounded draft is replaced by an explicit "could not verify" answer, and the graph recursion limit. These are the answer to the original objection to agent loops (unbounded latency and cost).

Consequences: several model calls per turn instead of one or two (a simple product question is Router, Knowledge x2, Router, Critic). Latency and cost are higher and are reported per turn. Behaviour is no longer asserted by exact agent sequence; tests script the model to assert each loop behaviour, and quality is measured by the evaluation harness instead.

Considered and rejected: a separate Planner agent that emits a full plan up front (plans written before any observation go stale, and the Router re-planning each step already covers it); peer-to-peer handoffs between specialists (harder to bound and to trace than a hub).
