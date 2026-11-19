# Getnet Multi-Agent Support Context

Domain language for supporting Getnet merchants with payment products, point-of-sale troubleshooting, settlements and general questions. Code, prompts, schemas and tests use these terms.

## Actors

**Merchant**:
A business registered with Getnet that accepts payments and receives settlements. Identified by a verified token, never by a value in a request body.
_Avoid_: Client, user, customer, account holder

**Operator**:
A human support specialist who claims and decides human-review tickets.
_Avoid_: Agent (reserved for software agents), admin, L2

**Principal**:
The authenticated caller of a request: a Merchant, an Operator, or anonymous. Every tool call runs on behalf of exactly one Principal.
_Avoid_: User id, session, tenant

## Products

**POS Terminal**:
A physical card machine (Get Clássica, Get Smart) used by a Merchant.
_Avoid_: Card reader, device (maquininha only when quoting the product name)

**Settlement**:
The scheduled payout of net funds from a Merchant's sales into their registered account.
_Avoid_: Deposit, transfer

**Receivables Advance**:
Antecipação de recebíveis: receiving funds from credit sales before the standard Settlement date.
_Avoid_: Loan, cash advance

**Crediário**:
A Getnet modality that lets a buyer split a purchase into up to 48 installments financed by the card issuer, while the Merchant is paid in a single Settlement.
_Avoid_: Standard installments, parcelado lojista, BNPL

**Payment Link**:
Link de Pagamento: a checkout link a Merchant shares over WhatsApp or social networks to be paid without a POS Terminal.
_Avoid_: Checkout page, invoice link

**Transaction Decline**:
A rejected payment attempt, identified by an issuer or terminal code.
_Avoid_: Failed payment, chargeback

## Conversation

**Inquiry**:
One message from a Merchant.
_Avoid_: Prompt, request

**Conversation**:
An ordered series of Turns between one Principal and the system, addressed by a conversation id and remembered across requests.
_Avoid_: Session, chat, thread (thread is the storage term)

**Turn**:
The handling of one Inquiry from guard to final answer. A Turn can pause for Human Review and resume later.
_Avoid_: Request, run

**Memory**:
What a Conversation keeps between Turns: recent messages verbatim and a rolling summary of older ones.
_Avoid_: Context, state (state is the per-Turn working data)

## Orchestration

**Router Agent**:
The agent that owns a Turn: it plans, delegates, reads Observations, re-plans and writes the answer.
_Avoid_: Orchestrator, dispatcher, classifier

**Delegation**:
A self-contained task the Router Agent hands to a specialist agent.
_Avoid_: Handoff (reserved for humans), routing

**Observation**:
What came back from a Delegation or a human decision: a typed report plus the raw tool results it rests on.
_Avoid_: Result, context

**Evidence**:
The raw tool results inside the Observations of a Turn. An answer is grounded when every claim is supported by Evidence.
_Avoid_: Sources (a source is the origin URL of a piece of Evidence)

**Critic**:
The reviewer that checks a draft answer against the Evidence before it is sent.
_Avoid_: Validator, judge (the Judge grades offline, in evaluation)

**Bounded autonomy**:
The hard limits on what the agents may do in one Turn: step budgets, refused repeats, capped review rounds.
_Avoid_: Guardrails (those concern content safety)

## Governance

**Guardrail**:
A check on content: the input screen, the handling of untrusted data, the output leak check.
_Avoid_: Filter, moderation

**Untrusted data**:
Text the system did not write and the Merchant did not send: retrieved passages, web results, operator notes. It informs answers and never changes instructions.
_Avoid_: Context, documents

**Human Review**:
A pause in a Turn during which an Operator decides something the agents may not decide alone.
_Avoid_: Escalation (the act of requesting it), fallback

**Ticket**:
The record of one Human Review: brief, proposed action, lease, decision.
_Avoid_: Case, issue

**Lease**:
An Operator's time-limited exclusive hold on a Ticket.
_Avoid_: Lock, assignment

**Approved Action**:
A change to a Merchant's account that code executes once, only for a Ticket an Operator approved.
_Avoid_: Tool call, operation

## Evaluation

**Semantic pass**:
A golden answer that carries every required fact, makes no forbidden claim, states only numbers found in the Evidence, cites only URLs a tool returned, ends in the expected status, and passes the judge.
_Avoid_: Accuracy, success rate

**Sealed split**:
Golden items written after the last prompt change and run with nothing changed in between. It stops being sealed the moment something is changed because of it.
_Avoid_: Test set, held-out (unqualified)

**Adjudication**:
A human review of one failed answer, tied to that exact answer, naming who was wrong: the agent, the judge, the fact patterns or the harness. It explains a failure; the gate never reads it.
_Avoid_: Override, correction

**Cassette**:
A compressed recording (`.json.gz`) of every non-deterministic exchange in a model evaluation (agent/Critic/judge completions, live tool outputs, hosted embeddings) plus its frozen date and settings, allowing anyone to replay the full evaluation offline without an API key and verify exact reproduction (`eval.compare`).
_Avoid_: Mock, stub, fixture

**Evidence checklist**:
Deterministic items extracted in code from a Turn's raw Evidence (human decisions, numbered procedure steps, unambiguous product prices) that the Critic must rule on individually (`in_draft`, `not_applicable`, or `must_add`).
_Avoid_: Prompt hint, heuristic list
