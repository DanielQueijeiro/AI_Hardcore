# 0007. One LLM port, an OpenAI Responses adapter, and an offline policy as the degradation path

Status: accepted (supersedes 0004)

Every agent calls `LLMClient.complete(role, instructions, prompt, tools, tool_choice, effort, context)`. There are three implementations: `OpenAIResponsesClient` (function tools, reasoning effort per role, real token usage), `OfflinePolicyLLM` (deterministic rules that answer with the same typed calls) and `ScriptedLLM` (tests). `ResilientLLM` wraps the provider with a circuit breaker and falls back to the offline policy, flagging the response `degraded`.

The first version had five providers behind a factory and defaulted to heuristics, so the "agents" mostly never called a model. Now the model path is the product and the offline policy has three narrow jobs: CI without network or cost, a demo without a key, and staying up when the provider is down. It is documented as a rule policy and its evaluation report says so.

The prompt is re-rendered as text each step (history, observations) rather than threaded as provider-specific message objects. That keeps the port provider-neutral and makes every prompt visible in a test, at the cost of resending context; history compaction and the step budgets bound that cost.

`context` duplicates the prompt's content in structured form so non-model implementations do not parse prose. Models never see it.
