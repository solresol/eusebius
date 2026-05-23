import unittest

from scripts.import_first1k import is_title_matter, parse_passages


class ImportFirst1KTests(unittest.TestCase):
    def test_title_matter_is_skipped_when_parsing_passages(self) -> None:
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0">
          <text>
            <body>
              <div type="textpart" subtype="book" n="1">
                <div type="textpart" subtype="chapter" n="1">
                  <p>THE ECCLESIASTICAL HISTORY OF EUSEBIUS</p>
                  <p>BOOK I</p>
                  <p>I. I. HAVE purposed to record the successions.</p>
                  <p>I will begin with Christ.</p>
                </div>
              </div>
            </body>
          </text>
        </TEI>
        """
        passages = parse_passages(xml)
        self.assertEqual([passage.canonical_ref for passage in passages], ["1.1.1", "1.1.2"])
        self.assertEqual(passages[0].text, "I. I. HAVE purposed to record the successions.")

    def test_short_uppercase_markers_are_title_matter(self) -> None:
        self.assertTrue(is_title_matter("ΕΥΣΗΒΙΟΥ"))
        self.assertTrue(is_title_matter("A"))
        self.assertFalse(is_title_matter("Ι. τὰς τῶν ἱερῶν ἀποστόλων διαδοχὰς"))


if __name__ == "__main__":
    unittest.main()
