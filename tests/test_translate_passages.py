import argparse
import unittest

from scripts.translate_passages import (
    estimate_request_tokens,
    resolve_daily_token_budget,
    resolve_model,
    resolve_prompt_version,
)


class TranslatePassagesTests(unittest.TestCase):
    def test_cleanup_defaults_are_for_english_repair(self) -> None:
        args = argparse.Namespace(
            mode="cleanup",
            model=None,
            prompt_version=None,
            daily_token_budget=None,
        )
        self.assertEqual(resolve_model(args), "gpt-5.6-terra")
        self.assertEqual(resolve_prompt_version(args), "english-cleanup-v1")
        self.assertEqual(resolve_daily_token_budget(args), 500_000)

    def test_translate_defaults_are_for_fresh_greek_translation(self) -> None:
        args = argparse.Namespace(
            mode="translate",
            model=None,
            prompt_version=None,
            daily_token_budget=None,
        )
        self.assertEqual(resolve_model(args), "gpt-6-sol")
        self.assertEqual(resolve_prompt_version(args), "greek-translation-v1")
        self.assertEqual(resolve_daily_token_budget(args), 10_000)

    def test_request_token_estimate_includes_prompt_overhead(self) -> None:
        self.assertGreater(estimate_request_tokens("a" * 400), 600)


if __name__ == "__main__":
    unittest.main()
