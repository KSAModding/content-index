#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the rules that need the whole index.

Each case builds a small index in a temporary folder, so the rules stay tested
once this repository holds real listings.
"""

import json
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

THREAD = "https://forums.ahwoo.com/threads/x.1/"


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

    def listing(self, identifier, kind="mod", extra="", name=None, forums=THREAD, abstract=None):
        path = self.listings / f"{name or identifier}.toml"
        text = LISTING.format(id=identifier, type=kind, extra=extra).replace(THREAD, forums)
        if abstract is not None:
            text = text.replace("A listing that exists only in this test.", abstract)
        path.write_text(text, encoding="utf-8")
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

    def notes(self, *documents):
        entries, _ = self.load()
        return check_index.notes(entries, documents)


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
    def test_a_successor_reference_with_canonical_case_is_fine(self):
        old = entry("OldMod")
        old.document["superseded_by"] = "NewMod"
        self.assertEqual(check_index.check_references([entry("NewMod"), old]), [])

    def test_a_successor_reference_with_noncanonical_case_is_rejected(self):
        old = entry("OldMod")
        old.document["superseded_by"] = "newmod"
        errors = check_index.check_references([entry("NewMod"), old])
        self.assertEqual(len(errors), 1)
        self.assertIn("superseded_by", errors[0])
        self.assertIn("canonical id spelling 'NewMod'", errors[0])

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

    def test_a_loader_reference_with_noncanonical_case_is_rejected(self):
        self.listing("StarMap", kind="mod-loader")
        self.listing("Mod", extra='\n[loader]\nid = "starmap"\nmin = "0.4.5"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("canonical id spelling 'StarMap'", errors[0])

    def test_a_dependency_on_a_mod_is_fine(self):
        self.listing("Other")
        self.listing("Mod", extra='\n[[dependencies]]\nid = "Other"\nkind = "required"\n')
        self.assertEqual(self.errors(), [])

    def test_a_dependency_reference_with_noncanonical_case_is_rejected(self):
        self.listing("Other")
        self.listing("Mod", extra='\n[[dependencies]]\nid = "other"\nkind = "required"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("dependencies[0]", errors[0])
        self.assertIn("canonical id spelling 'Other'", errors[0])

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

    def test_a_pack_member_with_noncanonical_case_is_rejected(self):
        self.listing("Mod")
        self.pack("Pack", extra='\n[[mods]]\nid = "mod"\nversion = "1.0.0"\n')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn("mods[0]", errors[0])
        self.assertIn("canonical id spelling 'Mod'", errors[0])

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


def pins(*pinned, section="mods"):
    return "".join(
        f'\n[[{section}]]\nid = "{identifier}"\nversion = "{version}"\n'
        for identifier, version in pinned
    )


class MemberCase(IndexCase):
    """A temporary index beside a release folder of the generated repository."""

    def setUp(self):
        super().setUp()
        self.releases = self.root / "releases"
        self.releases.mkdir()

    def stamp(self, identifier, version, **fields):
        folder = self.releases / identifier
        folder.mkdir(exist_ok=True)
        (folder / f"{version}.json").write_text(
            json.dumps({"id": identifier, "version": version, **fields}), encoding="utf-8"
        )

    def members(self, *pinned, delisted=(), section="mods"):
        self.pack("Pack", extra=pins(*pinned, section=section))
        entries, _ = self.load()
        return check_index.check_members(
            entries, ["packs/Pack/1.0.0.toml"], set(delisted), self.releases
        )


class Members(MemberCase):
    """The pins of a changed pack version, against the listings and the stamped releases."""

    def test_listed_members_at_stamped_releases_pass(self):
        self.listing("Alpha")
        self.listing("Beta")
        self.stamp("Alpha", "1.0.0")
        self.stamp("Beta", "0.4.0")
        self.assertEqual(self.members(("Alpha", "1.0.0"), ("Beta", "0.4.0")), [])

    def test_an_unlisted_member_is_refused_by_name(self):
        errors = self.members(("NotListed", "1.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("packs/Pack/1.0.0.toml: mods[0]: 'NotListed' is not a listed mod", errors[0])

    def test_every_refused_member_is_named(self):
        self.listing("Alpha")
        self.stamp("Alpha", "1.0.0")
        errors = self.members(("Missing", "1.0.0"), ("Alpha", "1.0.0"), ("Gone", "2.0.0"))
        self.assertEqual(len(errors), 2)
        self.assertIn("mods[0]: 'Missing'", errors[0])
        self.assertIn("mods[2]: 'Gone'", errors[1])

    def test_a_loader_is_refused(self):
        self.listing("StarMap", kind="mod-loader")
        self.stamp("StarMap", "0.4.6")
        errors = self.members(("StarMap", "0.4.6"))
        self.assertEqual(len(errors), 1)
        self.assertIn("listed as a mod-loader", errors[0])

    def test_a_delisted_member_is_refused(self):
        self.listing("Alpha")
        self.stamp("Alpha", "1.0.0")
        errors = self.members(("Alpha", "1.0.0"), delisted={"alpha"})
        self.assertEqual(len(errors), 1)
        self.assertIn("'Alpha' is delisted", errors[0])

    def test_a_version_with_no_stamped_release_is_refused(self):
        self.listing("Alpha")
        self.stamp("Alpha", "1.0.0")
        errors = self.members(("Alpha", "1.1.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("'Alpha' has no stamped release 1.1.0", errors[0])

    def test_a_yanked_release_is_refused(self):
        self.listing("Alpha")
        self.stamp("Alpha", "1.0.0", yanked=True, yanked_reason="broken")
        errors = self.members(("Alpha", "1.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("'Alpha' 1.0.0 is yanked", errors[0])

    def test_a_version_that_is_not_semver_is_left_to_the_schema(self):
        self.listing("Alpha")
        (self.root / "outside.json").write_text("[]", encoding="utf-8")
        self.assertEqual(self.members(("Alpha", "../../outside")), [])

    def test_a_release_that_is_not_an_object_raises_instead_of_refusing(self):
        self.listing("Alpha")
        (self.releases / "Alpha").mkdir()
        (self.releases / "Alpha" / "1.0.0.json").write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.members(("Alpha", "1.0.0"))

    def test_a_vehicle_or_save_is_refused_until_its_type_exists(self):
        for section in ("vehicles", "saves"):
            with self.subTest(section=section):
                errors = self.members(("Craft", "1.0.0"), section=section)
                self.assertEqual(len(errors), 1)
                self.assertIn(f"{section}[0]: 'Craft' cannot be pinned", errors[0])

    def test_a_nested_pack_is_left_to_the_reference_check(self):
        self.pack("Inner")
        self.assertEqual(self.members(("Inner", "1.0.0")), [])

    def test_an_unchanged_pack_version_is_not_checked(self):
        self.pack("Pack", extra=pins(("Gone", "1.0.0")))
        entries, _ = self.load()
        self.assertEqual(check_index.check_members(entries, [], set(), self.root / "absent"), [])

    def test_a_missing_release_folder_raises_instead_of_refusing(self):
        self.pack("Pack", extra=pins(("Alpha", "1.0.0")))
        entries, _ = self.load()
        with self.assertRaises(OSError):
            check_index.check_members(entries, ["packs/Pack/1.0.0.toml"], set(), self.root / "absent")

    def test_dependencies_that_are_not_a_list_raise_instead_of_refusing(self):
        self.listing("Alpha")
        self.stamp("Alpha", "1.0.0", dependencies={"id": "Beta"})
        with self.assertRaises(ValueError):
            self.members(("Alpha", "1.0.0"))


def requires(identifier, kind="required", **bounds):
    return {"id": identifier, "kind": kind, "source": "authored", **bounds}


class CompleteSet(MemberCase):
    """The pins of a changed pack version meet each other's stamped dependencies."""

    def setUp(self):
        super().setUp()
        for identifier in ("Alpha", "Beta", "Gamma"):
            self.listing(identifier)
        self.stamp("Beta", "1.0.0")
        self.stamp("Beta", "2.0.0")
        self.stamp("Beta", "2.1.0-rc.1")
        self.stamp("Gamma", "1.0.0")

    def needs(self, *dependencies):
        self.stamp("Alpha", "1.0.0", dependencies=list(dependencies))

    def test_a_required_dependency_pinned_in_its_bounds_passes(self):
        self.needs(requires("Beta", min="1.0.0", max="2.0.0"))
        for version in ("1.0.0", "2.0.0"):
            with self.subTest(version=version):
                self.assertEqual(self.members(("Alpha", "1.0.0"), ("Beta", version)), [])

    def test_a_missing_required_dependency_is_named_with_the_release_that_needs_it(self):
        self.needs(requires("Beta", min="2.0.0"))
        self.assertEqual(
            self.members(("Alpha", "1.0.0")),
            [
                "packs/Pack/1.0.0.toml: mods[0]: 'Alpha' 1.0.0 requires 'Beta' 2.0.0 or newer, "
                "and the pack does not pin it"
            ],
        )

    def test_a_required_dependency_pinned_outside_its_bounds_is_refused(self):
        cases = (
            ({"min": "2.0.0"}, "1.0.0", "'Beta' 2.0.0 or newer"),
            ({"max": "1.0.0"}, "2.0.0", "'Beta' 1.0.0 or older"),
            ({"min": "1.0.0", "max": "2.0.0"}, "2.1.0-rc.1", "'Beta' 1.0.0 to 2.0.0"),
            ({"min": "2.1.0"}, "2.1.0-rc.1", "'Beta' 2.1.0 or newer"),
        )
        for bounds, version, wanted in cases:
            with self.subTest(bounds=bounds, version=version):
                self.needs(requires("Beta", **bounds))
                errors = self.members(("Alpha", "1.0.0"), ("Beta", version))
                self.assertEqual(len(errors), 1)
                self.assertIn(f"requires {wanted}, and the pack pins 'Beta' {version}", errors[0])

    def test_a_derived_dependency_counts_like_an_authored_one(self):
        self.needs({"id": "Beta", "kind": "required", "source": "derived"})
        errors = self.members(("Alpha", "1.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("requires 'Beta', and the pack does not pin it", errors[0])

    def test_one_member_of_an_any_of_is_enough(self):
        self.needs({"kind": "required", "any_of": [{"id": "Beta", "min": "2.0.0"}, {"id": "Gamma"}]})
        self.assertEqual(self.members(("Alpha", "1.0.0"), ("Gamma", "1.0.0")), [])

    def test_an_any_of_with_no_member_pinned_names_every_choice(self):
        self.needs({"kind": "required", "any_of": [{"id": "Beta", "min": "2.0.0"}, {"id": "Gamma"}]})
        errors = self.members(("Alpha", "1.0.0"), ("Beta", "1.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn(
            "requires one of 'Beta' 2.0.0 or newer, 'Gamma', and the pack pins 'Beta' 1.0.0", errors[0]
        )

    def test_a_conflict_with_another_member_is_refused(self):
        self.needs(requires("Beta", kind="conflict"))
        self.assertEqual(
            self.members(("Alpha", "1.0.0"), ("Beta", "1.0.0")),
            [
                "packs/Pack/1.0.0.toml: mods[0]: 'Alpha' 1.0.0 conflicts with 'Beta', "
                "and the pack pins 'Beta' 1.0.0"
            ],
        )

    def test_a_conflict_outside_its_bounds_passes(self):
        self.needs(requires("Beta", kind="conflict", max="1.0.0"))
        self.assertEqual(self.members(("Alpha", "1.0.0"), ("Beta", "2.0.0")), [])

    def test_a_conflict_with_the_member_itself_is_not_another_member(self):
        self.needs(requires("Alpha", kind="conflict"))
        self.assertEqual(self.members(("Alpha", "1.0.0")), [])

    def test_a_conflict_with_a_mod_the_pack_does_not_pin_passes(self):
        self.needs(requires("Beta", kind="conflict"))
        self.assertEqual(self.members(("Alpha", "1.0.0")), [])

    def test_only_required_dependencies_have_to_be_pinned(self):
        self.needs(*(requires("Beta", kind=kind) for kind in ("optional", "recommends", "suggests")))
        self.assertEqual(self.members(("Alpha", "1.0.0")), [])

    def test_a_refused_pin_still_counts_as_pinned(self):
        self.needs(requires("Beta", min="3.0.0"))
        errors = self.members(("Alpha", "1.0.0"), ("Beta", "3.0.0"))
        self.assertEqual(len(errors), 1)
        self.assertIn("'Beta' has no stamped release 3.0.0", errors[0])


class Forums(IndexCase):
    def test_the_same_thread_under_two_url_forms_is_noted(self):
        self.listing("Alpha", forums="https://forums.ahwoo.com/threads/alpha.783/")
        self.listing(
            "Beta",
            forums="https://forums.ahwoo.com/forums/kitten-space-agency/mod-releases/beta.783/page-2",
        )
        notes = self.notes("listings/Beta.toml")
        self.assertEqual(len(notes), 1)
        self.assertIn("listings/Beta.toml: links.forums: thread 783", notes[0])
        self.assertIn("forums thread of listings/Alpha.toml", notes[0])
        self.assertEqual(self.errors(), [])

    def test_the_index_php_form_names_the_same_thread(self):
        self.listing("Alpha", forums="https://forums.ahwoo.com/threads/783/")
        self.listing("Beta", forums="https://forums.ahwoo.com/index.php?threads/beta.783/")
        self.assertEqual(len(self.notes("listings/Beta.toml")), 1)

    def test_two_different_threads_are_fine(self):
        self.listing("Alpha", forums="https://forums.ahwoo.com/threads/alpha.783/")
        self.listing("Beta", forums="https://forums.ahwoo.com/threads/alpha.784/")
        self.assertEqual(self.notes("listings/Beta.toml"), [])

    def test_an_edit_of_the_listing_that_owns_the_thread_is_fine(self):
        self.listing("Alpha", forums="https://forums.ahwoo.com/threads/alpha.783/")
        self.assertEqual(self.notes("listings/Alpha.toml"), [])

    def test_every_other_listing_on_the_thread_is_named(self):
        for identifier in ("Alpha", "Beta", "Gamma"):
            self.listing(identifier)
        notes = self.notes("listings/Gamma.toml")
        self.assertEqual(len(notes), 1)
        self.assertIn("listings/Alpha.toml, listings/Beta.toml", notes[0])

    def test_versions_of_one_pack_share_their_thread(self):
        self.pack("Pack", "1.0.0")
        self.pack("Pack", "1.1.0")
        self.assertEqual(self.notes("packs/Pack/1.1.0.toml"), [])

    def test_an_unchanged_document_is_not_noted(self):
        self.listing("Alpha")
        self.listing("Beta")
        self.assertEqual(self.notes(), [])

    def test_a_link_the_schema_refuses_is_not_compared(self):
        self.listing("Alpha", forums="https://forums.ahwoo.com/")
        self.listing("Beta", forums="https://forums.ahwoo.com/")
        self.assertEqual(self.notes("listings/Beta.toml"), [])

    def test_a_schema_rule_with_no_thread_id_is_reported(self):
        schema = self.root / "schema.json"
        schema.write_text('{"$defs": {"forumsUrl": {"pattern": "^https://"}}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            check_index.thread_pattern(schema)


class Abstracts(IndexCase):
    def test_an_abstract_of_280_characters_is_fine(self):
        self.listing("Mod", abstract="a" * 280)
        self.assertEqual(self.notes("listings/Mod.toml"), [])

    def test_an_abstract_of_281_characters_is_noted(self):
        self.listing("Mod", abstract="a" * 281)
        notes = self.notes("listings/Mod.toml")
        self.assertEqual(len(notes), 1)
        self.assertIn("listings/Mod.toml: abstract: 281 characters is longer than 280", notes[0])
        self.assertEqual(self.errors(), [])

    def test_an_unchanged_document_is_not_noted(self):
        self.listing("Mod", abstract="a" * 281)
        self.assertEqual(self.notes(), [])


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
