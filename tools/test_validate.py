#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the validation run and the verdict it leaves.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_scope
import validate


class Worst(unittest.TestCase):
    def test_nothing_is_a_pass(self):
        self.assertEqual(validate.worst([]), validate.PASS)

    def test_all_passing_is_a_pass(self):
        self.assertEqual(validate.worst([validate.PASS, validate.PASS]), validate.PASS)

    def test_one_rejection_decides(self):
        self.assertEqual(
            validate.worst([validate.PASS, validate.REJECT]), validate.REJECT
        )

    def test_a_rejection_outranks_a_could_not_evaluate(self):
        self.assertEqual(
            validate.worst([validate.COULD_NOT_EVALUATE, validate.REJECT]),
            validate.REJECT,
        )

    def test_a_could_not_evaluate_outranks_a_pass(self):
        self.assertEqual(
            validate.worst([validate.PASS, validate.COULD_NOT_EVALUATE]),
            validate.COULD_NOT_EVALUATE,
        )


class NextPage(unittest.TestCase):
    def test_a_header_with_a_next_link(self):
        header = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=9>; rel="last"'
        self.assertEqual(validate._next_page(header), "https://api.github.com/x?page=2")

    def test_a_header_with_no_next_link(self):
        self.assertIsNone(
            validate._next_page('<https://api.github.com/x?page=1>; rel="prev"')
        )

    def test_an_empty_header(self):
        self.assertIsNone(validate._next_page(""))
        self.assertIsNone(validate._next_page(None))


class Summary(unittest.TestCase):
    def test_the_verdict_and_the_scope_both_appear(self):
        text = validate.summarise(
            {
                "verdict": "reject",
                "auto_merge_candidate": False,
                "scope_reason": "the change also touches tools/x.py",
                "checks": [{"name": "schema", "outcome": "reject", "messages": ["bad"]}],
            }
        )
        self.assertIn("reject", text)
        self.assertIn("Auto-merge candidate: no", text)
        self.assertIn("tools/x.py", text)
        self.assertIn("bad", text)

    def test_a_check_with_nothing_to_say_still_appears(self):
        text = validate.summarise(
            {
                "verdict": "pass",
                "auto_merge_candidate": True,
                "scope_reason": "",
                "checks": [{"name": "layout", "outcome": "pass", "messages": []}],
            }
        )
        self.assertIn("layout", text)
        self.assertIn("nothing to report", text)


def passing(name):
    return lambda *args, **kwargs: validate.Check(name, validate.PASS)


