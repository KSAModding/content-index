#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check schemas/save-names.json, the cases of the name rule of RFC 0085.

This repository keeps no copy of the rule. The vectors run through
`stamp_release.valid_save_name` of content-index-releases where it is checked
out, and through `site/js/savename.js` in the tests of the listing page.
"""

import json
import os
import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_release

VECTORS = Path(__file__).resolve().parent.parent / "schemas" / "save-names.json"
KEYS = {"name": str, "value": str, "accepted": bool, "why": str}

# The cases use only characters that Unicode 15.0 or older assigns, so every
# runner with a table at least that new reads the same categories.
UNICODE = (15, 0, 0)


class SaveNameVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = VECTORS.read_bytes()
        cls.vectors = json.loads(cls.text.decode("utf-8"))["vectors"]

    def test_the_file_is_ascii(self):
        self.assertTrue(self.text.isascii(), "write every character outside ASCII as a \\u escape")

    def test_each_vector_is_well_formed(self):
        names = [vector.get("name") for vector in self.vectors]
        self.assertEqual(len(names), len(set(names)), "vector names are unique")
        for vector in self.vectors:
            with self.subTest(vector.get("name")):
                self.assertEqual(set(vector), set(KEYS))
                for key, kind in KEYS.items():
                    self.assertIsInstance(vector[key], kind, key)

    def test_both_verdicts_occur(self):
        self.assertEqual({vector["accepted"] for vector in self.vectors}, {True, False})

    def test_the_runner_knows_every_character(self):
        version = tuple(int(part) for part in unicodedata.unidata_version.split("."))
        self.assertGreaterEqual(
            version, UNICODE,
            f"the Unicode table of this Python is {unicodedata.unidata_version}, and the "
            "vectors need 15.0 or newer",
        )
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                unassigned = [
                    f"U+{ord(character):04X}"
                    for character in vector["value"]
                    if unicodedata.category(character) == "Cn"
                ]
                self.assertEqual(unassigned, [])

    def test_the_stamper_agrees(self):
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        if not (root / "tools" / "stamp_release.py").is_file():
            self.skipTest("content-index-releases is not checked out next to this repository")
        stamp_release, _ = check_release.load_stamper(root)
        if not hasattr(stamp_release, "valid_save_name"):
            self.skipTest("the checkout of content-index-releases has no name rule yet")
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                self.assertEqual(stamp_release.valid_save_name(vector["value"]), vector["accepted"], vector["why"])


if __name__ == "__main__":
    unittest.main()
