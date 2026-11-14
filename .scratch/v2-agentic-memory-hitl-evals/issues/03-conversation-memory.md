# 03: Conversation memory in the checkpointer

**What to build:** Persist history and a rolling summary per (identity, conversation) in the SQLite checkpointer.

**Blocked by:** 01

**Status:** resolved

- [x] A second request sees the first one's content in the Router prompt.
- [x] A pronoun follow-up is resolved against the earlier turn.
- [x] A new process on the same database continues the conversation.
- [x] History beyond the threshold is folded into the summary.
- [x] Conversations are isolated by identity; blocked messages are not stored verbatim.
