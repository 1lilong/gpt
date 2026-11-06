"""In-memory conversation and slash commands."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Protocol

from .config import ConfigError, normalize_model


class ChatBackend(Protocol):
    """The slice of the API client the session needs."""

    model: str
    base_url: str

    def iter_text(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        """Yield assistant text for the current message list."""

    def consume_stream_notice(self) -> bool:
        """Return True once after streaming is turned off."""


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class UserCommand:
    name: str
    argument: str


@dataclass(frozen=True)
class CommandOutcome:
    message: str = ""
    exit_chat: bool = False


HELP_TEXT = """
Commands
  /help              Show this help
  /reset             Clear conversation history
  /model <name>      Show or change the model
  /system <text>     Show or set the system prompt
  /system --clear    Remove the system prompt
  /exit, /quit       Leave the chat

Start a line with // to send it as a message. //reset sends the text /reset.
Ctrl+C stops the reply in progress. Ctrl+D exits (Ctrl+Z on Windows).
""".strip()


def parse_input(line: str) -> UserMessage | UserCommand | None:
    """Classify one input line as a message, a command, or a blank to ignore."""

    text = line.strip()
    if not text:
        return None
    if text.startswith("//"):
        message = text[1:].strip()
        if not message:
            return None
        return UserMessage(message)
    if not text.startswith("/"):
        return UserMessage(text)
    body = text[1:].strip()
    if not body:
        return UserCommand("help", "")
    name, _, argument = body.partition(" ")
    return UserCommand(name.lower(), argument.strip())


class ChatSession:
    """One terminal session. History lives only in this process."""

    def __init__(self, client: ChatBackend, system: str | None = None) -> None:
        self.client = client
        self.system: str | None = None
        self.history: list[dict[str, str]] = []
        if system and system.strip():
            self.set_system(system)

    def set_system(self, text: str | None) -> None:
        cleaned = (text or "").strip()
        self.system = cleaned or None
        self.history = [message for message in self.history if message["role"] != "system"]
        if self.system is not None:
            self.history.insert(0, {"role": "system", "content": self.system})

    def reset(self) -> None:
        self.history = []
        if self.system is not None:
            self.history.append({"role": "system", "content": self.system})

    def handle_command(self, name: str, argument: str) -> CommandOutcome:
        if name in {"help", "?"}:
            return CommandOutcome(HELP_TEXT)
        if name in {"exit", "quit"}:
            return CommandOutcome(exit_chat=True)
        if name == "reset":
            self.reset()
            return CommandOutcome("Conversation cleared.")
        if name == "model":
            return self._set_model(argument)
        if name == "system":
            return self._set_system_command(argument)
        shown = f"/{name}"
        return CommandOutcome(f"Unknown command '{shown}'. Type /help for commands.")

    def ask(self, user_text: str) -> Iterator[str]:
        """Send one user turn and yield the assistant reply.

        A failure before any text drops the user turn so the next message can
        retry cleanly. Text already received is kept, including a reply stopped
        with Ctrl+C.
        """

        cleaned = user_text.strip()
        if not cleaned:
            return
        self.history.append({"role": "user", "content": cleaned})
        parts: list[str] = []
        finished = False

        def finish() -> None:
            nonlocal finished
            if finished:
                return
            finished = True
            content = "".join(parts)
            if content:
                self.history.append({"role": "assistant", "content": content})
                return
            if self.history and self.history[-1]["role"] == "user":
                self.history.pop()

        try:
            for piece in self.client.iter_text(self.history):
                parts.append(piece)
                yield piece
        except BaseException:
            finish()
            raise
        else:
            finish()

    def _set_model(self, argument: str) -> CommandOutcome:
        if not argument:
            return CommandOutcome(f"Current model: {self.client.model}")
        try:
            self.client.model = normalize_model(argument)
        except ConfigError as exc:
            return CommandOutcome(str(exc))
        return CommandOutcome(f"Model set to {self.client.model}.")

    def _set_system_command(self, argument: str) -> CommandOutcome:
        if argument == "--clear":
            self.set_system(None)
            return CommandOutcome("System prompt cleared.")
        if not argument:
            if self.system:
                return CommandOutcome(f"System prompt:\n{self.system}")
            return CommandOutcome("No system prompt is set.")
        self.set_system(argument)
        return CommandOutcome("System prompt updated.")
