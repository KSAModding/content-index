#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the image rules of a document and the outcome of fetching its images.
"""

import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_images
import images

ICON = {
    "url": "https://example.invalid/icon.png",
    "sha256": "a" * 64,
    "width": 512,
    "height": 512,
    "size": 1000,
}


def shot(identifier, **changes):
    record = {
        "id": identifier,
        "url": f"https://example.invalid/{identifier}.png",
        "sha256": "b" * 64,
        "width": 1600,
        "height": 900,
        "size": 2000,
    }
    record.update(changes)
    return record


def document(icon=None, shots=(), description=None):
    table = {}
    if icon is not None:
        table["icon"] = icon
    if shots:
        table["description"] = list(shots)
    result = {"id": "Mod", "images": table}
    if description is None:
        description = "".join(f"![{record['id']}](ksa-image:{record['id']})\n" for record in shots)
    result["description"] = description
    return result


def failing(failures):
    """A verify that raises the exception mapped to a record's url, and passes the rest."""

    def verify(record, role):
        failure = failures.get(record["url"])
        if failure is not None:
            raise failure

    return verify


class DocumentRules(unittest.TestCase):
    def check(self, document):
        errors = []
        notes = []
        check_images.check_document("listings/Mod.toml", document, errors, notes)
        return errors, notes

    def test_a_clean_document_adds_nothing(self):
        self.assertEqual(self.check(document(ICON, [shot("a"), shot("b")])), ([], []))

    def test_an_icon_that_is_not_square_is_a_note(self):
        errors, notes = self.check(document({**ICON, "width": 1280, "height": 640}))
        self.assertEqual(errors, [])
        self.assertEqual(
            notes,
            ["listings/Mod.toml: images.icon: the icon is 1280 by 640 pixels, so clients show the square from 320,0 to 960,640"],
        )

    def test_the_note_for_a_tall_icon_with_an_odd_difference(self):
        _, notes = self.check(document({**ICON, "width": 256, "height": 511}))
        self.assertEqual(
            notes,
            ["listings/Mod.toml: images.icon: the icon is 256 by 511 pixels, so clients show the square from 0,127 to 256,383"],
        )

    def test_an_icon_whose_shorter_side_is_above_the_limit(self):
        errors, notes = self.check(document({**ICON, "width": 2048, "height": 1025}))
        self.assertEqual(
            errors,
            [
                "listings/Mod.toml: images.icon: 2048 by 1025 pixels is outside the limits: "
                "the shorter side 256 to 1024, the longer side at most 2 times the shorter side"
            ],
        )
        self.assertEqual(notes, [])

    def test_an_icon_longer_than_twice_its_shorter_side(self):
        errors, notes = self.check(document({**ICON, "width": 1500, "height": 500}))
        self.assertEqual(
            errors,
            [
                "listings/Mod.toml: images.icon: 1500 by 500 pixels is outside the limits: "
                "the shorter side 256 to 1024, the longer side at most 2 times the shorter side"
            ],
        )
        self.assertEqual(notes, [])

    def test_an_icon_whose_shorter_side_is_at_the_limit(self):
        errors, notes = self.check(document({**ICON, "width": 2048, "height": 1024}))
        self.assertEqual(errors, [])
        self.assertEqual(
            notes,
            ["listings/Mod.toml: images.icon: the icon is 2048 by 1024 pixels, so clients show the square from 512,0 to 1536,1024"],
        )

    def test_the_limits_of_each_side_are_left_to_the_schema(self):
        for width, height in ((128, 4096), (2049, 2049), (1025, 3000)):
            with self.subTest(width=width, height=height):
                self.assertEqual(self.check(document({**ICON, "width": width, "height": height})), ([], []))

    def test_two_description_images_with_the_same_id(self):
        errors, _ = self.check(document(shots=[shot("a"), shot("a")], description="![x](ksa-image:a)"))
        self.assertEqual(
            errors,
            ["listings/Mod.toml: images.description[1]: id 'a' is already used by images.description[0]"],
        )

    def test_ids_that_differ_only_in_case_are_two_ids(self):
        errors, _ = self.check(document(shots=[shot("a"), shot("A")]))
        self.assertEqual(errors, [])

    def test_wrong_types_are_left_to_the_schema(self):
        self.check({"images": {"icon": {"width": "512", "height": 512}, "description": [{"id": 3}]}})


