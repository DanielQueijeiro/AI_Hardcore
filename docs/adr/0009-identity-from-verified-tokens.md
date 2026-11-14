# 0009. Identity comes from a verified token; tools are scoped to the principal

Status: accepted (amends 0002; extended by [0014](0014-challenge-payload-and-deployment-mode.md))

The first version filtered queries by the `user_id` in the request body and blocked messages that named another merchant. Anyone could send another merchant's `user_id`. Tenant filtering is not authentication.

Now: `POST /auth/login` issues an HS256 JWT (scrypt password hashes, uniform failures, rate limit, revocation by `jti`). A request without a token is an anonymous principal with access to public knowledge only (any `user_id` in the body is ignored; see 0014). When a token is present, a body `user_id` that disagrees with the token is rejected with 403. A bad token is 401, never a silent downgrade.

The challenge contract `{message, user_id}` is kept: it works without a token for everything that is public, and account questions answer that sign-in is required. Making `/chat` trust `user_id` for the sake of a one-line curl would reintroduce the vulnerability the review identified.

Tools have no merchant parameter. Account tools read the merchant from the principal the API verified, and the tool layer drops and records any identity-like argument a model supplies. Conversation threads, traces and tickets are keyed by the verified identity. This is what makes prompt injection unable to cross tenants regardless of what the model does.

Demo users are seeded so the scenarios can be run; `SEED_DEMO_USERS=false` turns that off. A real deployment would validate tokens from the company IdP instead of issuing its own.
