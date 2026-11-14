# 0014. The challenge payload stays; identity does not come from it; demo credentials are fenced

Status: accepted (extends [0009](0009-identity-from-verified-tokens.md))

The challenge defines the request as `{"message", "user_id"}` and three of its ten example scenarios (deposit date, card machine offline, transaction declined) need the merchant's own data. The review of the first submission asked the question that follows from that: if anyone can send `user_id="cliente2026"`, where is the proof that they are that merchant?

There is none in a request body, so the body never grants access. `/chat` accepts the payload unchanged; without a bearer token the caller is anonymous and gets public knowledge plus an explicit "sign in to see your account"; with a token, `user_id` must agree with it or the request is refused. The alternative, a compatibility switch that trusts the body, would make the three scenarios work for an unauthenticated `curl` and would reintroduce exactly the hole the review found, one environment variable away from production. It was rejected.

The cost is one extra step for whoever runs the scenarios. `python -m scripts.run_scenarios` removes it: it logs in as the demo merchant and sends the ten payloads as the challenge lists them (`--approve` also plays the operator for the declined-transaction scenario; `--anonymous` shows what an unauthenticated caller gets).

Demo identities exist so those scenarios can authenticate, and they share a published password, including an operator who can approve write actions. `APP_ENV` fences them: `demo` (default, what `docker compose up` gives an evaluator) seeds them and logs a warning; `production` refuses to start while `SEED_DEMO_USERS` is true or `JWT_SECRET` is missing or short.

Anonymous conversations are a related edge. Signed-in threads are namespaced by the verified user; anonymous ones share a namespace, so the conversation id is the only separation between two visitors. An anonymous caller can therefore only continue a conversation under the unguessable id the server issued; any other id starts a fresh one.
