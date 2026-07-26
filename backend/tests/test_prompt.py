from __future__ import annotations

import hashlib
import json
import unittest

from backend.llm import LLMExtractor
from backend.prompt import VEHICLE_ENTITY_PROMPT, render_vehicle_entity_prompt


class PromptTests(unittest.TestCase):
    def test_production_prompt_matches_benchmarked_long_prompt(self) -> None:
        digest = hashlib.sha256(VEHICLE_ENTITY_PROMPT.encode("utf-8")).hexdigest()

        self.assertEqual(
            digest,
            "166e7ca3679365ed0f2102ac8cd5730a317eb69fd980fcbac0ede4c4b4036015",
        )

    def test_renderer_injects_exactly_one_json_input_row(self) -> None:
        query = 'I want a "Toyota" RAV4'
        rendered = render_vehicle_entity_prompt(query)

        self.assertNotIn("{{INPUT_ROWS}}", rendered)
        self.assertIn(json.dumps([query], ensure_ascii=False), rendered)

    def test_structured_result_is_converted_to_an_extraction(self) -> None:
        extraction = LLMExtractor._validate_batch(
            {
                "results": [
                    {
                        "record_id": 1,
                        "make": "Toyota",
                        "model": "RAV4",
                        "badge": None,
                        "transmission_type": None,
                        "fuel_type": None,
                        "drive_type": None,
                    }
                ]
            },
            [1],
        )[0]

        self.assertTrue(extraction.vehicle_present)
        self.assertTrue(extraction.is_complete)
        self.assertEqual(extraction.fields["make"], "Toyota")
        self.assertEqual(extraction.fields["model"], "RAV4")


if __name__ == "__main__":
    unittest.main()