class Run(unittest.TestCase):
    """main(), with the checks themselves stood in for.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.output = Path(self.folder.name) / "verdict.json"
        self.addCleanup(self.folder.cleanup)

        for name in ("run_layout", "run_schema", "run_tags", "run_packs"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        for name in ("run_index", "run_license", "run_status", "run_images"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(validate.check_index, "load_documents", lambda *a, **k: ([], []))
        patch.start()
        self.addCleanup(patch.stop)

    def run_with(self, changed, release=None):
        with mock.patch.object(
            validate, "run_release", release or passing("release")
        ), mock.patch.object(validate, "run_image_fetch", passing("run_image_fetch")):
            code = validate.main(
                ["--changed", *changed, "--output", str(self.output)]
            )
        return code, json.loads(self.output.read_text(encoding="utf-8"))

    def test_a_single_listing_passes_and_is_a_candidate(self):
        code, verdict = self.run_with(["listings/Mod.toml"])
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.PASS)
        self.assertTrue(verdict["auto_merge_candidate"])
        self.assertEqual(verdict["documents"], ["listings/Mod.toml"])

    def test_a_wide_change_is_valid_but_not_a_candidate(self):
        code, verdict = self.run_with(["listings/Mod.toml", "tools/check_schema.py"])
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.PASS)
        self.assertFalse(verdict["auto_merge_candidate"])
        self.assertIn("tools/check_schema.py", verdict["scope_reason"])

    def test_a_rejection_turns_the_job_red(self):
        rejecting = lambda *a, **k: validate.Check("release", validate.REJECT, ["no"])
        code, verdict = self.run_with(["listings/Mod.toml"], release=rejecting)
        self.assertEqual(code, 1)
        self.assertEqual(verdict["verdict"], validate.REJECT)

    def test_a_could_not_evaluate_leaves_the_job_green(self):
        undecided = lambda *a, **k: validate.Check(
            "release", validate.COULD_NOT_EVALUATE, ["the host is down"]
        )
        code, verdict = self.run_with(["listings/Mod.toml"], release=undecided)
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.COULD_NOT_EVALUATE)
        self.assertTrue(verdict["auto_merge_candidate"])

    def test_the_verdict_carries_its_own_version(self):
        _, verdict = self.run_with(["listings/Mod.toml"])
        self.assertEqual(verdict["schema_version"], validate.VERDICT_SCHEMA_VERSION)

    def test_every_check_appears_in_the_verdict(self):
        _, verdict = self.run_with(["listings/Mod.toml"])
        names = [check["name"] for check in verdict["checks"]]
        self.assertEqual(
            names,
            [
                "run_layout",
                "run_schema",
                "run_tags",
                "run_packs",
                "run_index",
                "run_license",
                "run_status",
                "run_images",
                "run_image_fetch",
                "release",
            ],
        )

    def test_the_archive_inspection_can_be_left_out(self):
        with mock.patch.object(validate, "run_release") as never:
            validate.main(["--changed", "listings/Mod.toml", "--skip-release", "--output", str(self.output)])
        never.assert_not_called()

    def test_unreadable_changed_files_reach_no_verdict(self):
        with mock.patch.object(validate, "changed_paths", side_effect=OSError("boom")):
            code = validate.main(
                ["--pull-request", "7", "--repository", "a/b", "--output", str(self.output)]
            )
        verdict = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.COULD_NOT_EVALUATE)
        self.assertFalse(verdict["auto_merge_candidate"])
        self.assertIn("boom", verdict["scope_reason"])


class NoFourthState(unittest.TestCase):
    """Every failure has to land in one of the three outcomes.
    """

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.output = Path(self.folder.name) / "verdict.json"
        self.addCleanup(self.folder.cleanup)

    def test_a_check_that_raises_becomes_a_could_not_evaluate(self):
        with mock.patch.object(validate, "run_schema", side_effect=ValueError("bad schema")):
            code = validate.main(
                ["--changed", "listings/Mod.toml", "--skip-release", "--output", str(self.output)]
            )
        verdict = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.COULD_NOT_EVALUATE)
        self.assertFalse(verdict["auto_merge_candidate"])
        self.assertIn("bad schema", verdict["checks"][0]["messages"][0])

    def test_a_verdict_is_written_even_then(self):
        with mock.patch.object(validate, "run_layout", side_effect=RuntimeError("boom")):
            validate.main(
                ["--changed", "listings/Mod.toml", "--skip-release", "--output", str(self.output)]
            )
        self.assertTrue(self.output.is_file())


class ShortCircuit(unittest.TestCase):
    """The inspection hands the document to the stamper.

    The stamper reads fields the schema has not vouched for yet, so a rejected
    document must not reach it.
    """

    def setUp(self):
        for name in ("run_index", "run_license", "run_status", "run_images"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(validate.check_index, "load_documents", lambda *a, **k: ([], []))
        patch.start()
        self.addCleanup(patch.stop)

    def run_checks(self, layout, schema, release, fetch=None):
        with mock.patch.object(validate, "run_layout", lambda: layout), mock.patch.object(
            validate, "run_schema", lambda: schema
        ), mock.patch.object(validate, "run_tags", passing("tags")), mock.patch.object(
            validate, "run_release", release
        ), mock.patch.object(validate, "run_image_fetch", fetch or passing("image fetch")):
            return validate.run_checks(check_scope.changes(["listings/Mod.toml"]))

    def test_a_schema_rejection_stops_the_archive_from_being_fetched(self):
        release = mock.Mock()
        checks = self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.REJECT, ["bad"]),
            release,
        )
        release.assert_not_called()
        self.assertEqual([check.name for check in checks[-2:]], ["image fetch", "release"])
        for check in checks[-2:]:
            self.assertIn("has to pass layout and schema first", check.messages[0])

    def test_a_schema_rejection_stops_the_images_from_being_fetched(self):
        fetch = mock.Mock()
        self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.REJECT, ["bad"]),
            mock.Mock(),
            fetch,
        )
        fetch.assert_not_called()

    def test_a_clean_document_reaches_the_image_fetch(self):
        fetch = mock.Mock(return_value=validate.Check("image fetch", validate.PASS))
        self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.PASS),
            mock.Mock(return_value=validate.Check("release", validate.PASS)),
            fetch,
        )
        fetch.assert_called_once_with(["listings/Mod.toml"], None)

    def test_a_layout_rejection_stops_it_too(self):
        release = mock.Mock()
        self.run_checks(
            validate.Check("layout", validate.REJECT, ["wrong place"]),
            validate.Check("schema", validate.PASS),
            release,
        )
        release.assert_not_called()

    def test_a_clean_document_reaches_the_archive_inspection(self):
        release = mock.Mock(return_value=validate.Check("release", validate.PASS))
        self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.PASS),
            release,
        )
        release.assert_called_once()

    def test_the_run_still_rejects(self):
        checks = self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.REJECT, ["bad"]),
            mock.Mock(),
        )
        self.assertEqual(validate.worst([check.outcome for check in checks]), validate.REJECT)


class ChangedPaths(unittest.TestCase):
    """The API answer is data, and its shape is not guaranteed by anything here."""

    def answer(self, payload, link=""):
        return mock.patch.object(validate, "_api", return_value=(payload, link))

    def test_the_status_is_carried_through(self):
        with self.answer([{"filename": "listings/Mod.toml", "status": "removed"}]):
            changes = validate.changed_paths("a/b", 1, None)
        self.assertEqual(changes, [check_scope.Change("listings/Mod.toml", "removed")])

    def test_a_rename_carries_its_previous_path(self):
        with self.answer(
            [{
                "filename": "archive/1.0.0.toml",
                "previous_filename": "packs/Starter/1.0.0.toml",
                "status": "renamed",
            }]
        ):
            changes = validate.changed_paths("a/b", 1, None)
        self.assertEqual(changes[0].previous_path, "packs/Starter/1.0.0.toml")

    def test_a_missing_status_reads_as_a_modification(self):
        with self.answer([{"filename": "listings/Mod.toml"}]):
            changes = validate.changed_paths("a/b", 1, None)
        self.assertEqual(changes[0].status, "modified")

    def test_an_answer_that_is_not_a_list_is_reported_not_raised_raw(self):
        with self.answer({"message": "Not Found"}):
            with self.assertRaises(ValueError):
                validate.changed_paths("a/b", 1, None)

    def test_an_entry_with_no_filename_is_reported(self):
        with self.answer([{"status": "added"}]):
            with self.assertRaises(ValueError):
                validate.changed_paths("a/b", 1, None)

    def test_a_malformed_answer_reaches_the_could_not_evaluate_path(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "verdict.json"
            with self.answer({"message": "Not Found"}):
                code = validate.main(
                    ["--pull-request", "7", "--repository", "a/b", "--output", str(output)]
                )
            verdict = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(verdict["verdict"], validate.COULD_NOT_EVALUATE)


class ReleaseWiring(unittest.TestCase):
    def test_no_documents_means_no_archive_is_fetched(self):
        with mock.patch.object(validate.check_release, "inspect_paths") as never:
            check = validate.run_release([])
        never.assert_not_called()
        self.assertEqual(check.outcome, validate.PASS)

    def test_a_missing_stamper_is_a_could_not_evaluate(self):
        # The checkout being absent says nothing about the listing, so it must
        # not reject one.
        with mock.patch.object(
            validate.check_release,
            "inspect_paths",
            side_effect=validate.check_release.Unavailable("no stamper"),
        ):
            check = validate.run_release(["listings/Mod.toml"])
        self.assertEqual(check.outcome, validate.COULD_NOT_EVALUATE)
        self.assertIn("no stamper", check.messages[0])

    def test_the_worst_outcome_across_documents_wins(self):
        results = {
            str(validate.ROOT / "listings/A.toml"): validate.check_release.Outcome(
                validate.PASS, ["fine"]
            ),
            str(validate.ROOT / "listings/B.toml"): validate.check_release.Outcome(
                validate.REJECT, ["broken"]
            ),
        }
        with mock.patch.object(validate.check_release, "inspect_paths", return_value=results):
            check = validate.run_release(["listings/A.toml", "listings/B.toml"])
        self.assertEqual(check.outcome, validate.REJECT)
        self.assertTrue(any("listings/B.toml" in message for message in check.messages))


class ImageWiring(unittest.TestCase):
    def entry(self, where, document):
        return validate.check_index.Entry(None, where, ("listing", where), "Mod", document)

    def test_warnings_are_reported_only_for_the_changed_documents(self):
        unreferenced = {"images": {"description": [{"id": "shot"}]}}
        entries = [self.entry("listings/A.toml", unreferenced), self.entry("listings/B.toml", unreferenced)]
        check = validate.run_images(entries, ["listings/B.toml"])
        self.assertEqual(check.outcome, validate.PASS)
        self.assertEqual(len(check.messages), 1)
        self.assertTrue(check.messages[0].startswith("listings/B.toml: "))

    def test_an_icon_that_is_not_square_passes_with_a_note(self):
        entries = [self.entry("listings/A.toml", {"images": {"icon": {"width": 1280, "height": 640}}})]
        check = validate.run_images(entries, ["listings/A.toml"])
        self.assertEqual(check.outcome, validate.PASS)
        self.assertEqual(
            check.messages,
            ["listings/A.toml: images.icon: the icon is 1280 by 640 pixels, so clients show the square from 320,0 to 960,640"],
        )

    def test_a_broken_rule_rejects_in_any_document(self):
        entries = [self.entry("listings/A.toml", {"description": "![x](ksa-image:missing)"})]
        self.assertEqual(validate.run_images(entries, []).outcome, validate.REJECT)

    def test_no_documents_means_no_image_is_fetched(self):
        with mock.patch.object(validate.check_images, "inspect_path") as never:
            check = validate.run_image_fetch([])
        never.assert_not_called()
        self.assertEqual(check.outcome, validate.PASS)

    def test_the_worst_outcome_across_documents_wins(self):
        answers = {
            "listings/A.toml": (validate.COULD_NOT_EVALUATE, ["slow"]),
            "listings/B.toml": (validate.PASS, ["fine"]),
        }
        with mock.patch.object(
            validate.check_images, "inspect_path", side_effect=lambda path, base: answers[path]
        ) as inspect:
            check = validate.run_image_fetch(["listings/A.toml", "listings/B.toml"], "HEAD^1")
        self.assertEqual(check.outcome, validate.COULD_NOT_EVALUATE)
        self.assertEqual(check.messages, ["slow", "fine"])
        inspect.assert_any_call("listings/A.toml", "HEAD^1")

    def test_the_base_reaches_the_checks(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(
            validate, "run_checks", return_value=[validate.Check("x", validate.PASS)]
        ) as run:
            validate.main(["--changed", "listings/Mod.toml", "--base", "HEAD^1", "--output", str(Path(folder) / "v.json")])
        self.assertEqual(run.call_args.kwargs["base"], "HEAD^1")


class TagWiring(unittest.TestCase):
    def test_changed_documents_reach_the_tag_check(self):
        with mock.patch.object(validate.check_tags, "check", return_value=([], ["note"])) as check:
            result = validate.run_tags(["listings/Mod.toml"])
        check.assert_called_once_with([validate.ROOT / "listings/Mod.toml"])
        self.assertEqual(result.outcome, validate.PASS)
        self.assertEqual(result.messages, ["note"])

    def test_invalid_vocabulary_rejects(self):
        with mock.patch.object(validate.check_tags, "check", return_value=(["bad"], [])):
            result = validate.run_tags([])
        self.assertEqual(result.outcome, validate.REJECT)

    def test_a_schema_rejection_stops_document_inspection(self):
        tags = mock.Mock(return_value=validate.Check("tags", validate.PASS))
        with mock.patch.object(validate, "run_layout", passing("layout")), mock.patch.object(
            validate, "run_schema", lambda: validate.Check("schema", validate.REJECT)
        ), mock.patch.object(validate, "run_tags", tags), mock.patch.object(
            validate, "run_packs", passing("packs")
        ), mock.patch.object(
            validate.check_index, "load_documents", return_value=([], [])
        ), mock.patch.object(validate, "run_index", passing("index")), mock.patch.object(
            validate, "run_license", passing("license")
        ), mock.patch.object(validate, "run_status", passing("status")):
            validate.run_checks(check_scope.changes(["listings/Mod.toml"]), skip_release=True)
        tags.assert_called_once_with(["listings/Mod.toml"], inspect_documents=False)


class IndexWiring(unittest.TestCase):
    def test_notes_on_changed_documents_do_not_reject(self):
        with mock.patch.object(validate.check_index, "check", return_value=[]), mock.patch.object(
            validate.check_index, "notes", return_value=["note"]
        ) as notes:
            result = validate.run_index([], documents=["listings/Mod.toml"])
        notes.assert_called_once_with([], ["listings/Mod.toml"])
        self.assertEqual(result.outcome, validate.PASS)
        self.assertEqual(result.messages, ["note"])


class RealRepository(unittest.TestCase):
    """This repository, run against its own gate.

    Its documents failing it would block every listing.
    """

    def test_the_repository_passes_its_own_checks(self):
        entries, skipped = validate.check_index.load_documents()
        self.assertEqual(skipped, [])
        for check in (
            validate.run_layout(),
            validate.run_schema(),
            validate.run_packs([]),
            validate.run_index(entries),
            validate.run_license(entries),
            validate.run_tags([]),
            validate.run_images(entries),
        ):
            self.assertEqual(check.outcome, validate.PASS, f"{check.name}: {check.messages}")



if __name__ == "__main__":
    unittest.main()
