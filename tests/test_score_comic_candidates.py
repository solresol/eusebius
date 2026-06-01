import unittest

from scripts.score_comic_candidates import score_passage


class ScoreComicCandidatesTests(unittest.TestCase):
    def test_scores_visual_documentary_features(self) -> None:
        score, reason = score_passage(
            greek_text="x" * 500,
            english_text=(
                "The emperor sent a letter to the bishop of Alexandria while "
                "soldiers gathered for the persecution."
            ),
            ai_english_translation="",
        )

        self.assertGreaterEqual(score, 8.0)
        self.assertIn("places", reason)
        self.assertIn("documents and testimony", reason)
        self.assertIn("conflict and persecution", reason)

    def test_ignores_abstract_passages_without_features(self) -> None:
        score, reason = score_passage(
            greek_text="short",
            english_text="This passage concerns an argument about earlier matters.",
            ai_english_translation="",
        )

        self.assertEqual(score, 0.0)
        self.assertEqual(reason, "No documentary-comic features matched.")

    def test_uses_ai_translation_when_reference_is_empty(self) -> None:
        score, reason = score_passage(
            greek_text="x" * 100,
            english_text="",
            ai_english_translation="A decree was written in Rome and sent by ship.",
        )

        self.assertGreater(score, 3.0)
        self.assertIn("documents and testimony", reason)


if __name__ == "__main__":
    unittest.main()
