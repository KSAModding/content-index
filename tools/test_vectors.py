#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the checks over schemas/vectors.json, the test documents the listing page runs too.
"""

import json
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_images
import check_index
import check_license
import check_schema
import check_tags
import page_licenses

VECTORS = Path(__file__).resolve().parent.parent / "schemas" / "vectors.json"
RULES = {"schema", "id", "bounds", "license", "tags", "images", "abstract"}
WHERE = "vector"


def run(text, validator, vocabulary):
    """The errors and notes of the checks that need nothing but the document."""
    document = check_schema.normalise(tomllib.loads(text))
    errors = []
    notes = []
    check_schema.check_parsed(WHERE, document, validator, errors)
    check_license.check_document(WHERE, document, errors)
    check_images.check_document(WHERE, document, errors, notes)
    notes.extend(check_tags.check_document(Path(WHERE), document, vocabulary))
    entry = check_index.Entry(Path(WHERE), WHERE, ("listing", WHERE), str(document.get("id")), document)
    notes.extend(check_index.check_abstracts([entry], {WHERE}))
    return errors, notes


class Vectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]
        cls.validator = check_schema.validator()
        cls.vocabulary, errors = check_tags.load_vocabulary()
        if errors:
            raise AssertionError(errors)

    def test_each_vector_is_well_formed(self):
        names = [vector["name"] for vector in self.vectors]
        self.assertEqual(len(names), len(set(names)), "vector names are unique")
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                self.assertIn(vector["rule"], RULES)
                self.assertIsInstance(vector["accepted"], bool)
                self.assertIsInstance(vector["noted"], bool)

    def test_every_rule_has_an_accepted_and_a_rejected_vector(self):
        for rule in RULES - {"abstract"}:
            outcomes = {vector["accepted"] for vector in self.vectors if vector["rule"] == rule}
            self.assertEqual(outcomes, {True, False}, rule)

    def test_the_checks_agree_with_each_vector(self):
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                errors, notes = run(vector["toml"], self.validator, self.vocabulary)
                self.assertEqual(not errors, vector["accepted"], errors)
                self.assertEqual(bool(notes), vector["noted"], notes)
                if "says" in vector:
                    self.assertTrue(any(vector["says"] in line for line in errors + notes), errors + notes)


class PageLicenses(unittest.TestCase):
    def test_the_page_knows_the_identifiers_the_checks_know(self):
        self.assertEqual(
            page_licenses.TARGET.read_text(encoding="utf-8"),
            page_licenses.render(),
            "site/js/licenses.js is out of date, run tools/page_licenses.py",
        )


if __name__ == "__main__":
    unittest.main()
