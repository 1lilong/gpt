"""Terminal loop against a local fake API. No real network calls."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from pathlib import Path

from rich.console import Console

from gptchat.cli import main
from gptchat.client import STREAM_FALLBACK_NOTICE
from tests.mock_openai import MockOpenAIServer

ROOT = Path(__file__).resolve().parents[1]


class _InterruptInput(io.StringIO):
    def readline(self) -> str:
        raise KeyboardInterrupt


class CliTest(unittest.TestCase):
    def _run(
        self,
        stdin_text: str,
        *,
        mode: str = "sse",
        args: list[str] | None = None,
        key: str = "sk-test",
        extra_env: dict[str, str] | None = None,
        stdin: io.TextIOBase | None = None,
    ) -> tuple[int, str, list[dict[str, object]]]:
        with MockOpenAIServer(mode) as server:
            buffer = io.StringIO()
            console = Console(
                file=buffer,
                force_terminal=False,
                highlight=False,
                width=400,
                no_color=True,
            )
            environ = {
                "OPENAI_API_KEY": key,
                "OPENAI_BASE_URL": server.base_url,
                "OPENAI_MODEL": "gpt-4o-mini",
            }
            if extra_env:
                environ.update(extra_env)
            code = main(
                args or [],
                environ=environ,
                stdin=stdin if stdin is not None else io.StringIO(stdin_text),
                console=console,
            )
            return code, buffer.getvalue(), server.requests

    def test_streaming_multiturn_history_and_eof(self) -> None:
        code, output, requests = self._run("hello\nand more\n")
        self.assertEqual(code, 0)
        self.assertIn("echo:hello", output)
        self.assertIn("echo:and more", output)
        self.assertIn("Goodbye.", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(len(requests), 2)
        first = requests[0]["body"]
        second = requests[1]["body"]
        assert isinstance(first, dict)
        assert isinstance(second, dict)
        self.assertTrue(first["stream"])
        self.assertEqual(first["model"], "gpt-4o-mini")
        self.assertTrue(str(requests[0]["path"]).endswith("/chat/completions"))
        self.assertEqual(requests[0]["authorization"], "Bearer sk-test")
        messages = second["messages"]
        assert isinstance(messages, list)
        self.assertEqual(messages[0]["content"], "hello")
        self.assertEqual(messages[1]["content"], "echo:hello")
        self.assertEqual(messages[2]["content"], "and more")

    def test_commands_reset_model_system_and_escape(self) -> None:
        script = "\n".join(
            [
                "/help",
                "/model",
                "/model other-model",
                "/system be brief",
                "hello",
                "/reset",
                "/system",
                "//reset",
                "/reset",
                "/system --clear",
                "after",
                "/nope",
                "/exit",
            ]
        )
        code, output, requests = self._run(script)
        self.assertEqual(code, 0)
        self.assertIn("Commands", output)
        self.assertIn("Current model: gpt-4o-mini", output)
        self.assertIn("Model set to other-model.", output)
        self.assertIn("System prompt updated.", output)
        self.assertIn("Conversation cleared.", output)
        self.assertIn("be brief", output)
        self.assertIn("System prompt cleared.", output)
        self.assertIn("Unknown command '/nope'", output)
        self.assertIn("Goodbye.", output)
        self.assertEqual(len(requests), 3)
        first, second, third = (request["body"] for request in requests)
        assert isinstance(first, dict)
        assert isinstance(second, dict)
        assert isinstance(third, dict)
        self.assertEqual(first["model"], "other-model")
        self.assertEqual(first["messages"][0], {"role": "system", "content": "be brief"})
        self.assertEqual(first["messages"][1]["content"], "hello")
        self.assertEqual(second["messages"][0]["role"], "system")
        self.assertEqual(second["messages"][1]["content"], "/reset")
        self.assertEqual(third["messages"], [{"role": "user", "content": "after"}])

    def test_stream_rejection_falls_back_once(self) -> None:
        code, output, requests = self._run("hello\nagain\n/exit\n", mode="reject-stream")
        self.assertEqual(code, 0)
        self.assertIn("echo:hello", output)
        self.assertIn("echo:again", output)
        self.assertIn(STREAM_FALLBACK_NOTICE, output)
        self.assertEqual(output.count(STREAM_FALLBACK_NOTICE), 1)
        bodies = [request["body"] for request in requests]
        assert all(isinstance(body, dict) for body in bodies)
        self.assertEqual(len(bodies), 3)
        self.assertIs(bodies[0]["stream"], True)
        self.assertNotIn("stream", bodies[1])
        self.assertNotIn("stream", bodies[2])

    def test_json_body_for_stream_request_is_shown(self) -> None:
        code, output, requests = self._run("hello\nagain\n/quit\n", mode="json")
        self.assertEqual(code, 0)
        self.assertIn("echo:hello", output)
        self.assertIn("echo:again", output)
        self.assertIn(STREAM_FALLBACK_NOTICE, output)
        bodies = [request["body"] for request in requests]
        assert all(isinstance(body, dict) for body in bodies)
        self.assertEqual(len(bodies), 2)
        self.assertIs(bodies[0]["stream"], True)
        self.assertNotIn("stream", bodies[1])

    def test_request_error_keeps_the_loop_and_drops_the_failed_turn(self) -> None:
        code, output, requests = self._run("first\nsecond\n/exit\n", mode="fail-once")
        self.assertEqual(code, 0)
        self.assertIn("Error:", output)
        self.assertIn("400", output)
        self.assertIn("echo:second", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(len(requests), 2)
        second = requests[1]["body"]
        assert isinstance(second, dict)
        self.assertEqual(second["messages"], [{"role": "user", "content": "second"}])

    def test_authentication_error_is_explicit(self) -> None:
        code, output, requests = self._run(
            "hello\n/exit\n",
            mode="unauthorized",
            key="sk-test-secret-value",
        )
        self.assertEqual(code, 0)
        self.assertIn("Authentication failed", output)
        self.assertNotIn("sk-test-secret-value", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(len(requests), 1)

    def test_missing_api_key(self) -> None:
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False, no_color=True, width=200)
        code = main([], environ={}, stdin=io.StringIO(""), console=console)
        self.assertEqual(code, 1)
        self.assertIn("OPENAI_API_KEY", buffer.getvalue())

    def test_ctrl_c_at_the_prompt_exits(self) -> None:
        code, output, requests = self._run("", stdin=_InterruptInput())
        self.assertEqual(code, 0)
        self.assertIn("Goodbye.", output)
        self.assertNotIn("Traceback", output)
        self.assertEqual(requests, [])

    def test_flags_override_environment(self) -> None:
        code, output, requests = self._run(
            "hello\n/exit\n",
            args=["--model", "flag-model", "--system", "from the flag", "--no-stream"],
        )
        self.assertEqual(code, 0)
        self.assertIn("flag-model", output)
        self.assertIn("from the flag", output)
        self.assertIn("Streaming is off", output)
        body = requests[0]["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["model"], "flag-model")
        self.assertNotIn("stream", body)
        self.assertEqual(body["messages"][0]["content"], "from the flag")

    def test_connection_error(self) -> None:
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False, no_color=True, width=200)
        code = main(
            [],
            environ={
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            },
            stdin=io.StringIO("hello\n/exit\n"),
            console=console,
        )
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Could not connect", output)
        self.assertIn("Goodbye.", output)
        self.assertNotIn("Traceback", output)

    def test_module_help_and_version(self) -> None:
        help_run = subprocess.run(
            [sys.executable, "-m", "gptchat", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn("OPENAI_API_KEY", help_run.stdout)
        version = subprocess.run(
            [sys.executable, "-m", "gptchat", "--version"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn("gptchat 0.1.0", version.stdout)


if __name__ == "__main__":
    unittest.main()
