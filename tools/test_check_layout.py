#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the layout rules."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_layout
from test_check_index import LISTING, PACK


class LayoutCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.listings = self.root / "listings"
        self.packs = self.root / "packs"
        self.listings.mkdir()
        self.packs.mkdir()
        self.addCleanup(self.folder.cleanup)

    def listing(self, identifier, name=None):
        path = self.listings / (name or f"{identifier}.toml")
        path.write_text(LISTING.format(id=identifier, type="mod", extra=""), encoding="utf-8")
        return path

    def pack(self, identifier, version="1.0.0", name=None):
        directory = self.packs / identifier
        directory.mkdir(exist_ok=True)
        path = directory / (name or f"{version}.toml")
        path.write_text(PACK.format(id=identifier, version=version, extra=""), encoding="utf-8")
        return path

    def errors(self):
        return check_layout.check(self.listings, self.packs)


class Suffix(LayoutCase):
    """The builder globs '*.toml', case-sensitively on Linux."""

    def test_a_lowercase_suffix_is_the_only_accepted_one(self):
        self.listing("AutoStage")
        self.assertEqual(self.errors(), [])

    def test_an_uppercase_suffix_on_a_listing_is_rejected(self):
        self.listing("AutoStage", name="AutoStage.TOML")
        self.assertTrue(any("lowercase" in error for error in self.errors()))

    def test_a_mixed_case_suffix_on_a_listing_is_rejected(self):
        self.listing("AutoStage", name="AutoStage.Toml")
        self.assertTrue(any("lowercase" in error for error in self.errors()))

    def test_an_uppercase_suffix_on_a_pack_version_is_rejected(self):
        self.pack("Pack", name="1.0.0.TOML")
        self.assertTrue(any("lowercase" in error for error in self.errors()))

    def test_the_rest_of_the_document_is_still_checked(self):
        """A wrong suffix must not hide the other errors."""
        path = self.listings / "Wrong.TOML"
        path.write_text(LISTING.format(id="AutoStage", type="mod", extra=""), encoding="utf-8")
        errors = self.errors()
        self.assertTrue(any("lowercase" in error for error in errors))
        self.assertTrue(any("declares id" in error for error in errors))


class Placement(LayoutCase):
    def test_a_listing_in_a_subfolder_is_rejected(self):
        nested = self.listings / "deep"
        nested.mkdir()
        (nested / "AutoStage.toml").write_text(
            LISTING.format(id="AutoStage", type="mod", extra=""), encoding="utf-8"
        )
        self.assertTrue(any("no subfolders" in error for error in self.errors()))

    def test_a_pack_version_directly_under_packs_is_rejected(self):
        (self.packs / "1.0.0.toml").write_text(
            PACK.format(id="Pack", version="1.0.0", extra=""), encoding="utf-8"
        )
        self.assertTrue(any("packs/<id>/<version>.toml" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
