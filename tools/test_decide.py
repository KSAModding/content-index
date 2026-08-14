#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for what the privileged half does about a verdict. No token, no network."""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_scope
import decide
import ownership

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github/workflows"

VERIFIED = ownership.Result(ownership.VERIFIED, "", "topic")
UNVERIFIED = ownership.Result(ownership.UNVERIFIED, "Maxi did not prove control of a/b")
UNAVAILABLE = ownership.Result(ownership.COULD_NOT_EVALUATE, "the host did not answer")

LISTING = 'id = "AutoStage"\n[releases]\ngithub = "Maxi/KSA-AutoStage"\n'


def workflow_jobs(path):
    """The job ids and display names in one workflow file, without a YAML parser."""
    ids, names = [], []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        bare = line.split("#")[0].rstrip()
        if not bare.strip():
            continue
        if not bare.startswith(" "):
            inside = bare.strip() == "jobs:"
            continue
        if not inside:
            continue
        job = re.match(r"^ {2}[\"']?([A-Za-z0-9_-]+)[\"']?:$", bare)
        if job:
            ids.append(job.group(1))
        name = re.match(r"^ {4}name:\s*(.+)$", bare)
        if name:
            names.append(name.group(1).strip().strip("\"'"))
    return ids, names


def verdict(outcome="pass", checks=(), reason="", **overrides):
    document = {
        "schema_version": 1,
        "verdict": outcome,
        "auto_merge_candidate": True,
        "pull_request": 5,
        "head_sha": "abc",
        "documents": ["listings/AutoStage.toml"],
        "scope_reason": reason,
        "checks": list(checks),
    }
    document.update(overrides)
    return document


class RecordingApi:
    """Every call this workflow would make, recorded instead of sent."""

    def __init__(self, comments=(), labels=(), reviewers=None, files=None):
        self.repository = "KSAModding/content-index"
        self.token = "app"
        self.public_token = "workflow"
        self.sent = []
        self.comments = list(comments)
        self.labels = list(labels)
        self.reviewers = reviewers or {"teams": []}
        self.files = {"listings/AutoStage.toml": LISTING} if files is None else files
        self.reads = []
        self.graphql_calls = []
        self.graphql_answer = {}
        self.order = []
        self.log = lambda message: None

    def get(self, path, **query):
        if path.endswith("/comments"):
            return self.comments
        if path.endswith("/labels"):
            return [{"name": name} for name in self.labels]
        if path.endswith("/requested_reviewers"):
            return self.reviewers
        return []

    def send(self, method, path, payload, token=None):
        self.sent.append((method, path, payload, token))
        self.order.append(f"{method} {path}")
        return {}

    def file(self, full_name, path, ref=None):
        self.reads.append((full_name, path, ref))
        return self.files.get(path)

    def graphql(self, query, variables):
        self.graphql_calls.append(variables)
        self.order.append("graphql")
        return self.graphql_answer


class Table(unittest.TestCase):
    def test_a_rejection_fails_the_status_and_explains(self):
        checks = [{"name": "schema", "outcome": "reject", "messages": ["id is not valid"]}]
        decision = decide.decide(verdict("reject", checks), True, VERIFIED)
        self.assertEqual(decision.status, "failure")
        self.assertFalse(decision.auto_merge)
        self.assertFalse(decision.needs_steward)
        self.assertIn("id is not valid", decision.comment)

    def test_a_could_not_evaluate_errors_the_status(self):
        decision = decide.decide(verdict("could-not-evaluate"), True, VERIFIED)
        self.assertEqual(decision.status, "error")
        self.assertFalse(decision.auto_merge)
        self.assertIn("sweep", decision.comment)

    def test_the_happy_path_arms_auto_merge_and_says_nothing(self):
        decision = decide.decide(verdict(), True, VERIFIED)
        self.assertEqual(decision.status, "success")
        self.assertTrue(decision.auto_merge)
        self.assertFalse(decision.needs_steward)
        self.assertIsNone(decision.comment)

    def test_a_change_that_is_not_a_candidate_waits_for_a_steward(self):
        decision = decide.decide(
            verdict(reason="the change touches 2 documents"), False, VERIFIED
        )
        self.assertEqual(decision.status, "success")
        self.assertFalse(decision.auto_merge)
        self.assertTrue(decision.needs_steward)
        self.assertIn("touches 2 documents", decision.comment)

    def test_unverified_ownership_is_green_and_waits_for_a_steward(self):
        decision = decide.decide(verdict(), True, UNVERIFIED)
        self.assertEqual(decision.status, "success")
        self.assertFalse(decision.auto_merge)
        self.assertTrue(decision.needs_steward)
        self.assertIn("did not prove control", decision.comment)

    def test_the_comment_tells_an_author_how_to_prove_it(self):
        decision = decide.decide(verdict(), True, UNVERIFIED)
        self.assertIn("ksa-index-", decision.comment)
        self.assertIn(ownership.MARKER_PATH, decision.comment)

    def test_ownership_that_could_not_be_checked_waits_too(self):
        decision = decide.decide(verdict(), True, UNAVAILABLE)
        self.assertEqual(decision.status, "success")
        self.assertFalse(decision.auto_merge)
        self.assertTrue(decision.needs_steward)

    def test_that_comment_does_not_blame_the_release_host(self):
        decision = decide.decide(
            verdict(), True, ownership.Result(ownership.COULD_NOT_EVALUATE, "it does not parse")
        )
        self.assertNotIn("reach the release host", decision.comment)
        self.assertIn("it does not parse", decision.comment)

    def test_a_passing_check_contributes_no_message(self):
        checks = [
            {"name": "schema", "outcome": "pass", "messages": ["all good"]},
            {"name": "index", "outcome": "reject", "messages": ["collides"]},
        ]
        decision = decide.decide(verdict("reject", checks), True, VERIFIED)
        self.assertNotIn("all good", decision.comment)
        self.assertIn("collides", decision.comment)

    def test_the_run_url_is_linked_when_given(self):
        decision = decide.decide(verdict("reject"), True, VERIFIED, run_url="https://x/run/1")
        self.assertIn("https://x/run/1", decision.comment)


