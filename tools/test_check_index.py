#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the rules that need the whole index.

Each case builds a small index in a temporary folder, so the rules stay tested
once this repository holds real listings.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_index

LISTING = """\
spec_version = 1
id = "{id}"
type = "{type}"
name = "{id}"
authors = ["Nobody"]
abstract = "A listing that exists only in this test."
license = "MIT"

[compatibility]
game_min = "2026.8.3.5117"

[links]
forums = "https://forums.ahwoo.com/threads/x.1/"
{extra}"""

PACK = """\
spec_version = 1
id = "{id}"
type = "modpack"
name = "{id}"
authors = ["Nobody"]
abstract = "A pack that exists only in this test."
license = "CC0-1.0"
version = "{version}"
released_at = "2026-08-05T12:00:00Z"

[compatibility]
game_min = "2026.8.3.5117"

[links]
forums = "https://forums.ahwoo.com/threads/x.1/"
{extra}"""


class IndexCase(unittest.TestCase):
    """A temporary index, written one document at a time."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.listings = self.root / "listings"
        self.packs = self.root / "packs"
        self.listings.mkdir()
        self.packs.mkdir()
        self.addCleanup(self.folder.cleanup)

    def listing(self, identifier, kind="mod", extra="", name=None):
        path = self.listings / f"{name or identifier}.toml"
        path.write_text(LISTING.format(id=identifier, type=kind, extra=extra), encoding="utf-8")
        return path

    def pack(self, identifier, version="1.0.0", extra="", folder=None):
        directory = self.packs / (folder or identifier)
        directory.mkdir(exist_ok=True)
        path = directory / f"{version}.toml"
        path.write_text(
            PACK.format(id=identifier, version=version, extra=extra), encoding="utf-8"
        )
        return path

    def load(self):
        return check_index.load_documents(self.listings, self.packs)

    def errors(self):
        entries, _ = self.load()
        return check_index.check(entries)


def entry(identifier, kind="mod", holder=None, where=None):
    """One Entry, built without touching the filesystem.
    """
    holder = holder or ("listing", identifier)
    return check_index.Entry(
        Path(where or f"listings/{identifier}.toml"),
        where or f"listings/{identifier}.toml",
        holder,
        identifier,
        {"id": identifier, "type": kind},
    )


class Collisions(IndexCase):
    def test_two_distinct_listings_do_not_collide(self):
        self.listing("Alpha")
        self.listing("Beta")
        self.assertEqual(self.errors(), [])

    def test_two_listings_differing_only_in_case_collide(self):
        errors = check_index.check_collisions([entry("MyMod"), entry("mymod")])
        self.assertEqual(len(errors), 1)
        self.assertIn("already held by", errors[0])

    def test_a_listing_and_a_pack_sharing_an_id_collide(self):
        # The namespace is global across content types, so a pack cannot take
        # the name of a mod even though they live in different folders.
        self.listing("Shared")
        self.pack("shared")
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("Shared", errors[0])

    def test_a_second_version_of_a_pack_is_not_a_collision(self):
        self.pack("Pack", "1.0.0")
        self.pack("Pack", "1.1.0")
        self.assertEqual(self.errors(), [])

    def test_many_versions_of_a_pack_are_not_a_collision(self):
        for version in ("1.0.0", "1.1.0", "2.0.0"):
            self.pack("Pack", version)
        self.assertEqual(self.errors(), [])

    def test_two_pack_folders_differing_only_in_case_collide(self):
        errors = check_index.check_collisions(
            [
                entry("Pack", "modpack", ("pack", "Pack"), "packs/Pack/1.0.0.toml"),
                entry("pack", "modpack", ("pack", "pack"), "packs/pack/1.0.0.toml"),
            ]
        )
        self.assertEqual(len(errors), 1)

    def test_a_third_holder_reports_against_the_first(self):
        errors = check_index.check_collisions(
            [entry("Same"), entry("same"), entry("SAME")]
        )
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("listings/Same.toml" in error for error in errors))

    def test_the_id_comes_from_the_path_not_from_the_document(self):
        self.listing("Declared", name="OnDisk")
        entries, _ = self.load()
        self.assertEqual(entries[0].identifier, "OnDisk")


class References(IndexCase):
    def test_a_loader_that_is_a_mod_loader_is_fine(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing("Mod", extra='\n[loader]\nid = "StarMap"\nmin = "0.4.5"\n')
        self.assertEqual(self.errors(), [])

    def test_a_loader_that_is_a_mod_is_rejected(self):
        self.listing("NotALoader")
        self.listing("Mod", extra='\n[loader]\nid = "NotALoader"\nmin = "0.4.5"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("has to be a mod-loader", errors[0])

    def test_an_unlisted_loader_is_left_alone(self):
        self.listing("Mod", extra='\n[loader]\nid = "NotListedYet"\nmin = "0.4.5"\n')
        self.assertEqual(self.errors(), [])

    def test_a_loader_reference_is_matched_case_insensitively(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing("Mod", extra='\n[loader]\nid = "starmap"\nmin = "0.4.5"\n')
        self.assertEqual(self.errors(), [])

    def test_a_dependency_on_a_mod_is_fine(self):
        self.listing("Other")
        self.listing("Mod", extra='\n[[dependencies]]\nid = "Other"\nkind = "required"\n')
        self.assertEqual(self.errors(), [])

    def test_a_dependency_on_a_loader_is_rejected(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing("Mod", extra='\n[[dependencies]]\nid = "StarMap"\nkind = "required"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("has to be a mod", errors[0])

    def test_a_dependency_on_a_pack_is_rejected(self):
        self.pack("Pack")
        self.listing("Mod", extra='\n[[dependencies]]\nid = "Pack"\nkind = "required"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("listed as a modpack", errors[0])

    def test_an_any_of_alternative_is_checked_too(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing(
            "Mod",
            extra='\n[[dependencies]]\nkind = "required"\nany_of = [{ id = "StarMap" }]\n',
        )
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("any_of[0]", errors[0])

    def test_every_any_of_alternative_is_checked(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing("AlsoALoader", kind="mod-loader")
        self.listing(
            "Mod",
            extra='\n[[dependencies]]\nkind = "required"\n'
            'any_of = [{ id = "StarMap" }, { id = "AlsoALoader" }]\n',
        )
        self.assertEqual(len(self.errors()), 2)

    def test_a_pack_pinning_a_mod_is_fine(self):
        self.listing("Mod")
        self.pack("Pack", extra='\n[[mods]]\nid = "Mod"\nversion = "1.0.0"\n')
        self.assertEqual(self.errors(), [])

    def test_a_pack_pinning_a_pack_is_rejected(self):
        self.pack("Inner")
        self.pack("Outer", extra='\n[[mods]]\nid = "Inner"\nversion = "1.0.0"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("does not nest", errors[0])

    def test_a_pack_pinning_a_pack_under_vehicles_is_rejected(self):
        self.pack("Inner")
        self.pack("Outer", extra='\n[[vehicles]]\nid = "Inner"\nversion = "1.0.0"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("vehicles[0]", errors[0])

    def test_a_pack_pinning_a_loader_is_left_alone(self):

        self.pack("Pack", extra='\n[[mods]]\nid = "StarMap"\nversion = "0.4.6"\n')
        self.listing("StarMap", kind="mod-loader")
        self.assertEqual(self.errors(), [])

    def test_a_self_reference_is_left_to_the_schema(self):
        self.listing("Mod", extra='\n[[dependencies]]\nid = "Mod"\nkind = "required"\n')
        self.assertEqual(self.errors(), [])


class Loading(IndexCase):
    def test_a_document_that_does_not_parse_is_skipped_and_named(self):
        (self.listings / "Broken.toml").write_text("id = ", encoding="utf-8")
        self.listing("Fine")
        entries, skipped = self.load()
        self.assertEqual([entry.identifier for entry in entries], ["Fine"])
        self.assertEqual(skipped, ["listings/Broken.toml"])

    def test_a_broken_document_does_not_stop_the_rules(self):
        (self.listings / "Broken.toml").write_text("id = ", encoding="utf-8")
        self.listing("Shared")
        self.pack("Shared")
        self.assertEqual(len(self.errors()), 1)

    def test_a_listing_in_a_subfolder_is_not_loaded(self):
        nested = self.listings / "nested"
        nested.mkdir()
        (nested / "Mod.toml").write_text(LISTING.format(id="Mod", type="mod", extra=""), encoding="utf-8")
        entries, _ = self.load()
        self.assertEqual(entries, [])

    def test_a_missing_folder_is_not_an_error(self):
        entries, skipped = check_index.load_documents(
            self.root / "absent", self.root / "gone"
        )
        self.assertEqual((entries, skipped), ([], []))

    def test_paths_are_reported_the_way_the_repository_reads_them(self):
        self.listing("Mod")
        entries, _ = self.load()
        self.assertEqual(entries[0].where, "listings/Mod.toml")


if __name__ == "__main__":
    unittest.main()
