"""Interactive terminal loop."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator, Mapping
from typing import TextIO

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from . import __version__
from .client import STREAM_FALLBACK_NOTICE, ChatClient, format_error
from .config import DEFAULT_BASE_URL, DEFAULT_MODEL, ConfigError, Settings, load_settings
from .session import ChatSession, UserCommand, UserMessage, parse_input


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    console: Console | None = None,
) -> int:
    """Run the chat loop. Returns a process exit code."""

    args = _parser().parse_args(argv)
    output = console if console is not None else Console(highlight=False)
    error_console = output if console is not None else Console(stderr=True, highlight=False)
    try:
        settings = load_settings(
            model=args.model,
            base_url=args.base_url,
            environ=environ,
        )
    except ConfigError as exc:
        error_console.print(Text(str(exc), style="bold red"))
        return 1

    stream: TextIO = stdin if stdin is not None else sys.stdin
    try:
        if stream is sys.stdin and stream.isatty():
            _configure_stdio()
            _enable_line_editing()
        client = ChatClient(settings, streaming=not args.no_stream)
        session = ChatSession(client, system=args.system)
        return _chat_loop(
            output,
            session,
            stream,
            settings,
            system=args.system,
        )
    except KeyboardInterrupt:
        output.print()
        _farewell(output)
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gptchat",
        description="Chat with an OpenAI-compatible model in the terminal.",
        epilog=(
            "Set OPENAI_API_KEY in the environment, then run python -m gptchat "
            "from the project directory."
        ),
    )
    parser.add_argument(
        "--model",
        help=f"Model id. Overrides OPENAI_MODEL (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--base-url",
        help=(
            "API base URL. Overrides OPENAI_BASE_URL "
            f"(default: {DEFAULT_BASE_URL})."
        ),
    )
    parser.add_argument("--system", help="System prompt for this session.")
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Request each reply as one response instead of a stream.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gptchat {__version__}",
    )
    return parser


def _chat_loop(
    console: Console,
    session: ChatSession,
    stdin: TextIO,
    settings: Settings,
    *,
    system: str | None,
) -> int:
    _print_banner(console, settings, system=system, streaming=session.client.streaming)
    while True:
        try:
            line = _read_line(console, stdin)
        except EOFError:
            console.print()
            _farewell(console)
            return 0
        except KeyboardInterrupt:
            console.print()
            _farewell(console)
            return 0

        action = parse_input(line)
        if action is None:
            continue
        if isinstance(action, UserCommand):
            outcome = session.handle_command(action.name, action.argument)
            if outcome.message:
                style = None if action.name in {"help", "?", ""} else "cyan"
                console.print(Text(outcome.message, style=style))
                console.print()
            if outcome.exit_chat:
                _farewell(console)
                return 0
            continue
        if isinstance(action, UserMessage):
            _deliver_reply(console, session, action.text)
    return 0


def _deliver_reply(console: Console, session: ChatSession, user_text: str) -> None:
    generator = session.ask(user_text)
    printed = False
    try:
        try:
            first = _first_piece(console, generator)
        except StopIteration:
            console.print(Text("The model returned an empty response.", style="dim"))
            console.print()
            return
        console.print(Text("Assistant › ", style="bold green"), end="")
        _write_piece(console, first)
        printed = True
        for piece in generator:
            _write_piece(console, piece)
            printed = True
        console.print()
        console.print()
    except KeyboardInterrupt:
        console.print()
        note = (
            "Stopped. The partial reply is saved in this session."
            if printed
            else "Stopped."
        )
        console.print(Text(note, style="yellow"))
        console.print()
    except Exception as exc:
        if printed:
            console.print()
        message = format_error(exc, base_url=session.client.base_url)
        error = Text()
        error.append("Error: ", style="bold red")
        error.append(message)
        console.print(error)
        if printed:
            console.print(Text("The partial reply is saved in this session.", style="yellow"))
        console.print()
    finally:
        generator.close()
        if session.client.consume_stream_notice():
            console.print(Text(STREAM_FALLBACK_NOTICE, style="dim"))
            console.print()


def _first_piece(console: Console, generator: Iterator[str]) -> str:
    if console.is_terminal:
        with console.status("[dim]Waiting for the model…[/]", spinner="dots"):
            return next(generator)
    return next(generator)


def _write_piece(console: Console, piece: str) -> None:
    if not piece:
        return
    console.print(piece, end="", markup=False, highlight=False, soft_wrap=True)


def _read_line(console: Console, stdin: TextIO) -> str:
    console.print(Text("You › ", style="bold cyan"), end="")
    console.file.flush()
    interactive = stdin is sys.stdin and stdin.isatty()
    if interactive:
        return input("")
    line = stdin.readline()
    if line == "":
        raise EOFError
    visible = line.rstrip("\r\n")
    console.print(visible, markup=False, highlight=False, soft_wrap=True)
    return visible


def _print_banner(
    console: Console,
    settings: Settings,
    *,
    system: str | None,
    streaming: bool,
) -> None:
    lines = [
        f"[bold]Model[/]     {escape(settings.model)}",
        f"[bold]Endpoint[/]  {escape(settings.base_url)}",
    ]
    if system and system.strip():
        preview = " ".join(system.split())
        if len(preview) > 80:
            preview = preview[:77] + "..."
        lines.append(f"[bold]System[/]    {escape(preview)}")
    if not streaming:
        lines.append("[dim]Streaming is off[/]")
    lines.append("[dim]/help  ·  /reset  ·  /model  ·  /system  ·  /exit[/]")
    console.print(
        Panel(
            "\n".join(lines),
            title=f"gptchat {__version__}",
            border_style="cyan",
            padding=(1, 2),
        )
    )
    console.print()


def _farewell(console: Console) -> None:
    console.print(Text("Goodbye.", style="dim"))


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


def _enable_line_editing() -> None:
    """Enable readline history when the standard library provides it."""

    try:
        import readline
    except ImportError:
        return
    readline.set_history_length(1000)