class Agreement(unittest.TestCase):
    def test_the_matching_verdict_agrees(self):
        self.assertTrue(decide._agrees(verdict(), 5, "abc")[0])

    def test_another_pull_request_does_not(self):
        self.assertFalse(decide._agrees(verdict(pull_request=999), 5, "abc")[0])

    def test_another_head_commit_does_not(self):
        self.assertFalse(decide._agrees(verdict(head_sha="deadbeef"), 5, "abc")[0])

    def test_a_pass_that_names_no_head_commit_does_not(self):
        # Code that can rewrite the verdict could otherwise delete the key.
        self.assertFalse(decide._agrees(verdict(head_sha=None), 5, "abc")[0])

    def test_the_unprivileged_fallback_still_agrees(self):
        agrees, _ = decide._agrees(
            verdict("could-not-evaluate", head_sha=None), 5, "abc"
        )
        self.assertTrue(agrees)


class Comment(unittest.TestCase):
    def test_the_first_run_creates_one(self):
        api = RecordingApi()
        decide.upsert_comment(api, 5, "Something to say")
        methods = [(method, path) for method, path, _, _ in api.sent]
        self.assertEqual(methods, [("POST", "/issues/5/comments")])
        self.assertIn(decide.COMMENT_MARKER, api.sent[0][2]["body"])

    def test_a_later_run_edits_the_same_one(self):
        api = RecordingApi(comments=[{"id": 9, "body": f"{decide.COMMENT_MARKER}\nold"}])
        decide.upsert_comment(api, 5, "new")
        self.assertEqual([m for m, _, _, _ in api.sent], ["PATCH"])
        self.assertIn("/issues/comments/9", api.sent[0][1])

    def test_an_unchanged_comment_is_left_alone(self):
        body = f"{decide.COMMENT_MARKER}\nsame"
        api = RecordingApi(comments=[{"id": 9, "body": body}])
        decide.upsert_comment(api, 5, "same")
        self.assertEqual(api.sent, [])

    def test_nothing_to_say_and_nothing_there_posts_nothing(self):
        api = RecordingApi()
        decide.upsert_comment(api, 5, None)
        self.assertEqual(api.sent, [])

    def test_nothing_to_say_resolves_a_comment_that_is_there(self):
        api = RecordingApi(comments=[{"id": 9, "body": f"{decide.COMMENT_MARKER}\nrejected"}])
        decide.upsert_comment(api, 5, None)
        self.assertEqual([m for m, _, _, _ in api.sent], ["PATCH"])
        self.assertIn("ownership verified", api.sent[0][2]["body"])

    def test_a_foreign_comment_is_not_touched(self):
        api = RecordingApi(comments=[{"id": 9, "body": "a human said something"}])
        decide.upsert_comment(api, 5, "mine")
        self.assertEqual([m for m, _, _, _ in api.sent], ["POST"])


class Label(unittest.TestCase):
    def test_it_is_added_when_a_steward_is_needed(self):
        api = RecordingApi()
        decide.add_label(api, 5)
        self.assertEqual(api.sent[0][2], {"labels": [decide.STEWARD_LABEL]})

    def test_it_is_not_added_twice(self):
        api = RecordingApi(labels=[decide.STEWARD_LABEL])
        decide.add_label(api, 5)
        self.assertEqual(api.sent, [])

    def test_it_is_removed_on_the_way_to_a_merge(self):
        api = RecordingApi(labels=[decide.STEWARD_LABEL])
        decide.remove_label(api, 5)
        self.assertEqual([m for m, _, _, _ in api.sent], ["DELETE"])

    def test_removing_one_that_is_not_there_does_nothing(self):
        api = RecordingApi()
        decide.remove_label(api, 5)
        self.assertEqual(api.sent, [])


