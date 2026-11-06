"""Local stand-in for an OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class MockOpenAIServer(ThreadingHTTPServer):
    """Serve ``/v1/chat/completions`` on an ephemeral localhost port.

    Modes:
    - ``sse``: honor ``stream: true`` with server-sent events.
    - ``json``: always return one JSON completion, even when streaming is requested.
    - ``reject-stream``: reject ``stream: true`` with HTTP 400, and accept a normal request.
    - ``unauthorized``: reject every request with HTTP 401.
    - ``fail-once``: fail the first request with HTTP 400, then behave like ``sse``.
    """

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, mode: str = "sse") -> None:
        self.mode = mode
        self.requests: list[dict[str, Any]] = []
        self._failures_remaining = 1 if mode == "fail-once" else 0
        super().__init__(("127.0.0.1", 0), _Handler)
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.serve_forever,
            name="mock-openai",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def __enter__(self) -> MockOpenAIServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class _Handler(BaseHTTPRequestHandler):
    server: MockOpenAIServer
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "invalid json"}})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": {"message": "expected an object"}})
            return
        self.server.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        self._dispatch(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _dispatch(self, body: dict[str, Any]) -> None:
        if self.server.mode == "unauthorized":
            self._send_json(
                401,
                {"error": {"message": "invalid api key", "type": "invalid_request_error"}},
            )
            return
        if self.server._failures_remaining > 0:
            self.server._failures_remaining -= 1
            self._send_json(
                400,
                {"error": {"message": "model not found", "type": "invalid_request_error"}},
            )
            return
        stream = bool(body.get("stream"))
        if stream and self.server.mode == "reject-stream":
            self._send_json(
                400,
                {
                    "error": {
                        "message": "stream is not supported by this endpoint",
                        "type": "invalid_request_error",
                    }
                },
            )
            return
        text = _reply_for(body)
        model = str(body.get("model") or "gpt-4o-mini")
        if stream and self.server.mode != "json":
            self._send_bytes(200, _sse(text, model), "text/event-stream; charset=utf-8")
            return
        self._send_json(200, _completion(text, model))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send_bytes(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def _reply_for(body: dict[str, Any]) -> str:
    last_user = ""
    messages = body.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "user":
                last_user = str(message.get("content") or "")
    return f"echo:{last_user}"


def _completion(text: str, model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def _sse(text: str, model: str) -> bytes:
    midpoint = max(1, len(text) // 2) if text else 0
    parts = [text[:midpoint], text[midpoint:]] if text else []
    events: list[str] = []
    for index, part in enumerate(parts):
        delta: dict[str, str] = {"content": part}
        if index == 0:
            delta["role"] = "assistant"
        payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        events.append(f"data: {json.dumps(payload)}\n\n")
    stop = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    events.append(f"data: {json.dumps(stop)}\n\n")
    events.append("data: [DONE]\n\n")
    return "".join(events).encode("utf-8")
