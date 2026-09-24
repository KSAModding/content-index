#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the note on a listing edit that reaches a published release."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_edits
import check_release
from check_index import Entry

WHERE = "listings/Mod.toml"

LISTING = {
    "id": "Mod",
    "type": "mod",
    "compatibility": {"game_min": "2026.8"},
    "loader": {"id": "StarMap", "min": "0.4.0"},
    "dependencies": [{"id": "Lib", "kind": "required"}, {"id": "Other", "kind": "optional"}],
}

VERSIONS = {"1.0.0": {}, "1.1.0": {}}


def listing(**changes):
    document = copy.deepcopy(LISTING)
    document.update(changes)
    return document


def newest(versions):
    return max(versions)


class WhatAnEditChanges(unittest.TestCase):
    def test_each_section_the_watcher_carries_is_named(self):
        cases = (
            (listing(compatibility={"game_min": "2026.9"}), ["[compatibility]"]),
            (listing(loader={"id": "StarMap", "min": "0.5.0"}), ["[loader]"]),
            (listing(dependencies=[{"id": "Lib", "kind": "required"}]), ["[[dependencies]]"]),
        )
        for head, sections in cases:
            with self.subTest(sections=sections):
                self.assertEqual(check_edits.edited(LISTING, head), (sections, False))

    def test_a_new_loader_id_is_its_own_change(self):
        head = listing(loader={"id": "OtherLoader", "min": "0.5.0"})
        self.assertEqual(check_edits.edited(LISTING, head), ([], True))

    def test_reordered_dependencies_and_other_fields_are_no_change(self):
        head = listing(dependencies=list(reversed(LISTING["dependencies"])), description="New.")
        self.assertEqual(check_edits.edited(LISTING, head), ([], False))


class TheNote(unittest.TestCase):
    def test_it_names_the_release_the_edit_reaches(self):
        head = listing(compatibility={"game_min": "2026.9"}, dependencies=[])
        notes = check_edits.notes_for(WHERE, LISTING, head, VERSIONS, newest)
        self.assertEqual(len(notes), 1)
        self.assertIn("[compatibility] and [[dependencies]] reaches `1.1.0`", notes[0])
        self.assertIn("with the next watcher tick after the merge", notes[0])
        self.assertIn("Older releases keep their stamp", notes[0])

    def test_a_new_loader_id_reaches_only_later_releases(self):
        head = listing(loader={"id": "OtherLoader", "min": "0.5.0"})
        notes = check_edits.notes_for(WHERE, LISTING, head, VERSIONS, newest)
        self.assertEqual(len(notes), 1)
        self.assertIn("from `StarMap` to `OtherLoader`", notes[0])
        self.assertIn("only releases stamped after the merge", notes[0])

    def test_an_added_or_removed_loader_is_named_as_such(self):
        bare = listing()
        del bare["loader"]
        cases = (
            (bare, LISTING, "the new loader `StarMap` reaches only releases"),
            (LISTING, bare, "removing the loader reaches only releases"),
        )
        for base, head, text in cases:
            with self.subTest(text=text):
                notes = check_edits.notes_for(WHERE, base, head, VERSIONS, newest)
                self.assertEqual(notes, [f"{WHERE}: {text} stamped after the merge"])

    def test_nothing_stamped_yet_is_no_note(self):
        head = listing(compatibility={"game_min": "2026.9"})
        self.assertEqual(check_edits.notes_for(WHERE, LISTING, head, {}, newest), [])

    def test_no_release_to_reach_is_no_note(self):
        head = listing(compatibility={"game_min": "2026.9"})
        self.assertEqual(check_edits.notes_for(WHERE, LISTING, head, VERSIONS, lambda _: None), [])


class TheChangedListings(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.releases = Path(directory.name)
        folder = self.releases / "releases" / "Mod"
        folder.mkdir(parents=True)
        for version in VERSIONS:
            (folder / f"{version}.json").write_text(json.dumps({"version": version}), encoding="utf-8")

    def notes(self, head, base=LISTING, target=newest):
        entry = Entry(None, WHERE, "Mod", "Mod", head)
        with mock.patch.object(check_edits.check_images, "base_document", return_value=base), \
                mock.patch.object(check_edits, "load_target", return_value=target) as load:
            notes = check_edits.notes([entry], [WHERE], "HEAD^1", self.releases)
        return notes, load

    def test_the_stamped_releases_come_from_the_generated_repository(self):
        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}))
        self.assertEqual(len(notes), 1)
        self.assertIn("reaches `1.1.0`", notes[0])

    def test_an_unrelated_edit_reads_nothing(self):
        notes, load = self.notes(listing(description="New."))
        self.assertEqual(notes, [])
        load.assert_not_called()

    def test_a_new_listing_has_nothing_to_reach(self):
        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}), base=None)
        self.assertEqual(notes, [])

    def test_a_generated_repository_that_cannot_be_read_is_only_a_note(self):
        entry = Entry(None, WHERE, "Mod", "Mod", listing(compatibility={"game_min": "2026.9"}))
        with mock.patch.object(check_edits.check_images, "base_document", return_value=LISTING), \
                mock.patch.object(
                    check_edits, "load_target", side_effect=check_release.Unavailable("no checkout")
                ):
            notes = check_edits.notes([entry], [WHERE], "HEAD^1", self.releases)
        self.assertEqual(notes, [f"{WHERE}: which release this edit reaches could not be read: no checkout"])


if __name__ == "__main__":
    unittest.main()
