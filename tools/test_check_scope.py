#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the auto-merge scope rule.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_scope


class IsDocument(unittest.TestCase):
    def test_a_listing_is_one(self):
        self.assertTrue(check_scope.is_document("listings/AdvancedFlightComputer.toml"))

    def test_a_pack_version_is_one(self):
        self.assertTrue(check_scope.is_document("packs/NavigationStarterPack/1.0.0.toml"))

    def test_the_suffix_is_matched_case_insensitively(self):
        self.assertTrue(check_scope.is_document("listings/Evil.TOML"))
        self.assertTrue(check_scope.is_document("packs/Pack/1.0.0.Toml"))

    def test_the_folder_name_is_matched_case_sensitively(self):
        self.assertFalse(check_scope.is_document("Listings/Mod.toml"))
        self.assertFalse(check_scope.is_document("PACKS/Pack/1.0.0.toml"))

    def test_a_trailing_newline_does_not_smuggle_a_path_through(self):
        self.assertFalse(check_scope.is_document("listings/Mod.toml\nx"))

    def test_a_listing_in_a_subfolder_is_not_one(self):
        self.assertFalse(check_scope.is_document("listings/nested/Mod.toml"))

    def test_a_pack_document_at_the_listing_depth_is_not_one(self):
        self.assertFalse(check_scope.is_document("packs/1.0.0.toml"))

    def test_a_pack_document_too_deep_is_not_one(self):
        self.assertFalse(check_scope.is_document("packs/Pack/nested/1.0.0.toml"))

    def test_a_readme_is_not_one(self):
        self.assertFalse(check_scope.is_document("listings/README.md"))

    def test_the_checks_are_not_documents(self):
        self.assertFalse(check_scope.is_document("tools/check_schema.py"))
        self.assertFalse(check_scope.is_document("index-status.toml"))

    def test_a_path_that_only_starts_like_a_document_is_not_one(self):
        self.assertFalse(check_scope.is_document("listings-archive/Mod.toml"))


class Evaluate(unittest.TestCase):
    def evaluate(self, paths, status="added"):
        return check_scope.evaluate(check_scope.changes(paths, status))

    def test_one_listing_merges_itself(self):
        candidate, documents, reason = self.evaluate(["listings/Mod.toml"])
        self.assertTrue(candidate)
        self.assertEqual(documents, ["listings/Mod.toml"])
        self.assertEqual(reason, "")

    def test_one_pack_version_merges_itself(self):
        candidate, documents, _ = self.evaluate(["packs/Pack/1.0.0.toml"])
        self.assertTrue(candidate)
        self.assertEqual(documents, ["packs/Pack/1.0.0.toml"])

    def test_an_author_updating_their_own_listing_merges_itself(self):
        candidate, _, _ = self.evaluate(["listings/Mod.toml"], status="modified")
        self.assertTrue(candidate)

    def test_two_documents_wait_for_a_steward(self):
        candidate, documents, reason = self.evaluate(
            ["listings/A.toml", "listings/B.toml"]
        )
        self.assertFalse(candidate)
        self.assertEqual(len(documents), 2)
        self.assertIn("2 documents", reason)

    def test_a_document_next_to_anything_else_waits(self):
        candidate, documents, reason = self.evaluate(
            ["listings/A.toml", "tools/check_schema.py"]
        )
        self.assertFalse(candidate)
        self.assertEqual(documents, ["listings/A.toml"])
        self.assertIn("tools/check_schema.py", reason)

    def test_a_change_to_the_checks_alone_waits(self):
        candidate, documents, reason = self.evaluate(["tools/check_schema.py"])
        self.assertFalse(candidate)
        self.assertEqual(documents, [])
        self.assertIn("no listing or pack document", reason)

    def test_an_empty_change_waits(self):
        candidate, documents, reason = check_scope.evaluate([])
        self.assertFalse(candidate)
        self.assertEqual(documents, [])
        self.assertIn("no file at all", reason)

    def test_the_reason_does_not_list_every_path_of_a_wide_change(self):
        paths = ["listings/A.toml"] + [f"tools/f{index}.py" for index in range(9)]
        _, _, reason = self.evaluate(paths)
        self.assertIn("and 4 more", reason)

    def test_the_index_status_file_is_not_a_document(self):
        candidate, _, _ = self.evaluate(["index-status.toml"])
        self.assertFalse(candidate)


class Removals(unittest.TestCase):

    def evaluate(self, path, status):
        return check_scope.evaluate([check_scope.Change(path, status)])

    def test_a_deleted_listing_does_not_merge_itself(self):
        candidate, documents, reason = self.evaluate("listings/Mod.toml", "removed")
        self.assertFalse(candidate)
        self.assertEqual(documents, ["listings/Mod.toml"])
        self.assertIn("index-status.toml", reason)

    def test_a_renamed_listing_does_not_merge_itself(self):
        candidate, _, reason = self.evaluate("listings/New.toml", "renamed")
        self.assertFalse(candidate)
        self.assertIn("renamed", reason)

    def test_a_deleted_pack_version_does_not_merge_itself(self):
        candidate, _, _ = self.evaluate("packs/Pack/1.0.0.toml", "removed")
        self.assertFalse(candidate)

    def test_a_status_the_api_may_grow_does_not_merge_itself(self):
        candidate, _, _ = self.evaluate("listings/Mod.toml", "copied")
        self.assertFalse(candidate)


if __name__ == "__main__":
    unittest.main()
