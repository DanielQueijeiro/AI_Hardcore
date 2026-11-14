# 0010. Conversation memory lives in the LangGraph checkpointer

Status: accepted

Each `(verified identity, conversation_id)` is a LangGraph thread checkpointed to SQLite after every node. Two fields are durable across turns: `history` (recent messages verbatim) and `summary` (older turns folded by a summarizer call once history exceeds a threshold). All other state belongs to the turn in flight and is reset by `new_turn`.

Why the checkpointer rather than a messages table: the same mechanism has to persist a turn that is paused mid-graph for human review, so one store gives multi-turn memory, restart recovery and resumable interrupts together.

Specialists do not receive the conversation. The Router resolves references from memory and writes self-contained tasks, which keeps specialist prompts small and keeps untrusted history away from the agents that hold tools.

A message blocked by the input guard is stored as a placeholder so it cannot poison later turns. History is rendered inside tagged blocks and treated as data.

One turn runs at a time per thread (in-process lock). Multiple replicas require the Postgres checkpointer and a distributed lock; that is a deployment change, not an agent change.
