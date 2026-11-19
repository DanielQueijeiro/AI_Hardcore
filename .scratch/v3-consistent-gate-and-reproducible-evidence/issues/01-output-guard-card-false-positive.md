# 01: Output guard: phone numbers are not card numbers

**What to build:** The card-number redaction in `redact_personal_identifiers`
([src/security/guardrails.py](../../../src/security/guardrails.py)) treats any 13-19 digit run that passes Luhn as
a card. In the 2026-11-16 run (s21, run 2) it rewrote the official WhatsApp number +55 11 97694-6815 as
"[redacted card number]". Roughly one in ten digit strings passes Luhn, so phone numbers will keep tripping it.

**Blocked by:** none

**Status:** resolved

- [x] A digit run written as a phone number (leading `+`, or the country/area-code layout `55 11 97694-6815`) is never redacted as a card.
- [x] A Luhn-valid run whose length its issuer prefix does not allow is not a card (13 digits are only Visa, 14 Diners, 15 Amex; every scheme starts with 2-6). This alone clears the unformatted `5511976946815`.
- [x] A real PAN (Visa, Mastercard, Amex 4-6-5, Hipercard, 13-digit Visa) is still redacted.
- [x] Tests cover the s21 number in three layouts and four test PANs (`tests/test_hardening.py`).

## Comments

Dropped an early idea: "a number that appears verbatim in the turn's evidence is not redacted". Trusting tool
output would let an account tool's data through the one check that exists for it; the issuer/length and phone
rules fix s21 without widening anything.
