# 04: Customer Support Agent — Merchant Profile, Settlements & Deterministic Tools

**What to build:** Deliver end-to-end resolution of **Merchant**-specific account and **Settlement** **Inquiries** through `POST /chat` (`router_agent` → `customer_support_agent`). Seed a deterministic SQLite store with rich operational data for **Merchant** `cliente1988` (plus a secondary **Merchant** `cliente2026` to verify tenant isolation) and equip the **Customer Support Agent** with three tools strictly scoped to the authenticated `user_id`: `get_merchant_profile_and_settlements`, `get_pos_terminal_diagnostics`, and `create_support_ticket_or_escalate`.

**Blocked by:** 01: Walking Skeleton — POST /chat API, State Graph & Router Safety Policy Guardrail

**Status:** resolved

- [x] Official Scenario **#3** (*"When will the money from yesterday's sales be deposited?"* for `user_id: "cliente1988"`) routes through `["router_agent", "customer_support_agent"]`, calls `["get_merchant_profile_and_settlements"]`, and returns the exact **Settlement** schedule and amounts for `cliente1988`'s yesterday sales across Pix (`D+0`), debit (`D+1`), and credit (`D+2` via **Receivables Advance**).
- [x] All three **Customer Support Agent** tools (`get_merchant_profile_and_settlements`, `get_pos_terminal_diagnostics`, `create_support_ticket_or_escalate`) are implemented, callable, and strictly enforce tenant scoping by `user_id`.
- [x] Requests from an unknown `user_id` receive a graceful support message indicating no active **Merchant** profile was found rather than raising an unhandled exception.
