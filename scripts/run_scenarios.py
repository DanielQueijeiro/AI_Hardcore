"""Run the ten official challenge scenarios against a running API, signed in as the demo merchant.

    python -m scripts.run_scenarios                      # http://localhost:8000, user cliente1988
    python -m scripts.run_scenarios --approve            # also plays the human operator for scenario 8
    python -m scripts.run_scenarios --anonymous          # same payloads with no token: account data stays locked
    python -m scripts.run_scenarios --only 3 5 8         # a subset

The challenge payload is `{"message": ..., "user_id": ...}`. This service keeps that payload, but `user_id`
in a request body proves nothing about who is calling, so account data (scenarios 3, 5 and 8) is only read
for a caller who presents a token from `/auth/login`. This script does that login first; the payloads are
otherwise sent exactly as the challenge lists them.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

import httpx

SCENARIOS = [
    "What's the difference between the Get Clássica and the Get Smart?",
    "What's the weather forecast in Porto Alegre tomorrow?",
    "When will the money from yesterday's sales be deposited?",
    "Do I need a bank account to receive my sales via Pix?",
    "My card machine won't connect to the internet, what should I do?",
    "How does receivables advance (antecipação) work with Getnet?",
    "What's the euro exchange rate today?",
    "My card machine is showing a transaction decline error.",
    "How many installments can I split a sale into with the crediário?",
    "Can I sell through WhatsApp using the Payment Link?",
]


def login(client: httpx.Client, user: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"user_id": user, "password": password})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def show(label: str, text: str) -> None:
    print(f"   {label}:")
    for line in text.splitlines() or [""]:
        print(textwrap.fill(line, width=110, initial_indent="     ", subsequent_indent="     ") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--user", default="cliente1988")
    parser.add_argument("--password", default="getnet-demo", help="demo password (DEMO_PASSWORD)")
    parser.add_argument("--operator", default="operador1")
    parser.add_argument("--anonymous", action="store_true", help="send the payloads without a token")
    parser.add_argument("--approve", action="store_true", help="act as the operator and approve any human review")
    parser.add_argument("--only", type=int, nargs="*", help="scenario numbers (1-10)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        ready = client.get("/ready").json()
        print(f"API {args.base_url}: {ready['status']} | model: {ready['checks'].get('llm_provider')}/{ready['checks'].get('llm_model')}")
        headers = {} if args.anonymous else login(client, args.user, args.password)
        print(f"Caller: {'anonymous (no token)' if args.anonymous else args.user + ' (bearer token)'}\n")
        failures = 0
        for number, message in enumerate(SCENARIOS, start=1):
            if args.only and number not in args.only:
                continue
            response = client.post(
                "/chat",
                json={"message": message, "user_id": args.user, "conversation_id": f"scenario-{number}"},
                headers=headers,
            )
            print(f"{number:>2}. {message}")
            if response.status_code != 200:
                failures += 1
                print(f"   HTTP {response.status_code}: {response.text[:300]}\n")
                continue
            body = response.json()
            run = body["orchestration"]
            print(
                f"   status={body['status']} | agents={' > '.join(run['agents'])} | tools={', '.join(run['tools_called']) or '-'} | "
                f"steps={run['plan_steps']} critic={run['critic_rounds']} | {run['latency_ms']} ms | trace={run['trace_id']}"
            )
            show("answer", body["answer"])
            if body["status"] == "awaiting_human" and args.approve and not args.anonymous:
                operator = login(client, args.operator, args.password)
                ticket_id = run["ticket_id"]
                client.post(f"/operator/tickets/{ticket_id}/claim", headers=operator).raise_for_status()
                decision = client.post(
                    f"/operator/tickets/{ticket_id}/respond",
                    json={"decision": "approve", "message": "Approved. Remote re-key scheduled for today."},
                    headers=operator,
                )
                decision.raise_for_status()
                print(f"   operator {args.operator} claimed and approved {ticket_id}; the paused turn resumed")
                show("answer after the human decision", decision.json()["agent_answer"] or "")
            print()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
