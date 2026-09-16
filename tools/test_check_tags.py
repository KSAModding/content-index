#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the curated tag vocabulary and authored tag notes.
"""

import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_tags


class Vocabulary(unittest.TestCase):
    def write(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "tags.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_repository_vocabulary_is_valid(self):
        vocabulary, errors = check_tags.load_vocabulary()
        self.assertEqual(errors, [])
        self.assertEqual(
            list(vocabulary["mod"]),
            [
                "parts",
                "celestial",
                "gameplay",
                "user-interface",
                "visual",
                "audio",
                "tools",
                "library",
            ],
        )

    def test_a_boolean_spec_version_is_invalid(self):
        path = self.write(
            'spec_version = true\n[[mod]]\ntag = "parts"\nname = "Parts"\nmeaning = "Parts."\n'
        )
        _, errors = check_tags.load_vocabulary(path)
        self.assertTrue(any("spec_version must be 1" in error for error in errors))

    def test_a_float_spec_version_is_invalid(self):
        path = self.write(
            'spec_version = 1.0\n[[mod]]\ntag = "parts"\nname = "Parts"\nmeaning = "Parts."\n'
        )
        _, errors = check_tags.load_vocabulary(path)
        self.assertTrue(any("spec_version must be 1" in error for error in errors))

    def test_a_duplicate_is_rejected(self):
        path = self.write(
            'spec_version = 1\n[[mod]]\ntag = "parts"\nname = "Parts"\nmeaning = "One."\n'
            '[[mod]]\ntag = "parts"\nname = "Parts again"\nmeaning = "Two."\n'
        )
        _, errors = check_tags.load_vocabulary(path)
        self.assertTrue(any("already defined" in error for error in errors))

    def test_a_bad_tag_form_is_rejected(self):
        path = self.write(
            'spec_version = 1\n[[mod]]\ntag = "User_Interface"\nname = "UI"\nmeaning = "Windows."\n'
        )
        _, errors = check_tags.load_vocabulary(path)
        self.assertTrue(any("lowercase words" in error for error in errors))

    def test_a_missing_meaning_is_rejected(self):
        path = self.write('spec_version = 1\n[[mod]]\ntag = "parts"\nname = "Parts"\n')
        _, errors = check_tags.load_vocabulary(path)
        self.assertTrue(any("'meaning' is required" in error for error in errors))


class AuthoredDocuments(unittest.TestCase):
    def setUp(self):
        self.vocabulary, errors = check_tags.load_vocabulary()
        self.assertEqual(errors, [])

    def notes(self, content_type, tags=None):
        document = {"type": content_type}
        if tags is not None:
            document["tags"] = tags
        return check_tags.check_document(Path("fixture.toml"), document, self.vocabulary)

    def test_curated_tags_have_no_note(self):
        self.assertEqual(self.notes("mod", ["gameplay", "tools"]), [])

    def test_an_unknown_tag_names_it_and_the_spec(self):
        notes = self.notes("mod", ["tools", "weapons"])
        self.assertEqual(len(notes), 1)
        self.assertIn("'weapons' is not a curated tag", notes[0])
        self.assertIn("spec/tags.md", notes[0])

    def test_no_curated_tag_has_one_note(self):
        notes = self.notes("mod", [])
        self.assertEqual(len(notes), 1)
        self.assertIn("no curated tag", notes[0])

    def test_a_mod_loader_uses_the_mod_list(self):
        self.assertEqual(self.notes("mod-loader", ["library"]), [])

    def test_a_pack_uses_the_mod_list(self):
        self.assertEqual(self.notes("modpack", ["parts"]), [])


if __name__ == "__main__":
    unittest.main()
