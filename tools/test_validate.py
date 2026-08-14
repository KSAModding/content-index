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

        for name in ("run_layout", "run_schema"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        for name in ("run_index", "run_license", "run_status"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(validate.check_index, "load_documents", lambda *a, **k: ([], []))
        patch.start()
        self.addCleanup(patch.stop)

    def run_with(self, changed, release=None):
        with mock.patch.object(
            validate, "run_release", release or passing("release")
        ):
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
            ["run_layout", "run_schema", "run_index", "run_license", "run_status", "release"],
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
        for name in ("run_index", "run_license", "run_status"):
            patch = mock.patch.object(validate, name, passing(name))
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(validate.check_index, "load_documents", lambda *a, **k: ([], []))
        patch.start()
        self.addCleanup(patch.stop)

    def run_checks(self, layout, schema, release):
        with mock.patch.object(validate, "run_layout", lambda: layout), mock.patch.object(
            validate, "run_schema", lambda: schema
        ), mock.patch.object(validate, "run_release", release):
            return validate.run_checks(check_scope.changes(["listings/Mod.toml"]))

    def test_a_schema_rejection_stops_the_archive_from_being_fetched(self):
        release = mock.Mock()
        checks = self.run_checks(
            validate.Check("layout", validate.PASS),
            validate.Check("schema", validate.REJECT, ["bad"]),
            release,
        )
        release.assert_not_called()
        self.assertEqual(checks[-1].name, "release")
        self.assertIn("has to pass layout and schema first", checks[-1].messages[0])

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
            validate.run_index(entries),
            validate.run_license(entries),
        ):
            self.assertEqual(check.outcome, validate.PASS, f"{check.name}: {check.messages}")


if __name__ == "__main__":
    unittest.main()
