# 0011. Human in the loop: interrupt, leased tickets, code-gated writes

Status: accepted

The first version created a ticket and ended the flow. No human ever answered and the agent never continued.

Flow now: the Escalation Agent writes a brief and opens a ticket; the next node calls `interrupt`, which checkpoints the turn and returns `awaiting_human` to the caller. An operator lists the queue, claims the ticket (a time-limited lease, so two operators cannot decide the same case), and responds with approve, reject or answer. The API then resumes the same graph thread; the decision arrives as an observation and the Router writes the final answer. Unanswered tickets expire: a sweeper marks them timed out and resumes the conversation with that fact, and the same check runs lazily when the merchant writes again.

Decisions that keep this safe:
- The brief/ticket step and the interrupt are separate nodes, because a resumed node re-executes from its start. The ticket key is `(thread, turn)`, so even a re-run cannot open a second ticket.
- On resume the node reads the ticket row. The resume payload is not trusted, so nothing that can call resume can forge an approval.
- The write action is executed by `OpsStore.execute_approved_action` only for an APPROVED ticket of that merchant with an allow-listed action, once. The model has no tool that performs it.
- A proposed action reaches a ticket only if the Support Agent derived it from account data in the same turn; the Router cannot introduce one.
- The operator's note is sanitized as untrusted text before any model reads it.

Considered: blocking the HTTP request until a human answers (the benchmark's synchronous consult). Rejected because human response time is minutes, and a paused, durable turn survives restarts and client disconnects.
