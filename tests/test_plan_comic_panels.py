import unittest

from scripts.plan_comic_panels import validate_plan_payload


class PlanComicPanelsTests(unittest.TestCase):
    def test_accepts_small_source_grounded_plan(self) -> None:
        payload = validate_plan_payload(
            {
                "decision": "plan",
                "title": "Letter to the Churches",
                "summary": "A messenger carries a church letter across the city.",
                "rejection_reason": "",
                "continuity_notes": "Late antique documentary palette.",
                "panels": [
                    {
                        "panel_number": 2,
                        "panel_title": "Delivery",
                        "panel_prompt": (
                            "A courier delivers a sealed letter to bishops; "
                            "no readable text, no captions, no speech balloons."
                        ),
                        "caption": "The letter arrives.",
                    },
                    {
                        "panel_number": 1,
                        "panel_title": "Writing",
                        "panel_prompt": (
                            "A bishop dictates beside a manuscript desk; "
                            "no readable text, no captions, no speech balloons."
                        ),
                        "caption": "A document is prepared.",
                    },
                ],
            }
        )

        self.assertEqual(payload["decision"], "plan")
        self.assertEqual([panel["panel_number"] for panel in payload["panels"]], [1, 2])

    def test_reject_requires_reason(self) -> None:
        with self.assertRaises(ValueError):
            validate_plan_payload(
                {
                    "decision": "reject",
                    "title": "",
                    "summary": "",
                    "rejection_reason": "",
                    "continuity_notes": "",
                    "panels": [],
                }
            )

    def test_accepted_plan_requires_two_panels(self) -> None:
        with self.assertRaises(ValueError):
            validate_plan_payload(
                {
                    "decision": "plan",
                    "title": "Too Small",
                    "summary": "Only one panel.",
                    "rejection_reason": "",
                    "continuity_notes": "",
                    "panels": [
                        {
                            "panel_number": 1,
                            "panel_title": "Only panel",
                            "panel_prompt": "A manuscript desk.",
                            "caption": "Short.",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
