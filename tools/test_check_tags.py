#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the curated tag vocabulary and authored tag notes.
"""

import json
import tempfile
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_tags

SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "authored.schema.json"


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

    def test_every_repository_forum_prefix_has_its_id(self):
        with check_tags.TAGS.open("rb") as handle:
            entries = tomllib.load(handle)["mod"]
        self.assertEqual(
            {entry["tag"]: entry.get("forum_prefix_id") for entry in entries if "forum_prefix" in entry},
            {
                "parts": 4,
                "celestial": 6,
                "gameplay": 9,
                "user-interface": 8,
                "visual": 11,
                "audio": 7,
                "tools": 10,
            },
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

    def prefixed(self, *entries):
        text = "spec_version = 1\n"
        for tag, prefix, prefix_id in entries:
            text += f'[[mod]]\ntag = "{tag}"\nname = "{tag}"\nmeaning = "Some {tag}."\n'
            if prefix is not None:
                text += f'forum_prefix = "{prefix}"\n'
            if prefix_id is not None:
                text += f"forum_prefix_id = {prefix_id}\n"
        path = self.write(text)
        _, errors = check_tags.load_vocabulary(path)
        where = check_tags._relative(path)
        return [error.removeprefix(f"{where}: ") for error in errors]

    def test_forum_prefix_ids_are_valid(self):
        errors = self.prefixed(("parts", "Parts", 4), ("tools", "Tools", 10), ("library", None, None))
        self.assertEqual(errors, [])

    def test_a_duplicate_forum_prefix_id_is_rejected(self):
        errors = self.prefixed(("parts", "Parts", 4), ("tools", "Tools", 4))
        self.assertEqual(errors, ["mod[1]: forum_prefix_id 4 is already defined"])

    def test_a_forum_prefix_id_that_is_not_a_positive_integer_is_rejected(self):
        for value in ("0", "-4", '"4"', "4.0", "true"):
            with self.subTest(value=value):
                errors = self.prefixed(("parts", "Parts", value))
                self.assertEqual(
                    errors, ["mod[0]: 'forum_prefix_id' must be a positive integer"]
                )

    def test_a_forum_prefix_id_without_forum_prefix_is_rejected(self):
        errors = self.prefixed(("library", None, 12))
        self.assertEqual(errors, ["mod[0]: 'forum_prefix_id' needs 'forum_prefix'"])


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

    def test_vehicle_and_save_tags_are_free_form(self):
        for content_type in ("vehicle", "save"):
            for tags in (None, [], ["rover"], ["parts", "rover"]):
                with self.subTest(content_type=content_type, tags=tags):
                    self.assertEqual(self.notes(content_type, tags), [])

    def test_every_type_of_the_schema_has_an_entry(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(set(check_tags.CONTENT_TYPES), set(schema["properties"]["type"]["enum"]))


if __name__ == "__main__":
    unittest.main()
