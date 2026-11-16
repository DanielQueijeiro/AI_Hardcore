"""Structured logs, in-process metrics (Prometheus text format) and per-turn trace spans."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)


LATENCY_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 20, 45, 90)


class Metrics:
    """Counters and one latency histogram. Per-process; scrape each replica."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._buckets: dict[float, int] = dict.fromkeys(LATENCY_BUCKETS, 0)
        self._latency_sum = 0.0
        self._latency_count = 0

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[(name, tuple(sorted(labels.items())))] += value

    def observe_latency(self, seconds: float) -> None:
        with self._lock:
            self._latency_sum += seconds
            self._latency_count += 1
            for bound in LATENCY_BUCKETS:
                if seconds <= bound:
                    self._buckets[bound] += 1

    def value(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._counters.get((name, tuple(sorted(labels.items()))), 0.0)

    def set_gauge(self, name: str, value: float, **labels: str) -> None:
        """A point-in-time value (tickets waiting, a breaker's state), refreshed just before each scrape."""
        with self._lock:
            self._gauges[(name, tuple(sorted(labels.items())))] = value

    @staticmethod
    def _series(kind: str, values: dict[tuple[str, tuple[tuple[str, str], ...]], float]) -> list[str]:
        lines: list[str] = []
        typed: set[str] = set()
        for (name, labels), value in sorted(values.items()):
            if name not in typed:
                lines.append(f"# TYPE {name} {kind}")
                typed.add(name)
            label_text = ",".join(f'{k}="{v}"' for k, v in labels)
            lines.append(f"{name}{{{label_text}}} {value:g}" if label_text else f"{name} {value:g}")
        return lines

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            lines += self._series("counter", self._counters)
            lines += self._series("gauge", self._gauges)
            lines.append("# TYPE chat_turn_seconds histogram")
            for bound in LATENCY_BUCKETS:
                lines.append(f'chat_turn_seconds_bucket{{le="{bound:g}"}} {self._buckets[bound]}')
            lines.append(f'chat_turn_seconds_bucket{{le="+Inf"}} {self._latency_count}')
            lines.append(f"chat_turn_seconds_sum {self._latency_sum:.4f}")
            lines.append(f"chat_turn_seconds_count {self._latency_count}")
        return "\n".join(lines) + "\n"


class Spans:
    """Collects the spans one graph node produces; the node returns them into state['events']."""

    def __init__(self, node: str) -> None:
        self.node = node
        self.items: list[dict[str, Any]] = []

    def add(self, kind: str, **fields: Any) -> None:
        self.items.append({"node": self.node, "kind": kind, **fields})

    @contextmanager
    def timed(self, kind: str, **fields: Any):
        started = time.perf_counter()
        extra: dict[str, Any] = {}
        try:
            yield extra
        finally:
            self.add(kind, ms=int((time.perf_counter() - started) * 1000), **fields, **extra)
