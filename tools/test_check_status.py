#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the index-status.toml check."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_index
import check_status
from test_check_index import IndexCase


class StatusCase(IndexCase):
    """The index of IndexCase, plus a status file next to it."""

    def status(self, text):
        path = self.root / "index-status.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def entries(self, *blocks):
        return self.status("\n".join(blocks) if blocks else "entries = []\n")

    def check(self, text=None):
        path = self.status(text) if text is not None else self.root / "index-status.toml"
        loaded, _ = self.load()
        return check_status.check(loaded, path=path)

    def errors(self, text=None):
        return self.check(text)[0]

    def notes(self, text=None):
        return self.check(text)[1]


def block(**fields):
    lines = ["[[entries]]"]
    lines.extend(f'{key} = "{value}"' for key, value in fields.items())
    return "\n".join(lines) + "\n"


class Absent(StatusCase):
    def test_no_status_file_at_all_is_no_error(self):
        self.listing("AutoStage")
        self.assertEqual(self.check(), ([], []))

    def test_an_empty_entries_array_is_no_error(self):
        self.listing("AutoStage")
        self.assertEqual(self.errors("entries = []\n"), [])


class Shape(StatusCase):
    def test_a_state_outside_the_three_is_rejected(self):
        self.listing("AutoStage")
        self.assertTrue(self.errors(block(id="AutoStage", state="hidden")))

    def test_an_entry_without_a_state_is_rejected(self):
        self.listing("AutoStage")
        self.assertTrue(self.errors(block(id="AutoStage")))

    def test_an_entry_without_an_id_is_rejected(self):
        self.assertTrue(self.errors(block(state="delisted")))

    def test_an_id_that_breaks_the_id_rules_is_rejected(self):
        self.assertTrue(self.errors(block(id="has space", state="delisted")))

    def test_a_reserved_name_is_rejected(self):
        self.assertTrue(self.errors(block(id="NUL", state="delisted")))

    def test_an_unknown_key_is_rejected(self):
        self.listing("AutoStage")
        self.assertTrue(self.errors(block(id="AutoStage", state="delisted", note="why")))

    def test_a_retracted_state_needs_a_version(self):
        self.pack("Pack")
        self.assertTrue(self.errors(block(id="Pack", state="retracted")))

    def test_a_whole_entry_state_takes_no_version(self):
        self.listing("AutoStage")
        self.assertTrue(self.errors(block(id="AutoStage", state="disputed", version="1.0.0")))

    def test_a_version_that_is_not_semver_is_rejected(self):
        self.pack("Pack")
        self.assertTrue(self.errors(block(id="Pack", state="retracted", version="v1")))

    def test_a_version_that_is_not_a_string_is_an_error_and_not_a_crash(self):
        """A hand-written file gets a schema message, not a Python type name."""
        self.pack("Pack")
        text = '[[entries]]\nid = "Pack"\nstate = "retracted"\nversion = ["1.0.0"]\n'
        self.assertTrue(self.errors(text))

    def test_a_since_that_is_not_a_utc_timestamp_is_rejected(self):
        self.listing("AutoStage")
        self.assertTrue(
            self.errors(block(id="AutoStage", state="delisted", since="2026-08-10"))
        )

    def test_a_bare_toml_datetime_is_accepted_as_since(self):
        self.listing("AutoStage")
        text = '[[entries]]\nid = "AutoStage"\nstate = "delisted"\nsince = 2026-08-10T00:00:00Z\n'
        self.assertEqual(self.errors(text), [])

    def test_an_empty_reason_is_rejected(self):
        self.listing("AutoStage")
        self.assertTrue(self.errors(block(id="AutoStage", state="delisted", reason="")))

    def test_a_file_that_is_not_valid_toml_is_reported(self):
        self.assertTrue(self.errors("entries = \n"))

    def test_entries_that_is_not_an_array_is_rejected(self):
        self.assertTrue(self.errors("entries = 0\n"))


class Duplicates(StatusCase):
    def test_one_id_cannot_carry_two_whole_entry_states(self):
        self.listing("AutoStage")
        self.assertTrue(
            self.errors(
                block(id="AutoStage", state="disputed") + block(id="AutoStage", state="delisted")
            )
        )

    def test_a_duplicate_is_caught_case_insensitively(self):
        self.listing("AutoStage")
        self.assertTrue(
            self.errors(
                block(id="AutoStage", state="disputed") + block(id="autostage", state="disputed")
            )
        )

    def test_one_pack_version_cannot_be_retracted_twice(self):
        self.pack("Pack")
        self.assertTrue(
            self.errors(
                block(id="Pack", state="retracted", version="1.0.0")
                + block(id="Pack", state="retracted", version="1.0.0")
            )
        )

    def test_two_versions_of_one_pack_may_each_be_retracted(self):
        self.pack("Pack", version="1.0.0")
        self.pack("Pack", version="1.1.0")
        self.assertEqual(
            self.errors(
                block(id="Pack", state="retracted", version="1.0.0")
                + block(id="Pack", state="retracted", version="1.1.0")
            ),
            [],
        )

    def test_a_pack_may_be_delisted_and_have_a_version_retracted(self):
        self.pack("Pack")
        errors, notes = self.check(
            block(id="Pack", state="delisted")
            + block(id="Pack", state="retracted", version="1.0.0")
        )
        self.assertEqual(errors, [])
        self.assertTrue(any("changes nothing" in note for note in notes))


class Resolves(StatusCase):
    def test_a_state_for_a_listing_resolves(self):
        self.listing("AutoStage")
        self.assertEqual(self.errors(block(id="AutoStage", state="delisted")), [])

    def test_a_state_for_a_pack_resolves(self):
        self.pack("Pack")
        self.assertEqual(self.errors(block(id="Pack", state="disputed")), [])

    def test_a_state_matches_its_id_case_insensitively(self):
        self.listing("MixedCase")
        self.assertEqual(self.errors(block(id="mixedcase", state="disputed")), [])

    def test_a_dangling_id_is_the_typo_this_check_exists_for(self):
        self.listing("AutoStage")
        errors = self.errors(block(id="AutoStge", state="delisted"))
        self.assertTrue(any("neither a listing nor a pack" in error for error in errors))

    def test_retracting_a_listing_is_rejected(self):
        self.listing("AutoStage")
        errors = self.errors(block(id="AutoStage", state="retracted", version="1.0.0"))
        self.assertTrue(any("only a pack version is retracted" in error for error in errors))

    def test_retracting_a_version_the_pack_does_not_have_is_rejected(self):
        self.pack("Pack", version="1.0.0")
        errors = self.errors(block(id="Pack", state="retracted", version="2.0.0"))
        self.assertTrue(any("no version 2.0.0 to retract" in error for error in errors))

    def test_a_pack_resolves_through_any_of_its_versions(self):
        self.pack("Pack", version="1.0.0")
        self.pack("Pack", version="1.1.0")
        self.assertEqual(self.errors(block(id="Pack", state="retracted", version="1.1.0")), [])


class Schema(unittest.TestCase):
    def test_the_schema_itself_is_valid(self):
        check_status.validator()


class LiveFile(unittest.TestCase):
    """The file this repository ships has to pass its own check."""

    def test_the_repositorys_own_index_status_resolves(self):
        entries, _ = check_index.load_documents()
        errors, _ = check_status.check(entries)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
