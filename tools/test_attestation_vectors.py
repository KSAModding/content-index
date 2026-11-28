#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run schemas/attestation-vectors.json, the canonical form a share host attests (RFC 0094).

Every share host builds the same form from its own change and tests against
this file, so a host and the ownership check hash the same bytes.
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_scope
import ownership

VECTORS = Path(__file__).resolve().parent.parent / "schemas" / "attestation-vectors.json"


def changes(files):
    """The files as the pull request files API gives them, read as decide.py reads them."""
    return [
        check_scope.Change(entry["filename"], entry["status"], entry.get("previous_filename"), entry.get("sha"))
        for entry in files
    ]


class AttestationVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vectors = json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]

    def test_each_vector_is_well_formed(self):
        names = [vector["name"] for vector in self.vectors]
        self.assertEqual(len(names), len(set(names)), "vector names are unique")
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                self.assertEqual(set(vector), {"name", "files", "canonical", "sha256"})
                self.assertTrue(vector["canonical"].endswith("\n"))
                self.assertEqual(vector["sha256"], hashlib.sha256(vector["canonical"].encode("utf-8")).hexdigest())

    def test_the_canonical_form_of_each_change(self):
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                self.assertEqual(ownership.canonical_change(changes(vector["files"])), vector["canonical"])

    def test_the_digest_of_each_change(self):
        for vector in self.vectors:
            with self.subTest(vector["name"]):
                self.assertEqual(ownership.change_digest(changes(vector["files"])), vector["sha256"])

    def test_the_vectors_hold_every_kind_of_change(self):
        statuses = {entry["status"] for vector in self.vectors for entry in vector["files"]}
        self.assertLessEqual({"added", "modified", "renamed", "removed"}, statuses)
        self.assertTrue(any(not vector["canonical"].isascii() for vector in self.vectors))

    def test_one_byte_more_is_another_digest(self):
        vector = self.vectors[0]
        self.assertNotEqual(
            hashlib.sha256((vector["canonical"] + "\n").encode("utf-8")).hexdigest(), vector["sha256"]
        )


class CanonicalForm(unittest.TestCase):
    def test_a_blob_id_is_lowercased(self):
        found = ownership.canonical_change([check_scope.Change("a.toml", "added", None, "AB" * 20)])
        self.assertEqual(found, f"a.toml {'ab' * 20}\n")

    def test_a_file_without_a_blob_id_has_no_canonical_form(self):
        for blob in (None, "", "abc", "g" * 40):
            with self.subTest(blob):
                with self.assertRaises(ValueError):
                    ownership.canonical_change([check_scope.Change("a.toml", "added", None, blob)])

    def test_no_change_is_the_empty_form(self):
        self.assertEqual(ownership.canonical_change([]), "")


if __name__ == "__main__":
    unittest.main()
