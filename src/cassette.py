"""Record a model evaluation once, replay it anywhere without an API key.

Everything non-deterministic that a model run depends on goes through a cassette: model calls (agents, guardrail
classifier, Critic, judge), live tools (FX, weather, web search) and hosted embeddings. Recording wraps the real
clients; replaying swaps them for ones that answer from the file and refuse anything that was not recorded.

- Keys are a hash of the request *content* (role, instructions, prompt, tools, tool choice, effort), never of call
  order, because parallel branches make call order non-deterministic. Identifiers the system mints at run time
  (ticket and service-order ids, trace ids, timestamps) are normalized out of the key.
- The same request can get different answers (a `--repeat 3` run sends identical prompts three times), so each key
  holds a FIFO list and replay hands the answers back in the order they were recorded.
- Prompts carry today's date, so the recording stores its date and replay freezes the clock to it (src/clock.py).
- A request with no recording raises CassetteMiss naming the role: a changed prompt never silently falls back.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import struct
import threading
from collections import deque
from pathlib import Path
from typing import Any

from src import clock
from src.llm.base import LLMClient, LLMResponse, ToolCall
from src.tools.live import LiveData

FORMAT = 2  # 2: first recorded vector per text wins, canary normalized
_VOLATILE = (
    (re.compile(r"\bTKT-\d{6}-[0-9A-F]{6}\b"), "TKT-ID"),
    (re.compile(r"\bSO-[0-9A-F]{8}\b"), "SO-ID"),
    (re.compile(r"\btrc-[0-9a-f]{16}\b"), "TRACE-ID"),
    (re.compile(r"\bCANARY-[0-9a-f]{12}\b"), "CANARY"),  # the prompt-leak canary is random per process
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"), "TIMESTAMP"),
)


class CassetteMiss(RuntimeError):
    """Replay was asked for something the recording does not contain."""


def normalize(text: str) -> str:
    for pattern, placeholder in _VOLATILE:
        text = pattern.sub(placeholder, text)
    return text


def request_key(kind: str, payload: dict[str, Any]) -> str:
    raw = normalize(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))
    return hashlib.sha256(f"{kind}\n{raw}".encode()).hexdigest()[:32]


class Cassette:
    def __init__(self, path: Path, mode: str, meta: dict[str, Any] | None = None) -> None:
        if mode not in ("record", "replay"):
            raise ValueError(mode)
        self.path, self.mode = Path(path), mode
        self._lock = threading.Lock()
        self.meta: dict[str, Any] = dict(meta or {})
        self._calls: dict[str, deque[Any]] = {}
        self.embeddings: dict[str, str] = {}
        if mode == "replay":
            data = json.loads(gzip.decompress(self.path.read_bytes()).decode("utf-8"))
            if data.get("format") != FORMAT:
                raise ValueError(f"{self.path}: cassette format {data.get('format')} is not {FORMAT}")
            self.meta = data["meta"]
            self._calls = {k: deque(v) for k, v in data["calls"].items()}
            self.embeddings = data["embeddings"]
        else:
            self.meta.setdefault("recorded_on", clock.today().isoformat())

    # --- calls (FIFO per key) ---

    def put(self, kind: str, payload: dict[str, Any], response: Any) -> None:
        key = request_key(kind, payload)
        frozen = json.loads(json.dumps(response, default=str))  # callers may mutate what they got back
        with self._lock:
            self._calls.setdefault(key, deque()).append(frozen)

    def take(self, kind: str, payload: dict[str, Any], label: str) -> Any:
        key = request_key(kind, payload)
        with self._lock:
            queue = self._calls.get(key)
            if not queue:
                raise CassetteMiss(f"no recorded {kind} for {label} (key {key}): the request differs from the recording")
            return json.loads(json.dumps(queue.popleft()))

    def unused(self) -> int:
        with self._lock:
            return sum(len(q) for q in self._calls.values())

    # --- embeddings (deterministic per text) ---

    def put_vector(self, model: str, text: str, vector: list[float]) -> None:
        key = request_key("embedding", {"model": model, "text": text})
        packed = base64.b64encode(struct.pack(f"<{len(vector)}f", *vector)).decode("ascii")  # float32; recording reads it back too
        with self._lock:
            self.embeddings.setdefault(key, packed)

    def vector_or_none(self, model: str, text: str) -> list[float] | None:
        try:
            return self.vector(model, text)
        except CassetteMiss:
            return None

    def vector(self, model: str, text: str) -> list[float]:
        key = request_key("embedding", {"model": model, "text": text})
        packed = self.embeddings.get(key)
        if packed is None:
            raise CassetteMiss(f"no recorded embedding for a text of {len(text)} characters (model {model})")
        raw = base64.b64decode(packed)
        return list(struct.unpack(f"<{len(raw) // 4}f", raw))

    def save(self) -> None:
        with self._lock:
            data = {"format": FORMAT, "meta": self.meta, "calls": {k: list(v) for k, v in sorted(self._calls.items())}, "embeddings": dict(sorted(self.embeddings.items()))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"), mtime=0))


_OPEN: dict[tuple[str, str], Cassette] = {}
_OPEN_LOCK = threading.Lock()


def open_cassette(path: Path | str, mode: str) -> Cassette:
    """One shared cassette per file and mode in a process: every app instance of an evaluation writes to the same one."""
    key = (str(Path(path).resolve()), mode)
    with _OPEN_LOCK:
        if key not in _OPEN:
            _OPEN[key] = Cassette(Path(path), mode)
        return _OPEN[key]


def close_cassettes() -> None:
    with _OPEN_LOCK:
        for cassette in _OPEN.values():
            if cassette.mode == "record":
                cassette.save()
        _OPEN.clear()


# --- model calls ---------------------------------------------------------------------------------


def _llm_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: kwargs.get(k) for k in ("role", "instructions", "prompt", "tools", "tool_choice", "effort")}


def _dump_response(response: LLMResponse) -> dict[str, Any]:
    return {
        "text": response.text,
        "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in response.tool_calls],
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "model": response.model,
        "degraded": response.degraded,
    }


def _load_response(data: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        text=data["text"],
        tool_calls=[ToolCall(**c) for c in data["tool_calls"]],
        input_tokens=data["input_tokens"],
        output_tokens=data["output_tokens"],
        model=data["model"],
        degraded=data["degraded"],
    )


class RecordingLLM:
    def __init__(self, inner: LLMClient, cassette: Cassette, slot: str = "app") -> None:
        self.inner, self.cassette, self.slot = inner, cassette, slot
        self.name, self.model = inner.name, inner.model
        cassette.meta.setdefault("models", {})[slot] = inner.model
        cassette.meta.setdefault("names", {})[slot] = inner.name  # code paths that branch on the client name replay the same way

    def complete(self, **kwargs: Any) -> LLMResponse:
        response = self.inner.complete(**kwargs)
        self.cassette.put(f"llm:{self.slot}", _llm_payload(kwargs), _dump_response(response))
        return response

    def __getattr__(self, item: str) -> Any:  # breaker state and the like stay visible
        return getattr(self.inner, item)


class ReplayLLM:
    def __init__(self, cassette: Cassette, slot: str = "app") -> None:
        self.cassette, self.slot = cassette, slot
        self.model = cassette.meta.get("models", {}).get(slot, "replay")
        self.name = cassette.meta.get("names", {}).get(slot, "replay")

    def complete(self, **kwargs: Any) -> LLMResponse:
        return _load_response(self.cassette.take(f"llm:{self.slot}", _llm_payload(kwargs), f"role {kwargs.get('role')}"))


# --- embeddings -----------------------------------------------------------------------------------


class RecordingEmbedder:
    def __init__(self, inner: Any, cassette: Cassette) -> None:
        self.inner, self.cassette, self.name = inner, cassette, inner.name
        cassette.meta["embedding_model"] = inner.name

    def embed(self, texts: list[str]) -> list[list[float]]:
        """The first vector recorded for a text is the one every later call gets.

        The embeddings API is not bit-for-bit deterministic: the same text embedded by two app instances of one run
        came back with slightly different vectors, and a replay serving one of them changed retrieval scores in the
        fourth decimal. Pinning the first one makes the recorded run consistent with itself and with its replay.
        """
        known = {t: self.cassette.vector_or_none(self.name, t) for t in texts}
        missing = [t for t in dict.fromkeys(texts) if known[t] is None]
        if missing:
            for text, vector in zip(missing, self.inner.embed(missing), strict=True):
                self.cassette.put_vector(self.name, text, vector)
                known[text] = self.cassette.vector(self.name, text)
        return [known[t] for t in texts]  # type: ignore[misc]


class ReplayEmbedder:
    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette
        self.name = cassette.meta.get("embedding_model", "replay")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.cassette.vector(self.name, t) for t in texts]


# --- live tools -----------------------------------------------------------------------------------


class RecordingLive(LiveData):
    def __init__(self, cassette: Cassette, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cassette = cassette

    def fx_rate(self, base: str, quote: str) -> dict[str, Any]:
        out = super().fx_rate(base, quote)
        self.cassette.put("live", {"fx": [base, quote]}, out)
        return out

    def weather(self, city: str, days: int = 3) -> dict[str, Any]:
        out = super().weather(city, days)
        self.cassette.put("live", {"weather": [city, days]}, out)
        return out

    def web_search(self, query: str, max_results: int = 4) -> dict[str, Any]:
        out = super().web_search(query, max_results)
        self.cassette.put("live", {"web": [query, max_results]}, out)
        return out


class ReplayLive(LiveData):
    def __init__(self, cassette: Cassette, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cassette = cassette

    def fx_rate(self, base: str, quote: str) -> dict[str, Any]:
        return self.cassette.take("live", {"fx": [base, quote]}, f"fx {base}/{quote}")

    def weather(self, city: str, days: int = 3) -> dict[str, Any]:
        return self.cassette.take("live", {"weather": [city, days]}, f"weather {city}")

    def web_search(self, query: str, max_results: int = 4) -> dict[str, Any]:
        return self.cassette.take("live", {"web": [query, max_results]}, "web search")
