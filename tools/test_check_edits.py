#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the note on a listing edit that reaches a published release."""

import copy
import datetime
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

STAMPED = {"loader": {"id": "StarMap", "min": "0.4.0", "source": "authored"}}

VERSIONS = {"1.0.0": dict(STAMPED), "1.1.0": dict(STAMPED)}

NOW = datetime.datetime(2026, 10, 4, tzinfo=datetime.timezone.utc)


def listing(**changes):
    document = copy.deepcopy(LISTING)
    document.update(changes)
    return document


def newest(versions):
    return max(versions)


def running(bound, now):
    return bound == "2026.10"


RULES = check_edits.Rules(newest, running)


def notes_for(head, base=LISTING, versions=VERSIONS, rules=RULES, state=None):
    return check_edits.notes_for(WHERE, base, head, versions, rules, state, NOW)


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

    def test_a_dependency_with_a_date_in_it_is_compared_too(self):
        dated = [{"id": "Lib", "kind": "required", "since": datetime.date(2026, 9, 1)}]
        self.assertEqual(
            check_edits.edited(listing(dependencies=dated), LISTING), (["[[dependencies]]"], False)
        )


class TheNote(unittest.TestCase):
    def test_it_names_the_release_the_edit_reaches_and_when(self):
        notes = notes_for(listing(compatibility={"game_min": "2026.9"}, dependencies=[]))
        self.assertEqual(len(notes), 1)
        self.assertIn("[compatibility] and [[dependencies]] reaches `1.1.0`", notes[0])
        self.assertIn("with the next watcher tick after the merge", notes[0])
        self.assertIn("adds a release of this listing is open in content-index-releases", notes[0])
        self.assertIn("lands in that release instead", notes[0])
        self.assertIn("Older releases keep their stamp", notes[0])
        self.assertIn("an amendment pull request to content-index-releases", notes[0])

    def test_it_names_no_fixed_waiting_time(self):
        note = notes_for(listing(compatibility={"game_min": "2026.9"}))[0]
        for text in ("24", "hour", "day"):
            with self.subTest(text=text):
                self.assertNotIn(text, note)

    def test_a_game_max_month_that_is_not_over_waits_alone(self):
        head = listing(compatibility={"game_min": "2026.8", "game_max": "2026.10"})
        note = notes_for(head)[0]
        self.assertIn("The `game_max` month 2026.10 is not over yet", note)
        self.assertIn("the rest of the change does not wait", note)

    def test_a_game_max_month_that_is_over_does_not_wait(self):
        head = listing(compatibility={"game_min": "2026.8", "game_max": "2026.9"})
        self.assertNotIn("not over yet", notes_for(head)[0])

    def test_an_unchanged_game_max_month_does_not_wait(self):
        base = listing(compatibility={"game_min": "2026.8", "game_max": "2026.10"})
        head = listing(compatibility={"game_min": "2026.9", "game_max": "2026.10"})
        self.assertNotIn("not over yet", notes_for(head, base=base)[0])

    def test_a_new_loader_id_reaches_only_later_releases(self):
        head = listing(loader={"id": "OtherLoader", "min": "0.5.0"})
        notes = notes_for(head)
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
                self.assertEqual(notes_for(head, base=base), [f"{WHERE}: {text} stamped after the merge"])

    def test_loader_bounds_do_not_reach_a_release_stamped_with_another_loader(self):
        versions = {"1.1.0": {"loader": {"id": "OldLoader", "min": "1.0.0"}}}
        head = listing(loader={"id": "StarMap", "min": "0.5.0"}, dependencies=[])
        notes = notes_for(head, versions=versions)
        self.assertEqual(len(notes), 2)
        self.assertIn("the change to [[dependencies]] reaches `1.1.0`", notes[0])
        self.assertIn("[loader] bounds reaches only releases stamped after the merge", notes[1])
        self.assertIn("was stamped with the loader `OldLoader`", notes[1])

    def test_loader_bounds_alone_still_say_that_stamped_releases_keep_their_stamp(self):
        versions = {"1.1.0": {"loader": {"id": "OldLoader", "min": "1.0.0"}}}
        notes = notes_for(listing(loader={"id": "StarMap", "min": "0.5.0"}), versions=versions)
        self.assertEqual(len(notes), 1)
        self.assertIn("[loader] bounds reaches only releases stamped after the merge", notes[0])
        self.assertIn("Stamped releases keep their stamp", notes[0])
        self.assertIn("an amendment pull request to content-index-releases", notes[0])

    def test_nothing_stamped_yet_reaches_the_first_stamp(self):
        notes = notes_for(listing(compatibility={"game_min": "2026.9"}), versions={})
        self.assertEqual(len(notes), 1)
        self.assertIn("no release of this listing is stamped yet", notes[0])
        self.assertIn("the first release stamped after the merge", notes[0])

    def test_only_yanked_or_dev_releases_get_nothing(self):
        rules = check_edits.Rules(lambda _: None, running)
        notes = notes_for(listing(compatibility={"game_min": "2026.9"}), rules=rules)
        self.assertEqual(len(notes), 1)
        self.assertIn("every stamped release of this listing is yanked or `dev`", notes[0])
        self.assertIn("only releases stamped after the merge", notes[0])

    def test_a_disputed_listing_gets_the_edit_once_the_dispute_ends(self):
        notes = notes_for(listing(compatibility={"game_min": "2026.9"}), state="disputed")
        self.assertEqual(len(notes), 1)
        self.assertIn("while the listing is disputed", notes[0])
        self.assertIn("Once the dispute ends", notes[0])
        self.assertIn("with the next watcher tick, unless a release was stamped first", notes[0])
        self.assertIn("Stamped releases keep their stamp", notes[0])
        self.assertNotIn("`1.1.0`", notes[0])

    def test_a_delisted_listing_gets_no_edit_while_it_is_delisted(self):
        notes = notes_for(listing(compatibility={"game_min": "2026.9"}), state="delisted")
        self.assertEqual(len(notes), 1)
        self.assertIn("while the listing is delisted", notes[0])
        self.assertIn("Stamped releases keep their stamp", notes[0])
        self.assertIn("an amendment pull request to content-index-releases", notes[0])


