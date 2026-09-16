#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for pack owner records and immutable version files."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_packs
import check_scope
import pack_ownership


class PackCheck(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.packs = Path(self.directory.name) / "packs"
        self.packs.mkdir()

    def version(self, pack="Starter", version="1.0.0"):
        folder = self.packs / pack
        folder.mkdir(exist_ok=True)
        path = folder / f"{version}.toml"
        path.write_text('id = "Starter"\n', encoding="utf-8")
        return path

    def owner(self, pack="Starter", **changes):
        record = {"github_login": "Maxi", "github_id": 7, **changes}
        path = self.packs / pack / pack_ownership.OWNER_FILE
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def test_a_pack_with_a_valid_owner_passes(self):
        self.version()
        self.owner()
        self.assertEqual(check_packs.check(packs=self.packs), [])

    def test_a_pack_must_record_its_owner(self):
        self.version()
        errors = check_packs.check(packs=self.packs)
        self.assertIn("every pack must record its owner", errors[0])

    def test_an_owner_without_a_version_is_rejected(self):
        (self.packs / "Starter").mkdir()
        self.owner()
        errors = check_packs.check(packs=self.packs)
        self.assertIn("has no pack version", errors[0])

    def test_unknown_owner_fields_are_rejected(self):
        self.version()
        self.owner(role="steward")
        errors = check_packs.check(packs=self.packs)
        self.assertIn("unknown pack owner field: role", errors[0])

    def test_duplicate_owner_fields_are_rejected(self):
        self.version()
        path = self.packs / "Starter" / pack_ownership.OWNER_FILE
        path.write_text(
            '{"github_login":"Maxi","github_login":"Attacker","github_id":7}',
            encoding="utf-8",
        )
        errors = check_packs.check(packs=self.packs)
        self.assertIn("duplicate field 'github_login'", errors[0])

    def test_a_boolean_is_not_an_account_id(self):
        self.version()
        self.owner(github_id=True)
        errors = check_packs.check(packs=self.packs)
        self.assertIn("positive integer", errors[0])

    def test_an_accepted_version_cannot_be_modified_or_deleted(self):
        self.version()
        self.owner()
        for status in ("modified", "removed", "renamed", "copied"):
            with self.subTest(status=status):
                change = check_scope.Change("packs/Starter/1.0.0.toml", status)
                errors = check_packs.check([change], self.packs)
                self.assertIn("immutable", errors[0])

    def test_a_rename_out_of_packs_uses_the_previous_path(self):
        self.version()
        self.owner()
        change = check_scope.Change("archive/1.0.0.toml", "renamed", "packs/Starter/1.0.0.toml")
        errors = check_packs.check([change], self.packs)
        self.assertIn("packs/Starter/1.0.0.toml", errors[0])

    def test_a_new_version_is_allowed(self):
        self.version()
        self.owner()
        change = check_scope.Change("packs/Starter/2.0.0.toml", "added")
        self.assertEqual(check_packs.check([change], self.packs), [])


if __name__ == "__main__":
    unittest.main()
