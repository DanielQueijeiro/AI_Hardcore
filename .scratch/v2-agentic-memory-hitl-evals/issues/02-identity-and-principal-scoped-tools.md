# 02: Token identity and principal-scoped tools

**What to build:** Issue and verify JWTs; derive the principal only from the token; make account tools read the merchant from the principal and drop identity arguments supplied by a model.

**Blocked by:** none

**Status:** resolved

- [x] The challenge payload without a token gets public knowledge and no account data.
- [x] A body `user_id` that disagrees with the token is rejected with 403; bad tokens are 401.
- [x] A scripted model that passes `merchant_id=cliente2026` still receives the caller's own data, and the attempt is recorded.
- [x] Login failures are uniform and rate-limited; logout revokes the token.
