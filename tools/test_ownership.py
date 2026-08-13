#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the three ownership proofs. No token, no network."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ownership

LISTING = {
    "id": "AutoStage",
    "releases": {"github": "Maxi/KSA-AutoStage"},
    "links": {"repository": "https://github.com/Maxi/KSA-AutoStage"},
}


class FakeApi:
    """The three lookups, answered from what a test set up."""

    def __init__(self, repositories=None, topics=None, files=None, unavailable=()):
        self.repositories = repositories or {}
        self.topic_map = topics or {}
        self.files = files or {}
        self.unavailable = set(unavailable)

    def repository(self, full_name):
        if "repository" in self.unavailable:
            raise ownership.Unavailable("the host did not answer")
        return self.repositories.get(full_name)

    def topics(self, full_name):
        if "topics" in self.unavailable:
            raise ownership.Unavailable("the host did not answer")
        return self.topic_map.get(full_name, [])

    def file(self, full_name, path):
        if "file" in self.unavailable:
            raise ownership.Unavailable("the host did not answer")
        return self.files.get((full_name, path))


def repository(full_name, owner_id=1, fork=False):
    return {"full_name": full_name, "fork": fork, "owner": {"id": owner_id}}


class Url(unittest.TestCase):
    def test_a_plain_repository_url(self):
        self.assertEqual(
            ownership.github_repository("https://github.com/Maxi/KSA-AutoStage"),
            "Maxi/KSA-AutoStage",
        )

    def test_a_git_suffix_is_dropped(self):
        self.assertEqual(
            ownership.github_repository("https://github.com/Maxi/KSA-AutoStage.git"),
            "Maxi/KSA-AutoStage",
        )

    def test_another_host_is_not_a_repository(self):
        self.assertIsNone(ownership.github_repository("https://gitlab.com/Maxi/Thing"))

    def test_an_owner_without_a_repository_is_not_one(self):
        self.assertIsNone(ownership.github_repository("https://github.com/Maxi"))


class Authority(unittest.TestCase):
    def test_one_host_is_the_authority(self):
        kind, target, _ = ownership.authority(LISTING)
        self.assertEqual((kind, target), ("github", "Maxi/KSA-AutoStage"))

    def test_several_hosts_need_an_authority_key(self):
        document = {"releases": {"github": "a/b", "spacedock": 42, "authority": "github"}}
        self.assertEqual(ownership.authority(document)[:2], ("github", "a/b"))

    def test_several_hosts_without_one_resolve_to_nothing(self):
        document = {"releases": {"github": "a/b", "spacedock": 42}}
        self.assertIsNone(ownership.authority(document)[0])

    def test_no_releases_section_falls_back_to_the_repository_link(self):
        document = {"links": {"repository": "https://github.com/Maxi/Thing"}}
        self.assertEqual(ownership.authority(document)[:2], ("github", "Maxi/Thing"))

    def test_a_spacedock_authority_has_no_proof(self):
        document = {"releases": {"spacedock": 4253}}
        kind, _, reason = ownership.authority(document)
        self.assertEqual(kind, "spacedock")
        self.assertIn("no ownership proof", reason)

    def test_nothing_to_bind_to(self):
        self.assertIsNone(ownership.authority({"id": "X"})[0])


class Proofs(unittest.TestCase):
    def verify(self, api, login="Maxi", author_id=1, document=None):
        return ownership.verify(document or LISTING, login, author_id, api)

    def test_the_owner_id_is_the_fast_path(self):
        api = FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=7)})
        result = self.verify(api, author_id=7)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id")

    def test_a_topic_naming_the_login_verifies(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            topics={"Maxi/KSA-AutoStage": ["ksa-index-maxi"]},
        )
        result = self.verify(api, login="Maxi", author_id=1)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "topic")

    def test_the_topic_comparison_is_lowercased(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            topics={"Maxi/KSA-AutoStage": ["ksa-index-mixedcase"]},
        )
        self.assertEqual(self.verify(api, login="MixedCase").state, ownership.VERIFIED)

    def test_a_marker_file_naming_the_login_verifies(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            files={
                ("Maxi/KSA-AutoStage", ownership.MARKER_PATH): 'id = "AutoStage"\nlogin = "Maxi"\n'
            },
        )
        result = self.verify(api)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "marker file")

    def test_a_marker_naming_another_login_does_not(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            files={
                ("Maxi/KSA-AutoStage", ownership.MARKER_PATH): 'id = "AutoStage"\nlogin = "Someone"\n'
            },
        )
        self.assertEqual(self.verify(api).state, ownership.UNVERIFIED)

    def test_a_marker_naming_another_listing_does_not(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            files={
                ("Maxi/KSA-AutoStage", ownership.MARKER_PATH): 'id = "Other"\nlogin = "Maxi"\n'
            },
        )
        self.assertEqual(self.verify(api).state, ownership.UNVERIFIED)

    def test_a_fork_is_rejected_even_when_the_owner_matches(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=7, fork=True)}
        )
        result = self.verify(api, author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("fork", result.reason)

    def test_a_repository_that_moved_does_not_verify(self):
        api = FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/Renamed", owner_id=7)})
        result = self.verify(api, author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("stale", result.reason)

    def test_a_repository_that_is_not_there(self):
        self.assertEqual(self.verify(FakeApi()).state, ownership.UNVERIFIED)

    def test_no_proof_at_all(self):
        api = FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("did not prove control", result.reason)

    def test_a_host_that_cannot_answer_is_not_a_rejection(self):
        for stage in ("repository", "topics", "file"):
            api = FakeApi(
                {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
                unavailable=[stage],
            )
            self.assertEqual(
                self.verify(api).state, ownership.COULD_NOT_EVALUATE, stage
            )

    def test_a_spacedock_listing_waits_for_a_steward(self):
        result = self.verify(FakeApi(), document={"id": "X", "releases": {"spacedock": 1}})
        self.assertEqual(result.state, ownership.UNVERIFIED)


if __name__ == "__main__":
    unittest.main()
