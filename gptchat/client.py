"""Chat completion client with streaming and a non-streaming fallback."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
    Stream,
)

from .config import Settings, redact_secrets

STREAM_FALLBACK_NOTICE = (
    "Streaming is unavailable on this endpoint. "
    "Further replies will arrive all at once."
)


class ResponseError(Exception):
    """The endpoint returned an error payload or an unreadable body."""


class StreamingUnsupported(Exception):
    """Streaming failed before any assistant text was produced."""


class ChatClient:
    """Talk to one OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        settings: Settings,
        *,
        streaming: bool = True,
        sdk: OpenAI | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.base_url = settings.base_url
        self.model = settings.model
        self.streaming = streaming
        self._pending_notice = False
        if sdk is not None:
            self._sdk = sdk
            return
        kwargs: dict[str, Any] = {
            "api_key": settings.api_key,
            "base_url": settings.base_url,
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if max_retries is not None:
            kwargs["max_retries"] = max_retries
        self._sdk = OpenAI(**kwargs)

    def consume_stream_notice(self) -> bool:
        """Return True once after this client switches streaming off."""

        if not self._pending_notice:
            return False
        self._pending_notice = False
        return True

    def disable_streaming(self) -> None:
        if not self.streaming:
            return
        self.streaming = False
        self._pending_notice = True

    def iter_text(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        """Yield assistant text for ``messages``.

        Streaming is attempted first. If the endpoint rejects the stream, or
        answers with a normal JSON completion, the client switches to a single
        response for this turn and the rest of the session.
        """

        payload = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]
        if self.streaming:
            produced = False
            try:
                for piece in self._iter_stream(payload):
                    produced = True
                    yield piece
                return
            except StreamingUnsupported:
                if produced:
                    raise
                self.disable_streaming()
        text = self._complete(payload)
        if text:
            yield text

    def _iter_stream(self, messages: list[dict[str, str]]) -> Iterator[str]:
        yielded = False
        try:
            manager = self._sdk.chat.completions.with_streaming_response.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                stream=True,
            )
            with manager as response:
                for piece in self._read_stream_response(response):
                    yielded = True
                    yield piece
        except StreamingUnsupported:
            # Already classified. The generic handler below would wrap it again.
            raise
        except Exception as exc:
            if yielded or not _is_unsupported_stream_error(exc):
                raise
            raise StreamingUnsupported(str(exc)) from exc

    def _read_stream_response(self, response: Any) -> Iterator[str]:
        kind = _media_kind(response.headers.get("content-type", ""))
        if kind == "json":
            data = _read_json(response)
            self._raise_if_payload_error(data)
            self.disable_streaming()
            text = text_from_payload(data)
            if text:
                yield text
            return

        parsed = response.parse()
        if not isinstance(parsed, Stream):
            self.disable_streaming()
            text = text_from_completion(parsed)
            if text:
                yield text
            return

        saw_chunk = False
        for chunk in parsed:
            saw_chunk = True
            text = text_from_chunk(chunk)
            if text:
                yield text
        if not saw_chunk:
            raise StreamingUnsupported(
                "The endpoint returned no streaming events."
            )

    def _complete(self, messages: list[dict[str, str]]) -> str:
        # Omit ``stream`` so endpoints that reject the field can still answer.
        completion = self._sdk.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
        )
        return text_from_completion(completion)

    def _raise_if_payload_error(self, data: Any) -> None:
        if not isinstance(data, dict) or "choices" in data:
            if data is None:
                raise StreamingUnsupported(
                    "The endpoint returned a JSON body that could not be read."
                )
            return
        message = _payload_message(data)
        if message is None:
            return
        if "stream" in message.lower():
            raise StreamingUnsupported(message)
        raise ResponseError(message)


def format_error(exc: BaseException, *, base_url: str) -> str:
    """Return a short, secret-free explanation of a failed request."""

    detail = _detail(exc)
    if isinstance(exc, AuthenticationError):
        return f"Authentication failed. {detail}"
    if isinstance(exc, PermissionDeniedError):
        return f"The API refused this request. {detail}"
    if isinstance(exc, RateLimitError):
        return f"The API rate limit was reached. {detail}"
    if isinstance(exc, APITimeoutError):
        return f"The request to {base_url} timed out."
    if isinstance(exc, APIConnectionError):
        return (
            f"Could not connect to {base_url}. "
            "Check OPENAI_BASE_URL and your network."
        )
    if isinstance(exc, APIStatusError):
        return f"The API returned HTTP {exc.status_code}. {detail}".strip()
    if isinstance(exc, ResponseError):
        return detail
    if isinstance(exc, APIError):
        return f"The request failed. {detail}"
    return f"The request failed. {detail}"


def text_from_chunk(chunk: object) -> str:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    return _coerce_text(getattr(delta, "content", None))


def text_from_completion(completion: object) -> str:
    if isinstance(completion, str):
        raise ResponseError("The endpoint returned a non-JSON response.")
    choices = getattr(completion, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = _coerce_text(getattr(message, "content", None))
    if content:
        return content
    refusal = getattr(message, "refusal", None)
    return refusal if isinstance(refusal, str) else ""


def text_from_payload(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = _coerce_text(message.get("content"))
        if content:
            return content
        refusal = message.get("refusal")
        return refusal if isinstance(refusal, str) else ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        return _coerce_text(delta.get("content"))
    return ""


def _coerce_text(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


def _media_kind(content_type: str) -> str:
    lowered = content_type.lower()
    if "event-stream" in lowered:
        return "sse"
    if "json" in lowered:
        return "json"
    return "unknown"


def _read_json(response: Any) -> Any:
    try:
        return response.json()
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def _payload_message(data: dict[str, Any]) -> str | None:
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        return message.strip() if isinstance(message, str) and message.strip() else None
    if isinstance(error, str) and error.strip():
        return error.strip()
    return None


def _is_unsupported_stream_error(exc: BaseException) -> bool:
    if isinstance(exc, StreamingUnsupported):
        return True
    if isinstance(
        exc,
        (
            AuthenticationError,
            PermissionDeniedError,
            RateLimitError,
            APIConnectionError,
            APITimeoutError,
        ),
    ):
        return False
    text = _detail(exc).lower()
    if isinstance(exc, json.JSONDecodeError):
        return True
    if isinstance(exc, APIStatusError):
        if exc.status_code in {405, 415, 501}:
            return True
        if exc.status_code in {400, 404, 422} and "stream" in text:
            return True
        return False
    if isinstance(exc, APIError):
        return any(token in text for token in ("stream", "event-stream", "server-sent"))
    return False


def _detail(exc: BaseException) -> str:
    message = getattr(exc, "message", None)
    text = message if isinstance(message, str) and message else str(exc)
    text = " ".join(text.split())
    text = redact_secrets(text)
    if len(text) > 500:
        return text[:500] + "…"
    return text
