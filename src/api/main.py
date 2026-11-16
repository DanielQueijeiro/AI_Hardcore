"""HTTP layer. Parses input, establishes identity, calls the conversation service, maps the result."""

from __future__ import annotations

import hmac
import json
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.agents.graph import open_checkpointer
from src.agents.service import ChatService, ConversationError
from src.config import Settings, get_settings
from src.llm import LLMClient
from src.observability import configure_logging
from src.rag import Retriever
from src.runtime import Runtime, build_runtime
from src.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    FeedbackRequest,
    HealthResponse,
    LoginRequest,
    Orchestration,
    ReadyResponse,
    TicketDecision,
    TicketResolution,
    TicketResponse,
    TokenResponse,
    Usage,
)
from src.security.auth import (
    ANONYMOUS,
    AuthError,
    Principal,
    SlidingWindowRateLimiter,
    client_ip,
    issue_token,
    token_claims,
    verify_password,
)
from src.tools.live import LiveData

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    retriever: Retriever | None = None,
    live: LiveData | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        if settings.app_env == "production" and settings.unsafe_for_production():
            raise RuntimeError("refusing to start with APP_ENV=production: " + "; ".join(settings.unsafe_for_production()))
        if settings.seed_demo_users:
            logger.warning("demo_users_enabled", extra={"detail": "demo identities share a published password; use APP_ENV=production outside a demo"})
        if not settings.jwt_secret:
            logger.warning("jwt_secret_unset", extra={"detail": "using a per-process secret; tokens will not survive a restart"})
        runtime = build_runtime(settings, llm=llm, retriever=retriever, live=live)
        if runtime.llm.name == "offline":
            logger.warning(
                "offline_policy_active",
                extra={"detail": "no model is configured (OPENAI_API_KEY unset or LLM_PROVIDER=offline): a deterministic "
                "rule policy answers instead of the agents' model. Set OPENAI_API_KEY to run the model-driven orchestration."},
            )
        checkpointer = open_checkpointer(settings.checkpoint_db_path)
        service = ChatService(runtime, checkpointer)
        app.state.runtime, app.state.service = runtime, service
        app.state.login_limiter = SlidingWindowRateLimiter(
            settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
        )
        app.state.chat_limiter = SlidingWindowRateLimiter(
            settings.chat_rate_limit_attempts, settings.chat_rate_limit_window_seconds
        )

        stop = threading.Event()

        def sweep() -> None:  # resumes conversations whose human review timed out
            while not stop.wait(settings.hitl_sweep_interval_seconds):
                try:
                    service.sweep_timeouts()
                except Exception:  # noqa: BLE001
                    logger.exception("timeout_sweep_failed")

        sweeper = threading.Thread(target=sweep, name="hitl-timeout-sweeper", daemon=True)
        sweeper.start()
        try:
            yield
        finally:
            stop.set()
            sweeper.join(timeout=2)
            checkpointer.conn.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Multi-agent merchant support: Router, Knowledge, Customer Support and Human Escalation agents.",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )

    # --- dependencies -----------------------------------------------------------------------------------

    trusted_proxies = settings.trusted_proxy_set()

    def caller_address(request: Request) -> str:
        return client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"), trusted_proxies)

    def rt(request: Request) -> Runtime:
        return request.app.state.runtime

    def svc(request: Request) -> ChatService:
        return request.app.state.service

    def current_principal(
        request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
    ) -> Principal:
        """Identity comes from a verified, unrevoked token and nowhere else. No token means anonymous."""
        if credentials is None:
            return ANONYMOUS
        try:
            claims = token_claims(settings, credentials.credentials)
        except AuthError as exc:
            raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc
        if claims["role"] not in ("merchant", "operator") or rt(request).ops.is_revoked(str(claims["jti"])):
            raise HTTPException(401, "invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
        request.state.claims = claims
        return Principal(user_id=str(claims["sub"]), role=str(claims["role"]))

    def operator(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.is_operator:
            raise HTTPException(403, "operator role required")
        return principal

    # --- health -----------------------------------------------------------------------------------------

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health() -> HealthResponse:
        """Liveness: the process is up. Does not touch dependencies."""
        return HealthResponse(service=settings.app_name, version=settings.app_version)

    @app.get("/ready", response_model=ReadyResponse, tags=["ops"])
    def ready(request: Request, response: Response) -> ReadyResponse:
        """Readiness: the stores answer, migrations are applied and the knowledge index is loaded."""
        runtime = rt(request)
        checks: dict[str, Any] = {}
        try:
            checks["database"] = runtime.ops.ping()
            checks["schema_version"] = runtime.ops.schema_version()
        except Exception as exc:  # noqa: BLE001
            checks["database"] = False
            checks["database_error"] = type(exc).__name__
        checks["knowledge_chunks"] = len(runtime.retriever.chunks)
        checks["llm_provider"] = runtime.llm.name
        checks["llm_model"] = runtime.llm.model
        checks["llm_circuit_open"] = bool(getattr(runtime.llm, "breaker_open", False))
        ok = bool(checks["database"]) and checks["knowledge_chunks"] > 0
        if not ok:
            response.status_code = 503
        return ReadyResponse(status="ready" if ok else "not_ready", checks=checks)

    @app.get("/metrics", response_class=PlainTextResponse, tags=["ops"])
    def metrics(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
        """Prometheus scrape. With METRICS_TOKEN set (required in production) the scraper must present it."""
        if settings.metrics_token and (
            credentials is None or not hmac.compare_digest(credentials.credentials.encode(), settings.metrics_token.encode())
        ):
            raise HTTPException(401, "metrics token required", headers={"WWW-Authenticate": "Bearer"})
        runtime = rt(request)
        runtime.metrics.set_gauge("human_review_tickets_open", len(runtime.ops.list_tickets("open")))
        runtime.metrics.set_gauge("llm_circuit_open", float(bool(getattr(runtime.llm, "breaker_open", False))))
        return runtime.metrics.render()

    # --- auth -------------------------------------------------------------------------------------------

    @app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
    def login(body: LoginRequest, request: Request) -> TokenResponse:
        limiter: SlidingWindowRateLimiter = request.app.state.login_limiter
        key = f"{caller_address(request)}:{body.user_id}"
        if not limiter.allow(key):
            raise HTTPException(429, "too many login attempts", headers={"Retry-After": str(settings.login_rate_limit_window_seconds)})
        user = rt(request).ops.get_user(body.user_id)
        # same error for unknown user and wrong password, and the hash is checked either way
        stored = user["password_hash"] if user else "scrypt$00$00"
        if not verify_password(body.password, stored) or user is None:
            rt(request).metrics.inc("login_failures_total")
            raise HTTPException(401, "invalid credentials")
        limiter.reset(key)
        token, expires_in = issue_token(settings, user["user_id"], user["role"])
        return TokenResponse(access_token=token, expires_in=expires_in, user_id=user["user_id"], role=user["role"])

    @app.post("/auth/logout", status_code=204, tags=["auth"])
    def logout(request: Request, principal: Principal = Depends(current_principal)) -> Response:
        if principal.user_id is None:
            raise HTTPException(401, "not signed in")
        claims = request.state.claims
        rt(request).ops.revoke_token(str(claims["jti"]), int(claims["exp"]))
        return Response(status_code=204)

    @app.get("/auth/me", tags=["auth"])
    def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
        return {**principal.as_dict(), "authenticated": principal.user_id is not None}

    # --- chat -------------------------------------------------------------------------------------------

    def admit(body: ChatRequest, request: Request, principal: Principal) -> None:
        """Checks every chat request passes before any agent runs: auth policy, identity agreement, rate limit."""
        if settings.require_chat_auth and principal.user_id is None:
            raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
        if principal.user_id is not None and body.user_id and body.user_id != principal.user_id:
            rt(request).metrics.inc("identity_mismatch_rejected_total")
            raise HTTPException(403, "user_id does not match the authenticated user")
        limiter: SlidingWindowRateLimiter = request.app.state.chat_limiter
        limiter_key = principal.user_id or caller_address(request)
        if not limiter.allow(limiter_key):
            rt(request).metrics.inc("chat_rate_limited_total")
            raise HTTPException(
                429,
                "too many chat requests",
                headers={"Retry-After": str(settings.chat_rate_limit_window_seconds)},
            )

    def chat(body: ChatRequest, request: Request, principal: Principal = Depends(current_principal)) -> ChatResponse:
        admit(body, request, principal)
        try:
            result = svc(request).handle_message(principal, body.message, body.conversation_id)
        except ConversationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return chat_response(result, body, principal, request)

    def chat_response(result: dict[str, Any], body: ChatRequest, principal: Principal, request: Request) -> ChatResponse:
        return ChatResponse(
            user_id=principal.user_id,
            authenticated=principal.user_id is not None,
            conversation_id=result["conversation_id"],
            message=body.message,
            answer=result["answer"],
            status=result["status"],
            orchestration=Orchestration(
                trace_id=result["trace_id"],
                agents=result["agents"],
                tools_called=result["tools"],
                sources=result["sources"],
                plan_steps=result["plan_steps"],
                critic_rounds=result["critic_rounds"],
                guardrail=result["guard"],
                escalated_to_human=result["ticket_id"] is not None,
                ticket_id=result["ticket_id"],
                usage=Usage(**result["usage"]),
                latency_ms=result["latency_ms"],
                llm_provider=rt(request).llm.name,
                degraded=result["degraded"],
            ),
        )

    app.post("/chat", response_model=ChatResponse, tags=["chat"], summary="Send a message (challenge contract)")(chat)
    app.post("/api/v1/chat", response_model=ChatResponse, tags=["chat"], summary="Send a message (versioned alias)")(chat)

    @app.post(
        "/chat/stream",
        tags=["chat"],
        summary="Send a message and follow the turn as server-sent events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}},
    )
    def chat_stream(body: ChatRequest, request: Request, principal: Principal = Depends(current_principal)) -> StreamingResponse:
        """Same request and checks as /chat. Events: `accepted`, then one `step` per routing decision, tool call,
        review and human-review event as it happens, then `result` (the /chat response body) or `error`."""
        admit(body, request, principal)
        try:
            events = svc(request).stream_message(principal, body.message, body.conversation_id)
        except ConversationError as exc:
            raise HTTPException(422, str(exc)) from exc

        def sse() -> Iterator[str]:
            for event in events:
                if event["type"] == "result":
                    data = chat_response(event["result"], body, principal, request).model_dump_json()
                else:
                    data = json.dumps(event, ensure_ascii=False, default=str)
                yield f"event: {event['type']}\ndata: {data}\n\n"

        return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/conversations/{conversation_id}", response_model=ConversationResponse, tags=["chat"])
    def conversation(
        conversation_id: str,
        request: Request,
        wait: float = Query(0.0, ge=0.0, description="While the conversation waits on a human, hold the request up to this many seconds for the decision."),
        principal: Principal = Depends(current_principal),
    ) -> ConversationResponse:
        """Stored memory of one of the caller's own conversations, including whether it is waiting on a human."""
        if settings.require_chat_auth and principal.user_id is None:
            raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})
        try:
            view = svc(request).conversation(principal, conversation_id, wait_seconds=min(wait, settings.max_conversation_wait_seconds))
        except ConversationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return ConversationResponse(**view)

    @app.get("/traces/{trace_id}", tags=["ops"])
    def trace(trace_id: str, request: Request, principal: Principal = Depends(current_principal)) -> dict[str, Any]:
        """Full trace of a turn: every model call, tool call, router decision and critic review."""
        payload = rt(request).ops.get_trace(trace_id)
        if payload is None or not (principal.is_operator or (principal.user_id and payload.get("user_id") == principal.user_id)):
            raise HTTPException(404, "trace not found")
        return payload

    @app.post("/feedback", status_code=204, tags=["chat"])
    def feedback(body: FeedbackRequest, request: Request, principal: Principal = Depends(current_principal)) -> Response:
        payload = rt(request).ops.get_trace(body.trace_id)
        if principal.user_id is None or payload is None or payload.get("user_id") != principal.user_id:
            raise HTTPException(404, "trace not found")
        rt(request).ops.save_feedback(body.trace_id, principal.user_id, body.rating, body.comment)
        rt(request).metrics.inc("user_feedback_total", rating=str(body.rating))
        return Response(status_code=204)

    # --- human operators ----------------------------------------------------------------------------------

    @app.get("/operator/tickets", response_model=list[TicketResponse], tags=["operator"])
    def list_tickets(request: Request, status: str | None = "open", _: Principal = Depends(operator)) -> list[TicketResponse]:
        return [TicketResponse(**t) for t in rt(request).ops.list_tickets(status)]

    @app.get("/operator/tickets/{ticket_id}", response_model=TicketResponse, tags=["operator"])
    def get_ticket(ticket_id: str, request: Request, _: Principal = Depends(operator)) -> TicketResponse:
        ticket = rt(request).ops.get_ticket(ticket_id)
        if ticket is None:
            raise HTTPException(404, "ticket not found")
        return TicketResponse(**ticket)

    @app.post("/operator/tickets/{ticket_id}/claim", response_model=TicketResponse, tags=["operator"])
    def claim_ticket(ticket_id: str, request: Request, principal: Principal = Depends(operator)) -> TicketResponse:
        """Take the ticket under a time-limited lease so two operators cannot decide the same case."""
        try:
            return TicketResponse(**rt(request).ops.claim_ticket(ticket_id, principal.user_id or "", settings.hitl_lease_seconds))
        except KeyError as exc:
            raise HTTPException(404, "ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/operator/tickets/{ticket_id}/respond", response_model=TicketResolution, tags=["operator"])
    def respond_ticket(
        ticket_id: str,
        body: TicketDecision,
        request: Request,
        response: Response,
        wait: bool = Query(True, description="true: resume the conversation now and return the agent's answer. false: record the decision, return 202 and resume in the background."),
        principal: Principal = Depends(operator),
    ) -> TicketResolution:
        """Record the human decision and resume the paused conversation with it."""
        runtime = rt(request)
        try:
            ticket = runtime.ops.resolve_ticket(ticket_id, principal.user_id or "", body.decision, body.message)
        except KeyError as exc:
            raise HTTPException(404, "ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not wait:
            # The decision is durable; the merchant's conversation picks it up on the worker (or, failing that, the sweep).
            svc(request).resume_in_background(ticket["thread_key"])
            response.status_code = 202
            return TicketResolution(ticket=TicketResponse(**ticket), conversation_resumed=False, resume="scheduled")
        result = svc(request).resume(ticket["thread_key"])
        return TicketResolution(
            ticket=TicketResponse(**(runtime.ops.get_ticket(ticket_id) or ticket)),
            conversation_resumed=result is not None,
            agent_answer=result["answer"] if result else None,
            trace_id=result["trace_id"] if result else None,
            resume="completed" if result is not None else "not_needed",
        )

    return app


app = create_app()