class TheChangedListings(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.releases = Path(directory.name)
        folder = self.releases / "releases" / "Mod"
        folder.mkdir(parents=True)
        for version, document in VERSIONS.items():
            (folder / f"{version}.json").write_text(json.dumps(document), encoding="utf-8")
        self.status = self.releases / "index-status.toml"

    def notes(self, head, base=LISTING, rules=RULES):
        entry = Entry(None, WHERE, "Mod", "Mod", head)
        with mock.patch.object(check_edits.check_images, "base_document", return_value=base), \
                mock.patch.object(check_edits, "load_rules", return_value=rules) as load:
            notes = check_edits.notes([entry], [WHERE], "HEAD^1", self.releases, self.status)
        return notes, load

    def test_the_stamped_releases_come_from_the_generated_repository(self):
        notes, load = self.notes(listing(compatibility={"game_min": "2026.9"}))
        self.assertEqual(len(notes), 1)
        self.assertIn("reaches `1.1.0`", notes[0])
        load.assert_called_once_with(self.releases)

    def test_an_unrelated_edit_reads_nothing(self):
        notes, load = self.notes(listing(description="New."))
        self.assertEqual(notes, [])
        load.assert_not_called()

    def test_a_new_listing_has_nothing_to_reach(self):
        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}), base=None)
        self.assertEqual(notes, [])

    def test_the_state_comes_from_the_index_status(self):
        self.status.write_text(
            '[[entries]]\nid = "mod"\nstate = "disputed"\nsince = 2026-09-01T00:00:00Z\nreason = "x"\n',
            encoding="utf-8",
        )
        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}))
        self.assertIn("while the listing is disputed", notes[0])

    def test_an_unreadable_index_status_gives_no_state(self):
        self.status.write_text("entries = [", encoding="utf-8")
        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}))
        self.assertIn("reaches `1.1.0`", notes[0])

    def test_a_release_file_name_that_is_no_version_is_only_a_note(self):
        def target(versions):
            raise ValueError("not a version")

        notes, _ = self.notes(listing(compatibility={"game_min": "2026.9"}), rules=check_edits.Rules(target, running))
        self.assertEqual(notes, [f"{WHERE}: which release this edit reaches could not be read: not a version"])

    def test_a_generated_repository_that_cannot_be_read_is_only_a_note(self):
        entry = Entry(None, WHERE, "Mod", "Mod", listing(compatibility={"game_min": "2026.9"}))
        with mock.patch.object(check_edits.check_images, "base_document", return_value=LISTING), \
                mock.patch.object(
                    check_edits, "load_rules", side_effect=check_release.Unavailable("no checkout")
                ):
            notes = check_edits.notes([entry], [WHERE], "HEAD^1", self.releases, self.status)
        self.assertEqual(notes, [f"{WHERE}: which release this edit reaches could not be read: no checkout"])

    def test_a_changed_loader_id_keeps_its_note_when_the_releases_cannot_be_read(self):
        head = listing(compatibility={"game_min": "2026.9"}, loader={"id": "Other", "min": "0.5.0"})
        entry = Entry(None, WHERE, "Mod", "Mod", head)
        with mock.patch.object(check_edits.check_images, "base_document", return_value=LISTING), \
                mock.patch.object(
                    check_edits, "load_rules", side_effect=check_release.Unavailable("no checkout")
                ):
            notes = check_edits.notes([entry], [WHERE], "HEAD^1", self.releases, self.status)
        self.assertEqual(notes, [
            f"{WHERE}: which release this edit reaches could not be read: no checkout",
            f"{WHERE}: the loader changes from `StarMap` to `Other`, which reaches only releases "
            "stamped after the merge",
        ])

    def test_a_changed_loader_id_alone_reads_no_releases(self):
        notes, load = self.notes(listing(loader={"id": "Other", "min": "0.5.0"}))
        self.assertEqual(len(notes), 1)
        self.assertIn("from `StarMap` to `Other`", notes[0])
        load.assert_not_called()

    def test_a_checkout_without_the_listing_edit_rules_is_only_a_note(self):
        tools = self.releases / "tools"
        tools.mkdir()
        (tools / "stamp_release.py").write_text("", encoding="utf-8")
        (tools / "hosts.py").write_text("", encoding="utf-8")
        # Only this empty checkout may be importable, not the one the other tests load.
        path = [entry for entry in sys.path if not (Path(entry) / "stamp_release.py").is_file()]
        with mock.patch.dict(sys.modules), mock.patch.object(sys, "path", path):
            for name in ("stamp_release", "hosts", "listing_edit"):
                sys.modules.pop(name, None)
            with self.assertRaises(check_release.Unavailable) as raised:
                check_edits.load_rules(self.releases)
        self.assertIn("the listing edit rules of the generated repository do not import", str(raised.exception))


class TheRulesOfTheGeneratedRepository(unittest.TestCase):
    """The real rules, when the checkout of the generated repository carries them."""

    def setUp(self):
        try:
            self.rules = check_edits.load_rules()
        except check_release.Unavailable as error:
            self.skipTest(str(error))

    def test_the_target_is_the_newest_release_that_is_neither_yanked_nor_dev(self):
        versions = {
            "1.0.0": {},
            "1.1.0": {},
            "1.2.0": {"yanked": True},
            "1.3.0-dev.1": {"release_status": "dev"},
        }
        self.assertEqual(self.rules.target(versions), "1.1.0")

    def test_a_game_max_month_runs_until_it_is_over(self):
        self.assertTrue(self.rules.month_running("2026.10", NOW))
        self.assertFalse(self.rules.month_running("2026.9", NOW))
        self.assertFalse(self.rules.month_running("2026.9.22.5482", NOW))


if __name__ == "__main__":
    unittest.main()
