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

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def errors(self):
        return check_layout.check(self.listings, self.packs)


def document(identifier, content_type):
    return f'id = "{identifier}"\ntype = "{content_type}"\n'


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
    def test_a_listing_id_mismatch_names_the_required_file(self):
        self.listing("ExampleMod", name="OldExampleMod.toml")

        self.assertEqual(
            self.errors(),
            [
                "listings/OldExampleMod.toml: declares id "
                "'ExampleMod', so the file name must be 'ExampleMod.toml'"
            ],
        )

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


class MissingKeys(LayoutCase):
    """A key that is not there is named as missing, with the line to write."""

    def test_a_listing_without_type_and_id(self):
        (self.listings / "MyMod.toml").write_text('name = "My Mod"\n', encoding="utf-8")
        self.assertEqual(
            self.errors(),
            [
                'listings/MyMod.toml: type is missing; write type = "mod" or type = "mod-loader"',
                'listings/MyMod.toml: id is missing; write id = "MyMod", the same as the file name',
            ],
        )

    def test_a_pack_without_type_id_and_version(self):
        (self.packs / "my-pack").mkdir()
        (self.packs / "my-pack" / "1.0.0.toml").write_text('name = "My Pack"\n', encoding="utf-8")
        self.assertEqual(
            self.errors(),
            [
                'packs/my-pack/1.0.0.toml: type is missing; write type = "modpack"',
                'packs/my-pack/1.0.0.toml: id is missing; write id = "my-pack", the same as the folder name',
                'packs/my-pack/1.0.0.toml: version is missing; write version = "1.0.0", the same as the file name',
            ],
        )

    def test_no_message_names_none(self):
        (self.listings / "MyMod.toml").write_text("", encoding="utf-8")
        (self.packs / "my-pack").mkdir()
        (self.packs / "my-pack" / "1.0.0.toml").write_text("", encoding="utf-8")
        for error in self.errors():
            with self.subTest(error=error):
                self.assertNotIn("None", error)

    def test_a_wrong_type_still_names_the_value(self):
        (self.listings / "MyMod.toml").write_text('id = "MyMod"\ntype = "addon"\n', encoding="utf-8")
        self.assertEqual(self.errors(), ["listings/MyMod.toml: type 'addon' is not one of mod, mod-loader"])

    def test_a_vehicle_without_type_and_id(self):
        self.write("vehicles/ExampleRover.toml", 'name = "Example Rover"\n')
        self.assertEqual(
            self.errors(),
            [
                'vehicles/ExampleRover.toml: type is missing; write type = "vehicle"',
                'vehicles/ExampleRover.toml: id is missing; write id = "ExampleRover", the same as the file name',
            ],
        )


class VehiclesAndSaves(LayoutCase):
    """RFC 0085: vehicles/<id>.toml and saves/<id>.toml, one document each, with no subfolders."""

    def test_a_vehicle_and_a_save_in_their_folders(self):
        self.write("vehicles/ExampleRover.toml", document("ExampleRover", "vehicle"))
        self.write("saves/ExampleBase.toml", document("ExampleBase", "save"))
        self.listing("ExampleMod")
        self.pack("ExamplePack")
        self.assertEqual(self.errors(), [])
        self.assertEqual(check_layout.counted(self.listings, self.packs), 4)

    def test_a_document_in_the_folder_of_another_type(self):
        cases = (
            ("listings", "vehicle", "vehicles"),
            ("saves", "vehicle", "vehicles"),
            ("vehicles", "save", "saves"),
            ("vehicles", "mod", "listings"),
            ("saves", "mod-loader", "listings"),
        )
        for folder, content_type, home in cases:
            with self.subTest(folder=folder, type=content_type):
                path = self.write(f"{folder}/ExampleRover.toml", document("ExampleRover", content_type))
                self.assertEqual(
                    self.errors(),
                    [f"{folder}/ExampleRover.toml: type '{content_type}' belongs under {home}/<id>.toml"],
                )
                path.unlink()

    def test_an_unknown_type_names_the_type_of_the_folder(self):
        self.write("saves/ExampleBase.toml", document("ExampleBase", "addon"))
        self.assertEqual(self.errors(), ["saves/ExampleBase.toml: type 'addon' is not one of save"])

    def test_a_vehicle_in_a_pack_folder(self):
        self.write("packs/ExampleRover/1.0.0.toml", document("ExampleRover", "vehicle") + 'version = "1.0.0"\n')
        self.assertEqual(
            self.errors(),
            ["packs/ExampleRover/1.0.0.toml: type 'vehicle' belongs under vehicles/<id>.toml"],
        )

    def test_a_pack_in_the_vehicle_folder(self):
        self.write("vehicles/ExamplePack.toml", document("ExamplePack", "modpack"))
        self.assertEqual(
            self.errors(),
            ["vehicles/ExamplePack.toml: type 'modpack' belongs under packs/<id>/<version>.toml"],
        )

    def test_a_subfolder_is_rejected(self):
        for folder, content_type in (("vehicles", "vehicle"), ("saves", "save")):
            with self.subTest(folder=folder):
                path = self.write(f"{folder}/deep/ExampleRover.toml", document("ExampleRover", content_type))
                self.assertEqual(
                    self.errors(),
                    [f"{folder}/deep/ExampleRover.toml: {folder}/ holds no subfolders, one document per {content_type}"],
                )
                self.assertEqual(check_layout.counted(self.listings, self.packs), 0)
                path.unlink()

    def test_the_file_name_is_the_id(self):
        self.write("saves/OldBase.toml", document("ExampleBase", "save"))
        self.assertEqual(
            self.errors(),
            ["saves/OldBase.toml: declares id 'ExampleBase', so the file name must be 'ExampleBase.toml'"],
        )

    def test_an_uppercase_suffix_is_rejected(self):
        self.write("vehicles/ExampleRover.TOML", document("ExampleRover", "vehicle"))
        self.assertTrue(any("lowercase" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
