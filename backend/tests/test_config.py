from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.config import AppConfig, DEFAULT_OPENAI_BASE_URL, normalize_openai_base_url


class OpenAIConfigurationTests(unittest.TestCase):
    def test_empty_base_url_uses_official_api(self) -> None:
        self.assertEqual(normalize_openai_base_url(""), DEFAULT_OPENAI_BASE_URL)

    def test_trailing_slash_is_removed(self) -> None:
        self.assertEqual(
            normalize_openai_base_url("https://example.test/v1/"),
            "https://example.test/v1",
        )

    def test_relative_base_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute"):
            normalize_openai_base_url("api.openai.com/v1")

    def test_legacy_open_ai_key_name_is_supported(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "", "OPEN_AI_API_KEY": "legacy-key"},
        ):
            self.assertEqual(AppConfig.from_environment().openai_api_key, "legacy-key")


if __name__ == "__main__":
    unittest.main()
