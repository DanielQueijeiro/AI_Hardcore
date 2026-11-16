# 0018. Progress is streamed; a human decision is resumed off the operator's request

Status: accepted (amends [0011](0011-human-in-the-loop-with-leased-tickets.md))

A turn is several sequential model calls: about 12 s at the median and 26 s at p95 in the 2026-11-16 model report. Two places made that wait worse than it had to be.

- The merchant saw nothing until the whole turn was done. `POST /chat/stream` takes the same body and the same admission checks as `/chat` and emits server-sent events as the turn runs: `accepted`, one `step` per routing decision, tool call, review and human-review event, then `result`, which is the `/chat` body. It does not make the turn shorter. The final answer is not streamed token by token: it is the argument of the Router's `finish` call, and the Critic reviews the whole draft before anything is sent, so streaming tokens would show text that might never be sent. Model reasoning and tool results are left out of the stream; they stay in the trace, which is access-controlled. The turn runs on its own thread and finishes even if the client disconnects, so a dropped connection never leaves a conversation between checkpoints.
- The operator's `respond` request waited for the resumed turn. With `respond?wait=false` the decision is recorded (that is the durable part), the call returns `202` with `resume: scheduled`, and the conversation resumes on a worker thread; if that fails, the existing sweep (H11) resumes it. The default stays `wait=true`, which returns the agent's answer to the operator and is what the evaluation harness uses. The merchant learns the outcome through a long-poll, `GET /conversations/{id}?wait=`, which returns as soon as the conversation is no longer waiting, capped by `MAX_CONVERSATION_WAIT_SECONDS`.

A consequence: a conversation can now be read while a turn is running on it. Reading it then reports `in_progress` (the reader tried the thread's lock and did not get it) instead of whatever state lies between two checkpoints. The long-poll waits on that lock rather than polling it.

Not done: a push channel (webhook, WebSocket) for merchants or operators, and parallelising the input classifier with the first Router step, which is the change that would actually cut latency.