class Reviewers(unittest.TestCase):
    def test_the_stewards_team_is_requested(self):
        api = RecordingApi()
        decide.request_stewards(api, 5)
        self.assertEqual(api.sent[0][2], {"team_reviewers": [decide.STEWARD_TEAM]})

    def test_it_is_not_requested_twice(self):
        api = RecordingApi(reviewers={"teams": [{"slug": decide.STEWARD_TEAM}]})
        decide.request_stewards(api, 5)
        self.assertEqual(api.sent, [])

    def test_a_standing_request_is_withdrawn(self):
        api = RecordingApi(reviewers={"teams": [{"slug": decide.STEWARD_TEAM}]})
        decide.withdraw_stewards(api, 5)
        self.assertEqual([m for m, _, _, _ in api.sent], ["DELETE"])

    def test_nothing_to_withdraw(self):
        api = RecordingApi()
        decide.withdraw_stewards(api, 5)
        self.assertEqual(api.sent, [])


class RequiredCheck(unittest.TestCase):
    """A job named like the required check would satisfy it before ownership ran."""

    def jobs(self):
        ids, names = [], []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            found_ids, found_names = workflow_jobs(path)
            ids.extend(found_ids)
            names.extend(found_names)
        return ids, names

    def test_the_reader_finds_the_jobs(self):
        ids, _ = self.jobs()
        self.assertIn("verdict", ids)

    def test_no_job_carries_the_context_the_ruleset_requires(self):
        ids, names = self.jobs()
        self.assertNotIn(decide.STATUS_CONTEXT, ids)
        self.assertNotIn(decide.STATUS_CONTEXT, names)


class Status(unittest.TestCase):
    def test_it_is_posted_under_the_name_the_sweep_reads(self):
        api = RecordingApi()
        decide.post_status(api, "abc", decide.Decision("success", "validated"), "https://x/run/1")
        method, path, payload, token = api.sent[0]
        self.assertEqual((method, path), ("POST", "/statuses/abc"))
        self.assertEqual(payload["context"], decide.STATUS_CONTEXT)
        self.assertEqual(payload["state"], "success")
        self.assertEqual(token, api.public_token)

    def test_a_long_description_is_cut_to_what_github_accepts(self):
        api = RecordingApi()
        decide.post_status(api, "abc", decide.Decision("success", "x" * 200), "")
        self.assertLessEqual(len(api.sent[0][2]["description"]), 140)


class AuthoredDocument(unittest.TestCase):
    def test_it_is_read_at_the_head_commit(self):
        api = RecordingApi()
        document, problem = decide.authored_document(api, "listings/AutoStage.toml", "abc123")
        self.assertEqual(problem, "")
        self.assertEqual(document["id"], "AutoStage")
        self.assertEqual(api.reads, [(api.repository, "listings/AutoStage.toml", "abc123")])

    def test_a_document_that_is_not_there_says_so(self):
        api = RecordingApi(files={})
        document, problem = decide.authored_document(api, "listings/AutoStage.toml", "abc123")
        self.assertIsNone(document)
        self.assertIn("could not be read", problem)

    def test_a_document_that_does_not_parse_says_so(self):
        api = RecordingApi(files={"listings/AutoStage.toml": "id = \n"})
        document, problem = decide.authored_document(api, "listings/AutoStage.toml", "abc123")
        self.assertIsNone(document)
        self.assertIn("does not parse", problem)

    def test_a_host_that_did_not_answer_says_so(self):
        api = RecordingApi()
        api.file = mock.Mock(side_effect=ownership.Unavailable("HTTP 502"))
        document, problem = decide.authored_document(api, "listings/AutoStage.toml", "abc")
        self.assertIsNone(document)
        self.assertIn("502", problem)


class AutoMerge(unittest.TestCase):
    def test_a_clean_answer_is_armed(self):
        api = RecordingApi()
        self.assertTrue(decide.arm_auto_merge(api, "PR_1"))

    def test_an_error_answer_is_not(self):
        api = RecordingApi()
        api.graphql_answer = {"errors": [{"message": "auto-merge is off"}]}
        self.assertFalse(decide.arm_auto_merge(api, "PR_1"))


