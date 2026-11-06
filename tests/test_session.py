"""Conversation history and slash commands."""

from __future__ import annotations

import unittest
from collections.abc import Iterator, Sequence

from gptchat.session import ChatSession, UserCommand, UserMessage, parse_input


class ScriptedClient:
    def __init__(self, events: list[object]) -> None:
        self.model = "demo"
        self.base_url = "http://example.test/v1"
        self.events = events
        self.calls: list[list[dict[str, str]]] = []
        self.notices = 0

    def iter_text(self, messages: Sequence[dict[str, str]]) -> Iterator[str]:
        self.calls.append([dict(message) for message in messages])
        for event in self.events:
            if isinstance(event, BaseException):
                raise event
            yield str(event)

    def consume_stream_notice(self) -> bool:
        self.notices += 1
        return False


class ParseInputTest(unittest.TestCase):
    def test_classifies_messages_and_commands(self) -> None:
        self.assertIsNone(parse_input("   "))
        self.assertEqual(parse_input("hello"), UserMessage("hello"))
        self.assertEqual(parse_input("/reset"), UserCommand("reset", ""))
        self.assertEqual(parse_input("/MODEL gpt-4o"), UserCommand("model", "gpt-4o"))
        self.assertEqual(parse_input("/"), UserCommand("help", ""))
        self.assertEqual(parse_input("//reset"), UserMessage("/reset"))
        self.assertEqual(
            parse_input("/system  be brief  "),
            UserCommand("system", "be brief"),
        )


class ChatSessionTest(unittest.TestCase):
    def test_history_grows_across_turns(self) -> None:
        client = ScriptedClient(["AB"])
        session = ChatSession(client, system="be brief")
        self.assertEqual("".join(session.ask("hi")), "AB")
        self.assertEqual("".join(session.ask("next")), "AB")
        self.assertEqual(
            client.calls[1],
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "AB"},
                {"role": "user", "content": "next"},
            ],
        )

    def test_failure_before_text_drops_the_user_turn(self) -> None:
        client = ScriptedClient([RuntimeError("nope")])
        session = ChatSession(client)
        with self.assertRaises(RuntimeError):
            list(session.ask("hi"))
        self.assertEqual(session.history, [])

    def test_interrupt_keeps_partial_reply(self) -> None:
        client = ScriptedClient(["Hi", KeyboardInterrupt()])
        session = ChatSession(client)
        received: list[str] = []
        with self.assertRaises(KeyboardInterrupt):
            for piece in session.ask("hi"):
                received.append(piece)
        self.assertEqual(received, ["Hi"])
        self.assertEqual(
            session.history,
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "Hi"},
            ],
        )

    def test_interrupt_before_text_drops_the_user_turn(self) -> None:
        client = ScriptedClient([KeyboardInterrupt()])
        session = ChatSession(client)
        with self.assertRaises(KeyboardInterrupt):
            list(session.ask("hi"))
        self.assertEqual(session.history, [])

    def test_commands(self) -> None:
        client = ScriptedClient(["ok"])
        session = ChatSession(client, system="old")
        list(session.ask("hi"))

        updated = session.handle_command("system", "new")
        self.assertIn("updated", updated.message)
        self.assertEqual(session.history[0]["content"], "new")
        self.assertEqual(session.history[1]["role"], "user")

        shown = session.handle_command("system", "")
        self.assertIn("new", shown.message)

        cleared = session.handle_command("system", "--clear")
        self.assertIn("cleared", cleared.message)
        self.assertIsNone(session.system)

        session.set_system("kept")
        list(session.ask("again"))
        reset = session.handle_command("reset", "")
        self.assertEqual(reset.message, "Conversation cleared.")
        self.assertEqual(session.history, [{"role": "system", "content": "kept"}])

        renamed = session.handle_command("model", "gpt-4o")
        self.assertEqual(client.model, "gpt-4o")
        self.assertIn("gpt-4o", renamed.message)
        rejected = session.handle_command("model", "two words")
        self.assertEqual(client.model, "gpt-4o")
        self.assertIn("whitespace", rejected.message)

        current = session.handle_command("model", "")
        self.assertIn("gpt-4o", current.message)

        unknown = session.handle_command("dance", "")
        self.assertIn("/dance", unknown.message)
        leaving = session.handle_command("quit", "")
        self.assertTrue(leaving.exit_chat)


if __name__ == "__main__":
    unittest.main()