class InspectDocument(unittest.TestCase):
    def inspect(self, current, base=None, failures=None):
        return check_images.inspect_document(
            "listings/Mod.toml", current, base, verify=failing(failures or {})
        )

    def test_matching_images_pass(self):
        outcome, messages = self.inspect(document(ICON, [shot("a")]))
        self.assertEqual(outcome, check_images.PASS)
        self.assertEqual(messages, ["listings/Mod.toml: 2 image(s) match their records"])

    def test_a_document_without_images_passes_quietly(self):
        self.assertEqual(self.inspect({"id": "Mod"}), (check_images.PASS, []))

    def test_a_new_record_that_does_not_match_rejects(self):
        outcome, messages = self.inspect(
            document(ICON), failures={ICON["url"]: images.Invalid("sha256 is a and the bytes show b")}
        )
        self.assertEqual(outcome, check_images.REJECT)
        self.assertIn("images.icon: sha256 is a and the bytes show b", messages[0])

    def test_a_new_record_whose_host_does_not_answer_is_could_not_evaluate(self):
        outcome, _ = self.inspect(
            document(ICON), failures={ICON["url"]: images.Unavailable("timed out")}
        )
        self.assertEqual(outcome, check_images.COULD_NOT_EVALUATE)

    def test_a_rejection_outranks_a_could_not_evaluate(self):
        outcome, _ = self.inspect(
            document(ICON, [shot("a")]),
            failures={
                ICON["url"]: images.Unavailable("timed out"),
                shot("a")["url"]: images.Invalid("HTTP 404"),
            },
        )
        self.assertEqual(outcome, check_images.REJECT)

    def test_an_edit_that_keeps_a_dead_unchanged_image_only_warns(self):
        base = document(ICON, [shot("a")])
        edited = {**base, "abstract": "A corrected abstract."}
        outcome, messages = self.inspect(
            edited, base, failures={shot("a")["url"]: images.Invalid("answered HTTP 404")}
        )
        self.assertEqual(outcome, check_images.PASS)
        self.assertTrue(any("unchanged from the base branch" in message for message in messages))

    def test_an_unchanged_record_whose_host_is_down_only_warns(self):
        base = document(ICON)
        outcome, _ = self.inspect(base, base, failures={ICON["url"]: images.Unavailable("timed out")})
        self.assertEqual(outcome, check_images.PASS)

    def test_a_changed_record_that_fails_rejects(self):
        base = document(ICON)
        edited = document({**ICON, "sha256": "c" * 64})
        outcome, _ = self.inspect(edited, base, failures={ICON["url"]: images.Invalid("sha256 differs")})
        self.assertEqual(outcome, check_images.REJECT)

    def test_a_digest_that_only_changes_case_is_unchanged(self):
        base = document(ICON)
        edited = document({**ICON, "sha256": "A" * 64})
        outcome, _ = self.inspect(edited, base, failures={ICON["url"]: images.Invalid("gone")})
        self.assertEqual(outcome, check_images.PASS)

    def test_reordered_description_images_are_unchanged(self):
        base = document(shots=[shot("a"), shot("b")])
        edited = document(shots=[shot("b"), shot("a")])
        outcome, _ = self.inspect(edited, base, failures={shot("a")["url"]: images.Invalid("gone")})
        self.assertEqual(outcome, check_images.PASS)

    def test_a_record_that_took_the_id_of_another_is_new(self):
        base = document(shots=[shot("a")])
        edited = document(shots=[shot("a", url="https://example.invalid/other.png")])
        outcome, _ = self.inspect(
            edited, base, failures={"https://example.invalid/other.png": images.Invalid("gone")}
        )
        self.assertEqual(outcome, check_images.REJECT)

    def test_an_unreadable_base_turns_a_rejection_into_could_not_evaluate(self):
        outcome, messages = self.inspect(
            document(ICON), check_images.UNREADABLE, failures={ICON["url"]: images.Invalid("gone")}
        )
        self.assertEqual(outcome, check_images.COULD_NOT_EVALUATE)
        self.assertIn("base branch could not be read", messages[0])

    def test_a_fetch_that_raises_something_else_is_could_not_evaluate(self):
        outcome, messages = self.inspect(document(ICON), failures={ICON["url"]: KeyError("url")})
        self.assertEqual(outcome, check_images.COULD_NOT_EVALUATE)
        self.assertIn("behaved unexpectedly", messages[0])


class BaseDocument(unittest.TestCase):
    def git(self, answers):
        calls = []

        def run(*arguments):
            calls.append(arguments)
            return answers.get(arguments[0])

        return run, calls

    def test_no_base_means_every_record_is_new(self):
        run, calls = self.git({})
        self.assertIsNone(check_images.base_document(None, "listings/Mod.toml", git=run))
        self.assertEqual(calls, [])

    def test_a_revision_that_does_not_exist_is_unreadable(self):
        run, _ = self.git({})
        self.assertIs(check_images.base_document("HEAD^1", "listings/Mod.toml", git=run), check_images.UNREADABLE)

    def test_a_revision_that_looks_like_an_option_is_never_passed_to_git(self):
        run, calls = self.git({"rev-parse": "abc\n"})
        self.assertIs(check_images.base_document("--output=x", "listings/Mod.toml", git=run), check_images.UNREADABLE)
        self.assertEqual(calls, [])

    def test_a_document_that_is_not_on_the_base_is_new(self):
        run, _ = self.git({"rev-parse": "abc\n"})
        self.assertIsNone(check_images.base_document("HEAD^1", "listings/Mod.toml", git=run))

    def test_the_base_document_is_parsed(self):
        run, _ = self.git({"rev-parse": "abc\n", "cat-file": "", "show": 'id = "Mod"\n'})
        self.assertEqual(check_images.base_document("HEAD^1", "listings/Mod.toml", git=run), {"id": "Mod"})

    def test_the_repository_reads_its_own_head(self):
        found = check_images.base_document("HEAD", "listings/StarMap.toml")
        if found is check_images.UNREADABLE:
            self.skipTest("this checkout carries no git history")
        self.assertEqual(found["id"], "StarMap")


class InspectPath(unittest.TestCase):
    def test_a_document_that_is_not_there_is_not_fetched(self):
        outcome, messages = check_images.inspect_path("listings/NotThere.toml")
        self.assertEqual(outcome, check_images.PASS)
        self.assertIn("not there", messages[0])


class Main(unittest.TestCase):
    def test_a_document_outside_the_repository_is_a_usage_error(self):
        outside = str(check_images.ROOT.parent / "outside.toml")
        with mock.patch("sys.stderr", io.StringIO()) as stderr, self.assertRaises(SystemExit) as stop:
            check_images.main([outside])
        self.assertEqual(stop.exception.code, 2)
        self.assertIn("is not in this repository", stderr.getvalue())


class RealRepository(unittest.TestCase):
    def test_the_repository_passes_its_own_image_rules(self):
        self.assertEqual(check_images.main([]), 0)


if __name__ == "__main__":
    unittest.main()