class Act(unittest.TestCase):
    """The whole run, with only the API replaced."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.api = RecordingApi()

        self.pull = {
            "number": 5,
            "node_id": "PR_1",
            "state": "open",
            "head": {"sha": "abc"},
            "user": {"login": "Maxi", "id": 7},
        }
        patches = [
            mock.patch.object(decide, "pull_request_for", lambda api, sha: self.pull),
            mock.patch.object(
                decide, "changed_paths",
                lambda api, number: [check_scope.Change("listings/AutoStage.toml", "added")],
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def act(self, document=None, write=True):
        path = self.root / "verdict.json"
        if write:
            path.write_text(json.dumps(document if document is not None else verdict()),
                            encoding="utf-8")
        arguments = mock.Mock(
            verdict=path, head_sha="abc", repository=self.api.repository, run_url="", dry_run=False
        )
        return decide.act(self.api, arguments)

    def statuses(self):
        return [payload for _, path, payload, _ in self.api.sent if path == "/statuses/abc"]

    def test_a_verdict_naming_another_pull_request_is_refused(self):
        self.assertEqual(self.act(verdict(pull_request=999)), 1)
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.api.graphql_calls, [])

    def test_a_verdict_naming_another_head_commit_is_refused(self):
        self.assertEqual(self.act(verdict(head_sha="deadbeef")), 1)
        self.assertEqual(self.api.sent, [])

    def test_an_added_listing_is_read_at_the_head_and_can_merge(self):
        with mock.patch.object(decide.ownership, "verify", lambda *a, **k: VERIFIED):
            self.assertEqual(self.act(), 0)
        self.assertEqual(self.api.graphql_calls, [{"id": "PR_1"}])
        self.assertEqual(self.api.reads, [(self.api.repository, "listings/AutoStage.toml", "abc")])
        self.assertEqual(self.statuses()[-1]["state"], "success")

    def test_the_check_is_held_pending_until_auto_merge_is_armed(self):
        with mock.patch.object(decide.ownership, "verify", lambda *a, **k: VERIFIED):
            self.assertEqual(self.act(), 0)
        self.assertEqual([status["state"] for status in self.statuses()], ["pending", "success"])

        posts = [index for index, call in enumerate(self.api.order) if call == "POST /statuses/abc"]
        arm = self.api.order.index("graphql")
        self.assertLess(posts[0], arm)
        self.assertGreater(posts[-1], arm)

    def test_nothing_is_held_pending_when_there_is_no_merge_to_arm(self):
        with mock.patch.object(decide.ownership, "verify", lambda *a, **k: UNVERIFIED):
            self.assertEqual(self.act(), 0)
        self.assertEqual([status["state"] for status in self.statuses()], ["success"])
        self.assertEqual(self.api.graphql_calls, [])

    def test_a_run_that_left_no_verdict_errors_the_status(self):
        self.assertEqual(self.act(write=False), 0)
        self.assertEqual(self.statuses()[0]["state"], "error")
        self.assertEqual(self.api.graphql_calls, [])

    def test_a_faked_pass_on_a_wide_change_does_not_merge(self):
        # Scope is re-derived from the API, so a faked candidate cannot merge.
        with mock.patch.object(
            decide, "changed_paths",
            lambda api, number: [
                check_scope.Change("listings/AutoStage.toml", "added"),
                check_scope.Change("tools/validate.py", "modified"),
            ],
        ):
            self.assertEqual(self.act(), 0)
        self.assertEqual(self.api.graphql_calls, [])
        self.assertTrue(
            any(payload == {"labels": [decide.STEWARD_LABEL]} for _, _, payload, _ in self.api.sent)
        )

    def test_auto_merge_that_could_not_be_armed_goes_to_a_steward(self):
        self.api.graphql_answer = {"errors": [{"message": "auto-merge is off"}]}
        with mock.patch.object(decide.ownership, "verify", lambda *a, **k: VERIFIED):
            self.assertEqual(self.act(), 0)
        self.assertEqual([status["state"] for status in self.statuses()], ["pending", "success"])
        self.assertTrue(
            any(payload == {"labels": [decide.STEWARD_LABEL]} for _, _, payload, _ in self.api.sent)
        )
        comment = [p for _, path, p, _ in self.api.sent if path.endswith("/comments")][0]
        self.assertIn("could not be armed", comment["body"])

    def test_a_rejection_leaves_a_steward_label_alone(self):
        self.api.labels = [decide.STEWARD_LABEL]
        self.assertEqual(self.act(verdict("reject")), 0)
        self.assertNotIn("DELETE", [m for m, _, _, _ in self.api.sent])

    def test_a_crash_still_leaves_a_status(self):
        arguments = mock.Mock(
            verdict=self.root / "missing.json", head_sha="abc",
            repository=self.api.repository, run_url="", dry_run=False,
        )
        with mock.patch.object(decide, "Api", lambda *a, **k: self.api), mock.patch.object(
            decide, "act", side_effect=RuntimeError("boom")
        ), mock.patch.object(decide, "parse_arguments", lambda argv: arguments):
            self.assertEqual(decide.main([]), 1)
        self.assertEqual(self.statuses()[0]["state"], "error")


if __name__ == "__main__":
    unittest.main()
