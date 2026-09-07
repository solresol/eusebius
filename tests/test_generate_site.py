import tempfile
import unittest
from pathlib import Path

from scripts.generate_site import (
    comic_public_relative_path,
    publish_comic_images,
    render_comic_viewer,
)


class GenerateSiteTests(unittest.TestCase):
    def test_rejects_comic_path_outside_public_tree(self) -> None:
        with self.assertRaises(ValueError):
            comic_public_relative_path("/assets/panel.webp")
        with self.assertRaises(ValueError):
            comic_public_relative_path("/comic/../assets/panel.webp")

    def test_publishes_derivative_and_renders_source_link(self) -> None:
        row = {
            "comic_plan_id": 2,
            "plan_title": "Martyrs of Phoenicia and Palestine",
            "plan_summary": "Three locations in one documentary sequence.",
            "panel_number": 3,
            "panel_title": "Phoenicia, Emesa, and Phaeno",
            "caption": "Phoenicia, Emesa, and Phaeno",
            "public_path": "/comic/2/3.webp",
            "image_model": "gpt-image-2",
            "image_sha256": "abc123",
            "canonical_ref": "8.13.1",
            "book": "8",
            "chapter": "13",
            "english_text": "A source-grounded translation.",
            "translation_model": "gpt-5.4-mini",
            "translation_prompt_version": "english-cleanup-v1",
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "site"
            web_dir = root / "web"
            source_path = web_dir / "2" / "3.webp"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"webp-derivative")
            source_path.chmod(0o600)

            published = publish_comic_images(output_dir, [row], web_dir)
            render_comic_viewer(output_dir, published)

            self.assertEqual(
                (output_dir / "comic" / "2" / "3.webp").read_bytes(),
                b"webp-derivative",
            )
            self.assertEqual(
                (output_dir / "comic" / "2" / "3.webp").stat().st_mode & 0o777,
                0o644,
            )
            self.assertEqual(source_path.stat().st_mode & 0o777, 0o600)
            viewer = (output_dir / "comics.html").read_text(encoding="utf-8")
            self.assertIn('src="comic/2/3.webp"', viewer)
            self.assertIn("passages-book-8-section-13.html#p-8.13.1", viewer)
            self.assertIn("A source-grounded translation.", viewer)


if __name__ == "__main__":
    unittest.main()
