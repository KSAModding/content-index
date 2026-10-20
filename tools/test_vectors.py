#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the checks over schemas/vectors.json, the test documents the listing page runs too.

A vector with `gated` names a type that the rollout gate of RFC 0085 holds. While
the schema refuses that type, the vector is refused with the title of the gate,
and its own verdict holds against a copy of the schema without the gate. So a
steward lifts the gate in the schema alone.
"""

import copy
import json
import sys
import tomllib
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

import check_images
import check_index
import check_layout
import check_license
import check_schema
import check_tags
import page_licenses

VECTORS = Path(__file__).resolve().parent.parent / "schemas" / "vectors.json"
SITE_FIXTURES = Path(__file__).resolve().parent.parent / "site" / "test" / "fixtures"
RULES = {"schema", "id", "bounds", "license", "tags", "images", "abstract", "game_max"}
# The rules that only give notes, so no vector of them is rejected.
NOTE_RULES = {"abstract", "game_max"}
WHERE = "vector"
GATED_TYPES = {"vehicle", "save"}


def gate(schema):
    """The subschema that refuses the types the index does not accept yet, or None."""
    return schema["properties"]["type"].get("not")


def gated_types(schema):
    found = gate(schema)
    return set(found["enum"]) if found else set()


def without_gate(schema):
    """A copy of the schema that accepts every type of its enum."""
    schema = copy.deepcopy(schema)
    schema["properties"]["type"].pop("not", None)
    return schema


def run(text, validator, vocabulary, game_versions=None):
    """The errors and notes of the checks that need the document and at most the game release list."""
    document = check_schema.normalise(tomllib.loads(text))
    errors = []
    notes = []
    check_schema.check_parsed(WHERE, document, validator, errors)
    check_license.check_document(WHERE, document, errors)
    check_images.check_document(WHERE, document, errors, notes)
    notes.extend(check_tags.check_document(Path(WHERE), document, vocabulary))
    entry = check_index.Entry(Path(WHERE), WHERE, ("listing", WHERE), str(document.get("id")), document)
    notes.extend(check_index.check_abstracts([entry], {WHERE}))
    if game_versions is not None:
        notes.extend(check_index.game_max_notes(check_index.bounded([entry], {WHERE}), game_versions))
    return errors, notes


class Vectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]
        cls.validator = check_schema.validator()
        cls.ungated = Draft202012Validator(without_gate(cls.validator.schema))
        cls.gated = gated_types(cls.validator.schema)
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
                self.assertIsInstance(vector.get("game_versions", []), list)
                if "gated" in vector:
                    self.assertIn(vector["gated"], GATED_TYPES)
                    self.assertEqual(tomllib.loads(vector["toml"]).get("type"), vector["gated"])

    def test_the_gate_holds_only_known_types(self):
        self.assertLessEqual(self.gated, GATED_TYPES)

    def test_every_rule_has_an_accepted_and_a_rejected_vector(self):
        for rule in RULES - NOTE_RULES:
            outcomes = {vector["accepted"] for vector in self.vectors if vector["rule"] == rule}
            self.assertEqual(outcomes, {True, False}, rule)

    def test_the_checks_agree_with_each_vector(self):
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                errors, notes = run(
                    vector["toml"], self.validator, self.vocabulary, vector.get("game_versions")
                )
                self.assertEqual(bool(notes), vector["noted"], notes)
                if vector.get("gated") in self.gated:
                    title = gate(self.validator.schema)["title"]
                    self.assertIn(f"{WHERE}: type: '{vector['gated']}' is {title}", errors)
                    continue
                self.assertEqual(not errors, vector["accepted"], errors)
                if "says" in vector:
                    self.assertTrue(any(vector["says"] in line for line in errors + notes), errors + notes)

    def test_the_gated_vectors_without_the_gate(self):
        for vector in self.vectors:
            if "gated" not in vector:
                continue
            with self.subTest(vector["name"]):
                errors, notes = run(
                    vector["toml"], self.ungated, self.vocabulary, vector.get("game_versions")
                )
                self.assertEqual(not errors, vector["accepted"], errors)
                self.assertEqual(bool(notes), vector["noted"], notes)
                if "says" in vector:
                    self.assertTrue(any(vector["says"] in line for line in errors + notes), errors + notes)


class PagePack(unittest.TestCase):
    """site/test/pack.test.js writes this file from a pack form."""

    def test_the_checks_accept_the_pack_the_page_writes(self):
        packs = SITE_FIXTURES / "packs"
        self.assertEqual(check_layout.check(SITE_FIXTURES / "listings", packs), [])
        self.assertEqual(check_layout.counted(SITE_FIXTURES / "listings", packs), 1)
        path = packs / "ExamplePack" / "1.0.0.toml"
        document = check_schema.normalise(tomllib.loads(path.read_text(encoding="utf-8")))
        errors = []
        check_schema.check_parsed(WHERE, document, check_schema.validator(), errors)
        self.assertEqual(errors, [])


class PageLicenses(unittest.TestCase):
    def test_the_page_knows_the_identifiers_the_checks_know(self):
        self.assertEqual(
            page_licenses.TARGET.read_text(encoding="utf-8"),
            page_licenses.render(),
            "site/js/licenses.js is out of date, run tools/page_licenses.py",
        )


if __name__ == "__main__":
    unittest.main()
