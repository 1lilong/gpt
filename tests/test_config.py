"""Settings parsing."""

from __future__ import annotations

import unittest

from gptchat.config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ConfigError,
    load_settings,
    normalize_base_url,
    normalize_model,
)


class LoadSettingsTest(unittest.TestCase):
    def test_defaults_and_strips_the_key(self) -> None:
        settings = load_settings(environ={"OPENAI_API_KEY": "  sk-test  "})
        self.assertEqual(settings.api_key, "sk-test")
        self.assertEqual(settings.base_url, DEFAULT_BASE_URL)
        self.assertEqual(settings.model, DEFAULT_MODEL)
        self.assertNotIn("sk-test", repr(settings))

    def test_environment_and_explicit_overrides(self) -> None:
        settings = load_settings(
            model="custom-model",
            base_url="http://localhost:8080/v1/",
            environ={
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_MODEL": "from-env",
                "OPENAI_BASE_URL": "https://example.com/v1",
            },
        )
        self.assertEqual(settings.model, "custom-model")
        self.assertEqual(settings.base_url, "http://localhost:8080/v1")

    def test_blank_optional_values_use_defaults(self) -> None:
        settings = load_settings(
            environ={
                "OPENAI_API_KEY": "sk-test",
                "OPENAI_BASE_URL": "  ",
                "OPENAI_MODEL": "",
            }
        )
        self.assertEqual(settings.base_url, DEFAULT_BASE_URL)
        self.assertEqual(settings.model, DEFAULT_MODEL)

    def test_missing_key(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            load_settings(environ={})
        self.assertIn("OPENAI_API_KEY", str(caught.exception))

    def test_rejects_bad_urls(self) -> None:
        for raw in (
            "ftp://example.com/v1",
            "api.openai.com",
            "https://user:secret@example.com/v1",
            "https://example.com/v1?token=secret",
            "https://example.com/v1 extra",
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError):
                    normalize_base_url(raw)

    def test_rejects_bad_models(self) -> None:
        with self.assertRaises(ConfigError):
            normalize_model("two words")
        with self.assertRaises(ConfigError):
            normalize_model("a" * 201)


if __name__ == "__main__":
    unittest.main()
