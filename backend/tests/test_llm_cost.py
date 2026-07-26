from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.llm import LLMExtractor


class LLMCostTests(unittest.TestCase):
    def test_luna_cost_uses_uncached_cached_write_and_output_rates(self) -> None:
        usage = SimpleNamespace(
            input_tokens=1_000,
            output_tokens=100,
            input_tokens_details=SimpleNamespace(
                cached_tokens=200,
                cache_write_tokens=100,
            ),
        )

        cost = LLMExtractor._calculate_cost(usage)

        self.assertAlmostEqual(cost, 0.001445)

    def test_no_usage_returns_no_cost(self) -> None:
        self.assertIsNone(LLMExtractor._calculate_cost(None))


if __name__ == "__main__":
    unittest.main()
