#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the ownership proofs. No token, no network."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_scope
import ownership

LISTING = {
    "id": "AutoStage",
    "releases": {"github": "Maxi/KSA-AutoStage"},
    "links": {"repository": "https://github.com/Maxi/KSA-AutoStage"},
}


class FakeApi:
    """The four lookups, answered from what a test set up."""

    def __init__(
        self, repositories=None, topics=None, files=None, spacedock=None, unavailable=()
    ):
        self.repositories = repositories or {}
        self.topic_map = topics or {}
        self.files = files or {}
        self.spacedock = spacedock or {}
        self.unavailable = set(unavailable)
        self.asked = []  # so a test can say a host was never asked

    def repository(self, full_name):
        self.asked.append(full_name)
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

    def spacedock_mod(self, mod_id):
        self.asked.append(f"spacedock:{mod_id}")
        if "spacedock" in self.unavailable:
            raise ownership.Unavailable("SpaceDock did not answer")
        return self.spacedock.get(mod_id)


def repository(full_name, owner_id=1, fork=False, login="Maxi", kind="User"):
    return {
        "full_name": full_name,
        "fork": fork,
        "owner": {"id": owner_id, "login": login, "type": kind},
    }


def organization(full_name="Maxi/KSA-AutoStage", fork=False):
    return {full_name: repository(full_name, owner_id=50, fork=fork, login="Maxi", kind="Organization")}


def spacedock_mod(source_code="https://github.com/Maxi/KSA-AutoStage", mod_id=4253, **fields):
    """What SpaceDock's mod API answers, trimmed to what the check reads."""
    return {
        "id": mod_id,
        "game_id": ownership.SPACEDOCK_GAME_ID,
        "author": "Maxi",
        "source_code": source_code,
        **fields,
    }


SPACEDOCK_LISTING = {"id": "AutoStage", "releases": {"spacedock": 4253}}


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

    def test_a_name_github_cannot_carry_is_not_one(self):
        # Such a name would otherwise reach the GitHub API path unquoted.
        for url in (
            "https://github.com/Maxi/Bad Name",
            "https://github.com/Maxi/M\u00f6d",
            "https://github.com/-Maxi/Thing",
            "https://github.com/Maxi/Thing.",
            "https://github.com/Maxi/%2e%2e",
        ):
            self.assertIsNone(ownership.github_repository(url), url)


class Advice(unittest.TestCase):
    """The one text both decide.py files show an author whose proof is missing."""

    def test_a_github_repository_gets_the_topic_and_the_marker_file(self):
        self.assertIn("`ksa-index-<your-github-username>`", ownership.ADVICE)
        self.assertIn(f"commit `{ownership.MARKER_PATH}` naming your username", ownership.ADVICE)

    def test_a_fork_is_told_the_marker_file_does_not_count(self):
        self.assertIn(f"when it is not a fork, commit `{ownership.MARKER_PATH}`", ownership.ADVICE)
        self.assertIn("A fork also passes when your account owns it", ownership.ADVICE)

    def test_a_spacedock_mod_is_told_to_set_its_source_code_link(self):
        self.assertIn(
            "For a SpaceDock host, set your GitHub repository as the mod's source code "
            "link on SpaceDock, and put the proof on that repository.",
            ownership.ADVICE,
        )


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

    def test_a_spacedock_authority_binds_to_the_mod(self):
        document = {"releases": {"spacedock": 4253}}
        self.assertEqual(ownership.authority(document), ("spacedock", "4253", ""))

    def test_an_unknown_host_kind_has_no_proof(self):
        document = {"releases": {"gitlab": "Maxi/Thing"}}
        kind, _, reason = ownership.authority(document)
        self.assertEqual(kind, "gitlab")
        self.assertIn("no ownership proof", reason)

    def test_since_is_not_a_host(self):
        document = {"releases": {"github": "a/b", "since": "1.2"}}
        self.assertEqual(ownership.authority(document), ("github", "a/b", ""))

    def test_since_next_to_two_hosts_leaves_the_authority_key_in_charge(self):
        document = {"releases": {"github": "a/b", "spacedock": 42, "authority": "spacedock", "since": "1.2"}}
        self.assertEqual(ownership.authority(document), ("spacedock", "42", ""))

    def test_tag_prefix_is_not_a_host(self):
        document = {"releases": {"github": "a/b", "tag_prefix": "gatos-v"}}
        self.assertEqual(ownership.authority(document), ("github", "a/b", ""))
        both = {"releases": {"github": "a/b", "spacedock": 42, "authority": "spacedock", "tag_prefix": "x-"}}
        self.assertEqual(ownership.authority(both), ("spacedock", "42", ""))

    def test_since_alone_names_no_host(self):
        kind, _, reason = ownership.authority({"releases": {"since": "1.2"}})
        self.assertIsNone(kind)
        self.assertIn("names no host", reason)

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


class ForkProofs(unittest.TestCase):
    """A fork proves control through its owner or its topic, never through its files."""

    MARKER = 'id = "AutoStage"\nlogin = "Maxi"\n'

    def verify(self, api, login="Maxi", author_id=1):
        return ownership.verify(LISTING, login, author_id, api)

    def fork(self, owner_id=99, **rest):
        return FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=owner_id, fork=True)},
            **rest,
        )

    def test_a_fork_whose_owner_opened_the_pull_request_verifies(self):
        # The owner of a fork is the account that forked it.
        result = self.verify(self.fork(owner_id=7), author_id=7)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id")

    def test_a_fork_with_the_topic_of_the_pull_request_author_verifies(self):
        # GitHub copies no topic to a fork, so an admin of the fork set this one.
        api = self.fork(topics={"Maxi/KSA-AutoStage": ["ksa-index-maxi"]})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "topic")

    def test_a_fork_with_only_a_marker_file_is_refused(self):
        # A fork inherits the files of its parent, so the marker proves nothing.
        api = self.fork(files={("Maxi/KSA-AutoStage", ownership.MARKER_PATH): self.MARKER})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("did not prove control of the fork Maxi/KSA-AutoStage", result.reason)
        self.assertIn("a fork inherits its files", result.reason)

    def test_the_same_marker_verifies_where_it_is_not_a_fork(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=99)},
            files={("Maxi/KSA-AutoStage", ownership.MARKER_PATH): self.MARKER},
        )
        self.assertEqual(self.verify(api).state, ownership.VERIFIED)

    def test_a_fork_another_account_owns_is_refused(self):
        result = self.verify(self.fork(owner_id=99), login="Attacker", author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("Attacker did not prove control of the fork", result.reason)

    def test_a_fork_whose_topics_cannot_be_read_is_not_a_rejection(self):
        result = self.verify(self.fork(unavailable=["topics"]))
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)


class SpaceDockProofs(unittest.TestCase):
    """A SpaceDock mod is bound to the repository its source code link names."""

    def verify(self, api, login="Maxi", author_id=1, document=None):
        return ownership.verify(document or SPACEDOCK_LISTING, login, author_id, api)

    def api(self, mod=None, owner_id=99, fork=False, **rest):
        return FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=owner_id, fork=fork)},
            spacedock={"4253": spacedock_mod() if mod is None else mod},
            **rest,
        )

    def test_the_owner_of_the_linked_repository_verifies(self):
        result = self.verify(self.api(owner_id=7), author_id=7)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "source code link, owner id")

    def test_a_topic_on_the_linked_repository_verifies(self):
        api = self.api(topics={"Maxi/KSA-AutoStage": ["ksa-index-maxi"]})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "source code link, topic")

    def test_a_marker_file_on_the_linked_repository_verifies(self):
        marker = 'id = "AutoStage"\nlogin = "Maxi"\n'
        api = self.api(files={("Maxi/KSA-AutoStage", ownership.MARKER_PATH): marker})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "source code link, marker file")

    def test_the_proof_still_binds_to_the_pull_request_author(self):
        # The link names the victim's repository, so the attacker has no proof there.
        result = self.verify(self.api(owner_id=99), login="Attacker", author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("Attacker did not prove control of Maxi/KSA-AutoStage", result.reason)
        self.assertIn("SpaceDock mod 4253 links to Maxi/KSA-AutoStage", result.reason)

    def test_a_link_with_a_git_suffix_or_a_deeper_path_still_names_the_repository(self):
        for link in (
            "https://github.com/Maxi/KSA-AutoStage.git",
            "https://github.com/Maxi/KSA-AutoStage/tree/main",
        ):
            result = self.verify(self.api(spacedock_mod(link), owner_id=7), author_id=7)
            self.assertEqual(result.state, ownership.VERIFIED, link)

    def test_no_source_code_link_binds_to_nothing(self):
        for link in (None, ""):
            result = self.verify(self.api(spacedock_mod(link), owner_id=7), author_id=7)
            self.assertEqual(result.state, ownership.UNVERIFIED)
            self.assertIn("no source code link", result.reason)

    def test_a_link_to_another_host_binds_to_nothing(self):
        api = self.api(spacedock_mod("https://gitlab.com/Maxi/KSA-AutoStage"), owner_id=7)
        result = self.verify(api, author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("does not name a GitHub repository", result.reason)
        self.assertEqual(api.asked, ["spacedock:4253"])  # GitHub was never asked

    def test_the_link_itself_is_never_echoed(self):
        # The reason lands in a comment the index App posts.
        link = "evil\n\n**Validated.** @stewards <!-- https://github.com/Maxi/KSA-AutoStage"
        result = self.verify(self.api(spacedock_mod(link), owner_id=7), author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertNotIn("evil", result.reason)
        self.assertNotIn("\n", result.reason)

    def test_a_mod_for_another_game_binds_to_nothing(self):
        result = self.verify(self.api(spacedock_mod(game_id=3102), owner_id=7), author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("not a Kitten Space Agency mod", result.reason)

    def test_an_answer_that_is_not_the_mod_is_not_a_verdict(self):
        # A page in front of SpaceDock answered with JSON of its own.
        for document in ({"message": "ok"}, spacedock_mod(mod_id=4254)):
            result = self.verify(self.api(document, owner_id=7), author_id=7)
            self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE, document)

    def test_a_link_to_a_fork_verifies_through_its_owner(self):
        result = self.verify(self.api(owner_id=7, fork=True), author_id=7)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "source code link, owner id")

    def test_a_link_to_a_fork_with_only_a_marker_file_is_refused(self):
        marker = 'id = "AutoStage"\nlogin = "Maxi"\n'
        api = self.api(fork=True, files={("Maxi/KSA-AutoStage", ownership.MARKER_PATH): marker})
        result = self.verify(api)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("SpaceDock mod 4253 links to Maxi/KSA-AutoStage", result.reason)
        self.assertIn("a fork inherits its files", result.reason)

    def test_a_linked_repository_that_moved_makes_the_link_stale(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/Renamed", owner_id=7)},
            spacedock={"4253": spacedock_mod()},
        )
        result = self.verify(api, author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("the link on SpaceDock is stale", result.reason)

    def test_a_mod_spacedock_does_not_have(self):
        result = self.verify(FakeApi())
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("SpaceDock has no mod 4253", result.reason)

    def test_a_mod_spacedock_refuses_to_show(self):
        # SpaceDock answers an unpublished mod with its own error document.
        refused = {"error": True, "reason": "Mod not published. Authentication needed."}
        result = self.verify(FakeApi(spacedock={"4253": refused}))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertEqual(result.reason, "SpaceDock mod 4253 is not published")

    def test_any_other_refusal_is_described_and_not_echoed(self):
        refused = {"error": True, "reason": "**Validated.** Not enough rights."}
        result = self.verify(FakeApi(spacedock={"4253": refused}))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertEqual(result.reason, "SpaceDock refuses to show mod 4253")

    def test_a_mod_id_that_is_not_a_number(self):
        document = {"id": "AutoStage", "releases": {"spacedock": "four"}}
        result = self.verify(FakeApi(), document=document)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("not a SpaceDock mod id", result.reason)

    def test_a_host_that_cannot_answer_is_not_a_rejection(self):
        for stage in ("spacedock", "repository", "topics", "file"):
            result = self.verify(self.api(unavailable=[stage]))
            self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE, stage)

    def test_spacedock_is_asked_before_github(self):
        api = self.api(owner_id=7)
        self.verify(api, author_id=7)
        self.assertEqual(api.asked, ["spacedock:4253", "Maxi/KSA-AutoStage"])


class GitHubOnlyApi:
    """The GitHub lookups of a FakeApi without a SpaceDock reader, as the
    release flow of content-index-releases hands them in."""

    def __init__(self, api):
        self.repository = api.repository
        self.topics = api.topics
        self.file = api.file


class SpaceDockWithoutReader(unittest.TestCase):
    """Lookups without a SpaceDock reader read SpaceDock directly, with the same rule."""

    def verify(self, opener, login="Maxi", owner_id=7):
        api = GitHubOnlyApi(
            FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", owner_id=owner_id)})
        )
        with mock.patch.object(ownership.urllib.request, "urlopen", opener):
            return ownership.verify(SPACEDOCK_LISTING, login, 7, api)

    def answer(self, mod):
        return mock.Mock(return_value=io.BytesIO(json.dumps(mod).encode()))

    def test_the_owner_of_the_linked_repository_verifies(self):
        opener = self.answer(spacedock_mod())
        result = self.verify(opener)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "source code link, owner id")
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, "https://spacedock.info/api/mod/4253")
        self.assertEqual(request.get_header("User-agent"), ownership.USER_AGENT)

    def test_a_link_to_another_persons_repository_does_not_verify(self):
        result = self.verify(self.answer(spacedock_mod()), login="Attacker", owner_id=99)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("Attacker did not prove control of Maxi/KSA-AutoStage", result.reason)

    def test_each_reason_to_wait_gives_its_own_answer(self):
        results = {
            name: self.verify(opener)
            for name, opener in {
                "no link": self.answer(spacedock_mod(None)),
                "not GitHub": self.answer(spacedock_mod("https://gitlab.com/Maxi/KSA-AutoStage")),
                "timeout": mock.Mock(side_effect=TimeoutError("timed out")),
                "connect timeout": mock.Mock(
                    side_effect=ownership.urllib.error.URLError(TimeoutError("timed out"))
                ),
            }.items()
        }
        self.assertEqual(results["no link"].state, ownership.UNVERIFIED)
        self.assertIn("has no source code link", results["no link"].reason)
        self.assertEqual(results["not GitHub"].state, ownership.UNVERIFIED)
        self.assertIn("does not name a GitHub repository", results["not GitHub"].reason)
        for name in ("timeout", "connect timeout"):
            self.assertEqual(results[name].state, ownership.COULD_NOT_EVALUATE)
            self.assertEqual(
                results[name].reason, "SpaceDock did not answer about mod 4253: timed out"
            )


class OwnerLogins(unittest.TestCase):
    """The accounts the proofs name as a listing's owners, for a mention."""

    MARKER = ("Maxi/KSA-AutoStage", ownership.MARKER_PATH)

    def owners(self, api, document=None):
        return ownership.owner_logins(document or LISTING, api)

    def test_a_personal_repository_names_its_owner(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", login="Maxi")},
            topics={"Maxi/KSA-AutoStage": ["ksa-index-helper"]},
        )
        self.assertEqual(self.owners(api), (("Maxi",), ""))

    def test_an_organization_repository_names_its_topic(self):
        api = FakeApi(organization(), topics={"Maxi/KSA-AutoStage": ["ksa", "ksa-index-alice"]})
        self.assertEqual(self.owners(api), (("alice",), ""))

    def test_an_organization_repository_names_its_marker_file(self):
        api = FakeApi(organization(), files={self.MARKER: 'id = "AutoStage"\nlogin = "Bob"\n'})
        self.assertEqual(self.owners(api), (("Bob",), ""))

    def test_every_topic_and_the_marker_file_are_named_once(self):
        api = FakeApi(
            organization(),
            topics={"Maxi/KSA-AutoStage": ["ksa-index-bob", "ksa-index-alice"]},
            files={self.MARKER: 'login = "Bob"\n'},
        )
        self.assertEqual(self.owners(api), (("alice", "bob"), ""))

    def test_a_marker_file_for_another_listing_names_nobody(self):
        api = FakeApi(organization(), files={self.MARKER: 'id = "Other"\nlogin = "Bob"\n'})
        logins, reason = self.owners(api)
        self.assertEqual(logins, ())
        self.assertIn("names an owner", reason)

    def test_a_login_github_cannot_carry_is_never_named(self):
        # The mention lands in a comment the index App posts.
        api = FakeApi(organization(), files={self.MARKER: 'login = "@stewards **x**"\n'})
        self.assertEqual(self.owners(api)[0], ())

    def test_a_fork_of_a_person_names_the_account_that_forked_it(self):
        api = FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", fork=True, login="Carol")})
        self.assertEqual(self.owners(api), (("Carol",), ""))

    def test_a_fork_of_an_organization_names_its_topic_and_not_its_marker_file(self):
        marker = {self.MARKER: 'login = "Parent"\n'}
        api = FakeApi(organization(fork=True), files=marker)
        logins, reason = self.owners(api)
        self.assertEqual(logins, ())
        self.assertIn("on the fork", reason)

        api = FakeApi(
            organization(fork=True), files=marker, topics={"Maxi/KSA-AutoStage": ["ksa-index-dave"]}
        )
        self.assertEqual(self.owners(api), (("dave",), ""))

    def test_the_placeholder_of_a_no_owner_reason_stays_in_a_code_span(self):
        # A GitHub comment hides a bare <login> as an HTML tag.
        for fork in (False, True):
            _, reason = self.owners(FakeApi(organization(fork=fork)))
            self.assertIn("`ksa-index-<login>`", reason, fork)
            self.assertNotIn("<", reason.replace("`ksa-index-<login>`", ""), fork)
        _, reason = self.owners(FakeApi(organization()))
        self.assertIn(f"`{ownership.MARKER_PATH}`", reason)

    def test_a_spacedock_mod_names_the_owner_of_its_linked_repository(self):
        api = FakeApi(
            {"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage", login="Maxi")},
            spacedock={"4253": spacedock_mod()},
        )
        self.assertEqual(self.owners(api, SPACEDOCK_LISTING), (("Maxi",), ""))

    def test_a_spacedock_mod_without_a_link_names_nobody(self):
        api = FakeApi(spacedock={"4253": spacedock_mod(None)})
        logins, reason = self.owners(api, SPACEDOCK_LISTING)
        self.assertEqual(logins, ())
        self.assertIn("no source code link", reason)

    def test_lookups_without_a_spacedock_reader_still_read_spacedock(self):
        api = GitHubOnlyApi(FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/KSA-AutoStage")}))
        opener = mock.Mock(return_value=io.BytesIO(json.dumps(spacedock_mod()).encode()))
        with mock.patch.object(ownership.urllib.request, "urlopen", opener):
            self.assertEqual(self.owners(api, SPACEDOCK_LISTING), (("Maxi",), ""))

    def test_no_owner_comes_with_the_reason(self):
        cases = {
            "does not exist or is private": FakeApi(),
            "is stale": FakeApi({"Maxi/KSA-AutoStage": repository("Maxi/Renamed")}),
            "names an owner": FakeApi(organization()),
            "no ownership proof": FakeApi(),
        }
        for expected, api in cases.items():
            document = {"releases": {"gitlab": "a/b"}} if expected == "no ownership proof" else None
            logins, reason = self.owners(api, document)
            self.assertEqual(logins, (), expected)
            self.assertIn(expected, reason)

    def test_a_host_that_does_not_answer_is_a_reason_and_not_an_error(self):
        for stage, document in (
            ("repository", LISTING),
            ("topics", LISTING),
            ("file", LISTING),
            ("spacedock", SPACEDOCK_LISTING),
        ):
            api = FakeApi(organization(), spacedock={"4253": spacedock_mod()}, unavailable=[stage])
            logins, reason = self.owners(api, document)
            self.assertEqual(logins, (), stage)
            self.assertIn("did not answer", reason, stage)

    def test_a_marker_file_that_does_not_answer_keeps_the_topics(self):
        api = FakeApi(
            organization(), topics={"Maxi/KSA-AutoStage": ["ksa-index-alice"]}, unavailable=["file"]
        )
        self.assertEqual(self.owners(api), (("alice",), ""))


def hosted_at(repository, identifier="AutoStage"):
    """A listing whose releases come from `repository`."""
    return {"id": identifier, "releases": {"github": repository}}


class SameAuthority(unittest.TestCase):
    def test_the_same_repository_is_the_same_authority(self):
        self.assertTrue(ownership.same_authority(hosted_at("Maxi/Mod"), hosted_at("Maxi/Mod")))

    def test_the_comparison_is_case_insensitive(self):
        self.assertTrue(ownership.same_authority(hosted_at("Maxi/Mod"), hosted_at("maxi/mod")))

    def test_another_repository_is_another_authority(self):
        self.assertFalse(ownership.same_authority(hosted_at("Maxi/Mod"), hosted_at("Other/Mod")))

    def test_another_host_kind_is_another_authority(self):
        spacedock = {"id": "AutoStage", "releases": {"spacedock": 4254}}
        self.assertFalse(ownership.same_authority(hosted_at("Maxi/Mod"), spacedock))

    def test_moving_the_authority_key_is_a_move(self):
        both = {"releases": {"github": "Maxi/Mod", "spacedock": 42, "authority": "github"}}
        moved = {"releases": {"github": "Maxi/Mod", "spacedock": 42, "authority": "spacedock"}}
        self.assertFalse(ownership.same_authority(both, moved))

    def test_adding_a_releases_section_over_a_repository_link_is_a_move(self):
        linked = {"links": {"repository": "https://github.com/Maxi/Mod"}}
        hosted = dict(hosted_at("Maxi/Other"), links=linked["links"])
        self.assertFalse(ownership.same_authority(linked, hosted))

    def test_setting_since_is_not_a_move(self):
        opted = {"id": "AutoStage", "releases": {"github": "Maxi/Mod", "since": "0.5"}}
        self.assertTrue(ownership.same_authority(hosted_at("Maxi/Mod"), opted))

    def test_setting_tag_prefix_is_not_a_move(self):
        opted = {"id": "gatOS", "releases": {"github": "Maxi/Mod", "tag_prefix": "gatos-v"}}
        self.assertTrue(ownership.same_authority(hosted_at("Maxi/Mod"), opted))

    def test_two_documents_binding_to_nothing_are_the_same(self):
        self.assertTrue(ownership.same_authority({"id": "A"}, {"id": "A"}))


class VerifyChange(unittest.TestCase):
    """Which document decides who may write a listing."""

    def change(self, api, base, submitted, login="Attacker", author_id=7):
        return ownership.verify_change(base, submitted, login, author_id, api)

    def test_a_new_listing_is_verified_against_what_it_declares(self):
        api = FakeApi({"Attacker/Mod": repository("Attacker/Mod", owner_id=7)})
        result = self.change(api, None, hosted_at("Attacker/Mod"))
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id")

    def test_an_edit_cannot_repoint_a_listing_at_a_repository_it_owns(self):
        # The hole this exists to close.
        api = FakeApi(
            {
                "Victim/Mod": repository("Victim/Mod", owner_id=99),
                "Attacker/Mod": repository("Attacker/Mod", owner_id=7),
            }
        )
        self.assertEqual(
            ownership.verify(hosted_at("Attacker/Mod"), "Attacker", 7, api).state,
            ownership.VERIFIED,
        )

        result = self.change(api, hosted_at("Victim/Mod"), hosted_at("Attacker/Mod"))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("already names", result.reason)
        self.assertIn("Victim/Mod", result.reason)

    def test_an_edit_that_leaves_the_authority_alone_asks_only_about_it(self):
        api = FakeApi({"Maxi/Mod": repository("Maxi/Mod", owner_id=7)})
        base = hosted_at("Maxi/Mod")
        submitted = dict(base, abstract="Edited.")
        result = self.change(api, base, submitted, login="Maxi")
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(api.asked, ["Maxi/Mod"])

    def test_an_edit_that_leaves_the_authority_alone_still_has_to_prove_it(self):
        # The busiest path, and the one that makes the base check real.
        api = FakeApi({"Victim/Mod": repository("Victim/Mod", owner_id=99)})
        base = hosted_at("Victim/Mod")
        result = self.change(api, base, dict(base, abstract="Edited."))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("Victim/Mod", result.reason)

    def test_moving_the_authority_key_needs_the_new_host_proved(self):
        # Flipping one word hands the id to a host no proof was ever read for.
        hosts = {"github": "Maxi/Mod", "spacedock": 4254}
        api = FakeApi(
            {
                "Maxi/Mod": repository("Maxi/Mod", owner_id=7),
                "Someone/Mod": repository("Someone/Mod", owner_id=99),
            },
            spacedock={"4254": spacedock_mod("https://github.com/Someone/Mod", mod_id=4254)},
        )
        result = self.change(
            api,
            {"id": "AutoStage", "releases": dict(hosts, authority="github")},
            {"id": "AutoStage", "releases": dict(hosts, authority="spacedock")},
            login="Maxi",
        )
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("moves to", result.reason)
        self.assertIn("SpaceDock mod 4254 links to Someone/Mod", result.reason)

    def test_moving_to_a_spacedock_mod_that_links_back_verifies(self):
        hosts = {"github": "Maxi/Mod", "spacedock": 4254}
        api = FakeApi(
            {"Maxi/Mod": repository("Maxi/Mod", owner_id=7)},
            spacedock={"4254": spacedock_mod("https://github.com/Maxi/Mod", mod_id=4254)},
        )
        result = self.change(
            api,
            {"id": "AutoStage", "releases": dict(hosts, authority="github")},
            {"id": "AutoStage", "releases": dict(hosts, authority="spacedock")},
            login="Maxi",
        )
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id, then source code link, owner id")

    def test_an_edit_of_a_spacedock_listing_is_verified_through_its_link(self):
        api = FakeApi(
            {"Maxi/Mod": repository("Maxi/Mod", owner_id=7)},
            spacedock={"4254": spacedock_mod("https://github.com/Maxi/Mod", mod_id=4254)},
        )
        base = {"id": "AutoStage", "releases": {"spacedock": 4254}}
        submitted = dict(base, abstract="Edited.")
        self.assertEqual(self.change(api, base, submitted, login="Maxi").state, ownership.VERIFIED)
        attacker = self.change(api, base, submitted, author_id=99)
        self.assertEqual(attacker.state, ownership.UNVERIFIED)
        self.assertIn("SpaceDock mod 4254 links to Maxi/Mod", attacker.reason)
        self.assertIn("Attacker did not prove control of Maxi/Mod", attacker.reason)

    def test_dropping_every_release_host_is_a_move(self):
        api = FakeApi({"Maxi/Mod": repository("Maxi/Mod", owner_id=7)})
        result = self.change(api, hosted_at("Maxi/Mod"), {"id": "AutoStage"}, login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("moves to", result.reason)

    def test_an_owner_who_controls_both_hosts_moves_the_authority(self):
        api = FakeApi(
            {
                "Maxi/Mod": repository("Maxi/Mod", owner_id=7),
                "MaxiOrg/Mod": repository("MaxiOrg/Mod", owner_id=7),
            }
        )
        result = self.change(api, hosted_at("Maxi/Mod"), hosted_at("MaxiOrg/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id, then owner id")

    def test_controlling_only_the_old_host_is_not_enough_to_move(self):
        api = FakeApi(
            {
                "Maxi/Mod": repository("Maxi/Mod", owner_id=7),
                "Someone/Mod": repository("Someone/Mod", owner_id=99),
            }
        )
        result = self.change(api, hosted_at("Maxi/Mod"), hosted_at("Someone/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("moves to", result.reason)
        self.assertIn("Someone/Mod", result.reason)

    def test_a_failed_current_authority_stops_before_the_new_one(self):
        api = FakeApi(
            {
                "Victim/Mod": repository("Victim/Mod", owner_id=99),
                "Attacker/Mod": repository("Attacker/Mod", owner_id=7),
            }
        )
        self.change(api, hosted_at("Victim/Mod"), hosted_at("Attacker/Mod"))
        self.assertNotIn("Attacker/Mod", api.asked)

    def test_a_host_that_could_not_answer_is_not_a_rejection(self):
        api = FakeApi(
            {"Maxi/Mod": repository("Maxi/Mod", owner_id=7)}, unavailable=["repository"]
        )
        result = self.change(api, hosted_at("Maxi/Mod"), hosted_at("Other/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)
        self.assertIn("already names", result.reason)

    def test_a_renamed_repository_stays_self_service(self):
        # The old name answers as the new one, which only its controller could
        # have arranged, so the listing is catching up rather than moving.
        # GitHub answers both names, the old one under the new full name.
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=7),
                "Maxi/New": repository("Maxi/New", owner_id=7),
            }
        )
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Maxi")
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_a_rename_still_needs_the_new_name_to_verify(self):
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=99),
                "Maxi/New": repository("Maxi/New", owner_id=99),
            }
        )
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)

    def test_a_redirect_somewhere_else_is_still_a_move(self):
        # The redirect has to land on exactly the submitted host.
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=7),
                "Someone/Mod": repository("Someone/Mod", owner_id=7),
            }
        )
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Someone/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("already names", result.reason)

    def test_a_renamed_fork_stays_self_service(self):
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=7, fork=True),
                "Maxi/New": repository("Maxi/New", owner_id=7, fork=True),
            }
        )
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Maxi")
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "owner id")

    def test_a_renamed_fork_does_not_verify_through_its_marker_file(self):
        marker = 'id = "AutoStage"\nlogin = "Maxi"\n'
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=99, fork=True),
                "Maxi/New": repository("Maxi/New", owner_id=99, fork=True),
            },
            files={("Maxi/New", ownership.MARKER_PATH): marker},
        )
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("renamed into", result.reason)
        self.assertIn("a fork inherits its files", result.reason)

    def test_moving_a_listing_to_a_fork_verifies_against_both(self):
        # The listing keeps its id, so the account moving it has to control the original too.
        api = FakeApi(
            {
                "Original/Mod": repository("Original/Mod", owner_id=99),
                "Maxi/Mod": repository("Maxi/Mod", owner_id=7, fork=True),
            },
            topics={"Original/Mod": ["ksa-index-maxi"]},
        )
        result = self.change(api, hosted_at("Original/Mod"), hosted_at("Maxi/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "topic, then owner id")

    def test_owning_the_fork_is_not_enough_to_take_a_listing(self):
        api = FakeApi(
            {
                "Original/Mod": repository("Original/Mod", owner_id=99),
                "Maxi/Mod": repository("Maxi/Mod", owner_id=7, fork=True),
            }
        )
        result = self.change(api, hosted_at("Original/Mod"), hosted_at("Maxi/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("already names", result.reason)
        self.assertNotIn("Maxi/Mod", api.asked)

    def test_moving_to_a_fork_with_only_a_marker_file_is_refused(self):
        marker = 'id = "AutoStage"\nlogin = "Maxi"\n'
        api = FakeApi(
            {
                "Original/Mod": repository("Original/Mod", owner_id=7),
                "Maxi/Mod": repository("Maxi/Mod", owner_id=99, fork=True),
            },
            files={("Maxi/Mod", ownership.MARKER_PATH): marker},
        )
        result = self.change(api, hosted_at("Original/Mod"), hosted_at("Maxi/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("moves to", result.reason)
        self.assertIn("a fork inherits its files", result.reason)

    def test_a_spacedock_host_is_never_a_rename(self):
        # "4254" answers, so only the base_kind guard can fail the second one.
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=7),
                "4254": repository("Maxi/New", owner_id=7),
            }
        )
        spacedock = {"id": "AutoStage", "releases": {"spacedock": 4254}}
        self.assertFalse(ownership.renamed_into(hosted_at("Maxi/Old"), spacedock, api))
        self.assertFalse(ownership.renamed_into(spacedock, hosted_at("Maxi/New"), api))

    def test_a_host_that_did_not_answer_is_not_read_as_a_rename(self):
        # The one place that could turn a blip into a definite no.
        class Flaky(FakeApi):
            def repository(self, full_name):
                self.asked.append(full_name)
                if len(self.asked) > 1:
                    raise ownership.Unavailable("the host did not answer")
                return self.repositories.get(full_name)

        api = Flaky({"Maxi/Old": repository("Maxi/New", owner_id=7)})
        result = self.change(api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Maxi")
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)

    def test_a_rename_verdict_says_which_host_it_is_about(self):
        api = FakeApi(
            {
                "Maxi/Old": repository("Maxi/New", owner_id=7),
                "Maxi/New": repository("Maxi/New", owner_id=7),
            }
        )
        result = self.change(
            api, hosted_at("Maxi/Old"), hosted_at("Maxi/New"), login="Outsider", author_id=1
        )
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("renamed into", result.reason)

    def test_the_new_host_not_answering_is_not_a_rejection_either(self):
        class Flaky(FakeApi):
            def repository(self, full_name):
                if full_name == "Other/Mod":
                    raise ownership.Unavailable("the host did not answer")
                return super().repository(full_name)

        api = Flaky({"Maxi/Mod": repository("Maxi/Mod", owner_id=7)})
        result = self.change(api, hosted_at("Maxi/Mod"), hosted_at("Other/Mod"), login="Maxi")
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)
        self.assertIn("moves to", result.reason)


class ShareListings(unittest.TestCase):
    """A vehicle or a save on a repository of its own (RFC 0085), with one
    repository and a tag prefix per share (RFC 0096)."""

    TARGET = "Maxi/KSA-Rovers"
    MARKER = (TARGET, ownership.MARKER_PATH)

    def document(self, identifier="ExampleRover", kind="vehicle", prefix="ExampleRover-"):
        return {
            "id": identifier,
            "type": kind,
            "releases": {"github": self.TARGET, "tag_prefix": prefix},
        }

    def api(self, owner_id=99, **rest):
        return FakeApi({self.TARGET: repository(self.TARGET, owner_id=owner_id)}, **rest)

    def test_the_repository_is_the_authority_and_the_prefix_is_no_host(self):
        self.assertEqual(ownership.authority(self.document()), ("github", self.TARGET, ""))

    def test_each_proof_verifies_a_vehicle_and_a_save(self):
        cases = {
            "owner id": (self.api(owner_id=7), 7),
            "topic": (self.api(topics={self.TARGET: ["ksa-index-maxi"]}), 1),
            "marker file": (self.api(files={self.MARKER: 'login = "Maxi"\n'}), 1),
        }
        for kind in ownership.SHARE_TYPES:
            for proof, (api, author_id) in cases.items():
                with self.subTest(kind=kind, proof=proof):
                    result = ownership.verify(self.document(kind=kind), "Maxi", author_id, api)
                    self.assertEqual(result.state, ownership.VERIFIED)
                    self.assertEqual(result.proof, proof)

    def test_a_marker_with_only_a_login_covers_every_share_of_the_repository(self):
        api = self.api(files={self.MARKER: 'login = "Maxi"\n'})
        for identifier in ("ExampleRover", "OtherRover"):
            document = self.document(identifier, prefix=f"{identifier}-")
            self.assertEqual(ownership.verify(document, "Maxi", 1, api).state, ownership.VERIFIED)

    def test_a_marker_that_names_one_share_covers_only_that_one(self):
        api = self.api(files={self.MARKER: 'id = "ExampleRover"\nlogin = "Maxi"\n'})
        verdict = ownership.verify(self.document("OtherRover", prefix="OtherRover-"), "Maxi", 1, api)
        self.assertEqual(verdict.state, ownership.UNVERIFIED)

    def test_no_host_gets_the_advice_that_names_every_path(self):
        for kind in ownership.SHARE_TYPES:
            with self.subTest(kind=kind):
                result = ownership.verify({"id": "ExampleRover", "type": kind}, "Maxi", 1, FakeApi())
                self.assertEqual(result.state, ownership.UNVERIFIED)
                self.assertEqual(
                    result.reason, "the document names no release host and no GitHub repository"
                )
                self.assertEqual(result.instructions, ownership.SHARE_ADVICE)
        for part in ("`[releases] github`", "`tag_prefix`", "share host", "release pull request"):
            self.assertIn(part, ownership.SHARE_ADVICE)

    def test_a_mod_with_no_host_keeps_the_common_advice(self):
        result = ownership.verify({"id": "AutoStage", "type": "mod"}, "Maxi", 1, FakeApi())
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIsNone(result.instructions)

    def test_a_new_tag_prefix_is_no_new_host(self):
        base, submitted = self.document(prefix="A-"), self.document(prefix="B-")
        self.assertTrue(ownership.same_authority(base, submitted))
        api = self.api(owner_id=7)
        result = ownership.verify_change(base, submitted, "Maxi", 7, api)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(api.asked, [self.TARGET])

    def test_an_organization_repository_names_the_login_of_its_marker(self):
        api = FakeApi(
            organization(self.TARGET), files={self.MARKER: 'login = "Bob"\n'}
        )
        self.assertEqual(ownership.owner_logins(self.document(), api), (("Bob",), ""))


STORAGE = "ksamods-content/share"
BOT = 98765432
TABLE = {
    "kind": "share",
    "name": "ksamods.gg",
    "storage": STORAGE,
    "bot": BOT,
    "pages": "https://ksamods-content.github.io/share/",
    "types": ["vehicle", "save"],
}
REGISTRY = {"ksamods": TABLE}
ROVER = {"id": "ExampleRover", "type": "vehicle", "releases": {"ksamods": "ExampleRover"}}
RECORD_PATH = "owners/vehicle/ExampleRover.json"
ACCOUNT = "u_7Hk2pQ"
BLOB = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"


def record(identifier="ExampleRover", content_type="vehicle", account=ACCOUNT, github_id=None):
    value = {"id": identifier, "type": content_type, "account": account}
    if github_id is not None:
        value["github_id"] = github_id
    return json.dumps(value)


def change(*paths, blob=BLOB):
    return [check_scope.Change(path, "added", None, blob) for path in paths]


def attestation(accounts=None, host="ksamods"):
    return json.dumps({
        "host": host,
        "accounts": {"vehicle/ExampleRover": ACCOUNT} if accounts is None else accounts,
        "created": "2026-10-11T09:14:30Z",
    })


class ShareApi(FakeApi):
    """The lookups of decide.py, with the files of a storage repository and the change."""

    def __init__(self, files=None, changes=None, unavailable=()):
        super().__init__(unavailable=unavailable)
        self.share_files = files or {}
        self.changes = changes
        self.read = []

    def share_file(self, table, path):
        self.read.append(path)
        if "share" in self.unavailable:
            raise ownership.Unavailable(f"{table['storage']} did not answer about {path}")
        return self.share_files.get(path)

    def change(self):
        return self.changes


def attested(changes, text=None):
    """The files of a storage repository that attested `changes`."""
    return {
        RECORD_PATH: record(),
        ownership.ATTESTATION.format(digest=ownership.change_digest(changes)): text or attestation(),
    }


class ShareHostAuthority(unittest.TestCase):
    def test_a_registered_key_is_a_share_host_with_its_table(self):
        kind, target, reason = ownership.authority(ROVER, REGISTRY)
        self.assertEqual((kind, target, reason), ("share", ownership.Share("ksamods", "ExampleRover", TABLE), ""))

    def test_a_key_hosts_toml_does_not_register_has_no_proof(self):
        kind, target, reason = ownership.authority(ROVER, {})
        self.assertEqual((kind, target), ("ksamods", "ExampleRover"))
        self.assertEqual(
            reason,
            "ksamods is not a share host that hosts.toml registers, so it offers no ownership proof a check can read",
        )
        result = ownership.verify(ROVER, "Maxi", 7, ShareApi(), {})
        self.assertEqual((result.state, result.reason), (ownership.UNVERIFIED, reason))

    def test_a_table_of_another_kind_is_not_a_share_host(self):
        self.assertEqual(ownership.authority(ROVER, {"ksamods": dict(TABLE, kind="mirror")})[0], "ksamods")

    def test_a_share_host_as_the_authority_of_several_hosts(self):
        document = {"id": "ExampleRover", "releases": {"ksamods": "ExampleRover", "github": "a/b", "authority": "ksamods"}}
        self.assertEqual(ownership.authority(document, REGISTRY)[0], "share")
        document["releases"]["authority"] = "github"
        self.assertEqual(ownership.authority(document, REGISTRY)[:2], ("github", "a/b"))

    def test_hosts_toml_is_read_when_no_registry_is_given(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "hosts.toml"
        path.write_text('[ksamods]\nkind = "share"\nstorage = "a/b"\n', encoding="utf-8")
        self.assertEqual(ownership.share_hosts(path), {"ksamods": {"kind": "share", "storage": "a/b"}})
        with mock.patch.object(ownership, "HOSTS_FILE", path), mock.patch.object(
            ownership.share_hosts, "__defaults__", (path,)
        ):
            self.assertEqual(ownership.authority(ROVER)[0], "share")

    def test_a_hosts_toml_that_is_missing_or_does_not_read_registers_nothing(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        broken = Path(folder.name) / "hosts.toml"
        broken.write_text("[ksamods\n", encoding="utf-8")
        self.assertEqual(ownership.share_hosts(broken), {})
        self.assertEqual(ownership.share_hosts(Path(folder.name) / "none.toml"), {})

    def test_the_same_host_and_id_is_the_same_authority(self):
        other = {"id": "ExampleRover", "releases": {"ksamods": "examplerover"}}
        self.assertTrue(ownership.same_authority(ROVER, other, REGISTRY))
        moved = {"id": "ExampleRover", "releases": {"github": "ksamods/ExampleRover"}}
        self.assertFalse(ownership.same_authority(ROVER, moved, REGISTRY))

    def test_a_share_host_names_no_github_login(self):
        logins, reason = ownership.owner_logins(ROVER, ShareApi(), REGISTRY)
        self.assertEqual(logins, ())
        self.assertIn("names its owners by its own accounts", reason)


class ShareHostProofs(unittest.TestCase):
    def verify(self, author_id, api, document=ROVER):
        return ownership.verify(document, "someone", author_id, api, REGISTRY)

    def test_a_linked_github_account_verifies(self):
        api = ShareApi({RECORD_PATH: record(github_id=54321)})
        result = self.verify(54321, api)
        self.assertEqual((result.state, result.proof), (ownership.VERIFIED, "linked GitHub account"))
        self.assertEqual(api.read, [RECORD_PATH])

    def test_another_github_account_does_not(self):
        result = self.verify(11111, ShareApi({RECORD_PATH: record(github_id=54321)}))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertEqual(
            result.reason,
            "the owner record owners/vehicle/ExampleRover.json of `ksamods` links no GitHub account of "
            "the pull request author, and the pull request is not from the account of `ksamods`",
        )
        self.assertEqual(result.instructions, ownership.SHARE_HOST_ADVICE)

    def test_a_record_without_a_link_does_not_verify_an_author(self):
        self.assertEqual(self.verify(54321, ShareApi({RECORD_PATH: record()})).state, ownership.UNVERIFIED)

    def test_the_bot_with_a_good_attestation_verifies(self):
        changes = change("vehicles/ExampleRover.toml")
        result = self.verify(BOT, ShareApi(attested(changes), changes))
        self.assertEqual((result.state, result.proof), (ownership.VERIFIED, "attestation"))

    def test_the_bot_with_one_byte_changed_after_the_attestation_does_not(self):
        files = attested(change("vehicles/ExampleRover.toml"))
        changed = change("vehicles/ExampleRover.toml", blob="a5c19667710254f835085b99726e523457150e03")
        result = self.verify(BOT, ShareApi(files, changed))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        digest = ownership.change_digest(changed)
        self.assertEqual(
            result.reason,
            f"`ksamods` attested no change with the digest {digest}: {STORAGE} has no "
            f"attestations/{digest}.json, so the pull request differs from what the host attested, "
            "or the attestation is not published yet",
        )

    def test_an_attestation_that_misses_one_listing_does_not_verify(self):
        changes = change("vehicles/ExampleRover.toml", "saves/MunBase.toml")
        result = self.verify(BOT, ShareApi(attested(changes), changes))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("names no account for save/MunBase, which the pull request touches", result.reason)

    def test_the_old_path_of_a_rename_is_a_touched_listing_too(self):
        changes = [check_scope.Change("vehicles/ExampleRover.toml", "renamed", "vehicles/OldRover.toml", BLOB)]
        result = self.verify(BOT, ShareApi(attested(changes), changes))
        self.assertIn("names no account for vehicle/OldRover", result.reason)
        accounts = {"vehicle/ExampleRover": ACCOUNT, "vehicle/OldRover": "u_other"}
        result = self.verify(BOT, ShareApi(attested(changes, attestation(accounts)), changes))
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_a_grouped_attestation_verifies_each_listing_of_the_group(self):
        changes = change("vehicles/ExampleRover.toml", "saves/MunBase.toml", "listings/Other.toml")
        accounts = {"vehicle/ExampleRover": ACCOUNT, "save/MunBase": "u_other"}
        result = self.verify(BOT, ShareApi(attested(changes, attestation(accounts)), changes))
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_an_owner_record_that_does_not_exist(self):
        result = self.verify(BOT, ShareApi({}, change("vehicles/ExampleRover.toml")))
        self.assertEqual(
            (result.state, result.reason),
            (ownership.UNVERIFIED, f"the share host `ksamods` has no owner record {RECORD_PATH} in {STORAGE}"),
        )

    def test_an_owner_record_of_another_listing_does_not_verify(self):
        for text in (record(identifier="OtherRover"), record(content_type="save"), record(account=""), "[]", "not json"):
            with self.subTest(text):
                result = self.verify(54321, ShareApi({RECORD_PATH: text}))
                self.assertEqual(result.state, ownership.UNVERIFIED)
                self.assertIn("is not the owner record of this vehicle", result.reason)

    def test_an_attestation_of_another_host_does_not_verify(self):
        changes = change("vehicles/ExampleRover.toml")
        result = self.verify(BOT, ShareApi(attested(changes, attestation(host="other")), changes))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("is not an attestation of `ksamods`", result.reason)

    def test_an_account_other_than_the_owner_record_does_not_verify(self):
        changes = change("vehicles/ExampleRover.toml")
        text = attestation({"vehicle/ExampleRover": "u_somebody"})
        result = self.verify(BOT, ShareApi(attested(changes, text), changes))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("names another account for vehicle/ExampleRover than its owner record", result.reason)

    def test_a_storage_that_does_not_answer_is_no_verdict(self):
        result = self.verify(BOT, ShareApi(unavailable=["share"]))
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)

    def test_a_change_without_a_blob_id_does_not_verify_by_the_bot_alone(self):
        changes = change("vehicles/ExampleRover.toml", blob=None)
        result = self.verify(BOT, ShareApi({RECORD_PATH: record()}, changes))
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("cannot be attested", result.reason)

    def test_lookups_without_the_change_cannot_take_the_bot_path(self):
        class ReleaseFlowApi(FakeApi):
            def share_file(self, table, path):
                return record()

        result = self.verify(BOT, ReleaseFlowApi())
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("cannot read the change", result.reason)

    def test_a_value_that_is_not_the_id_of_the_listing_does_not_verify(self):
        document = {"id": "ExampleRover", "type": "vehicle", "releases": {"ksamods": "OtherRover"}}
        result = self.verify(54321, ShareApi({RECORD_PATH: record(github_id=54321)}), document)
        self.assertEqual(result.state, ownership.UNVERIFIED)

    def test_a_first_claim_by_the_bot_verifies(self):
        changes = change("vehicles/ExampleRover.toml")
        result = ownership.verify_change(None, ROVER, "ksamods-bot", BOT, ShareApi(attested(changes), changes), REGISTRY)
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_an_edit_verifies_against_the_share_host_of_the_base(self):
        moved = {"id": "ExampleRover", "type": "vehicle", "releases": {"github": "Attacker/Rover"}}
        api = ShareApi({RECORD_PATH: record(github_id=54321)})
        api.repositories = {"Attacker/Rover": repository("Attacker/Rover", owner_id=666)}
        result = ownership.verify_change(ROVER, moved, "attacker", 666, api, REGISTRY)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertTrue(result.reason.startswith(ownership.CURRENT_HOST))
        self.assertEqual(result.instructions, ownership.SHARE_HOST_ADVICE)
        edited = dict(ROVER, name="Example Rover Mk2")
        self.assertEqual(ownership.verify_change(ROVER, edited, "owner", 54321, api, REGISTRY).state, ownership.VERIFIED)


class ShareFile(unittest.TestCase):
    """How the owner record and the attestation are read from the storage repository."""

    def answer(self, body=b"{}"):
        answer = mock.MagicMock()
        answer.__enter__.return_value.read.side_effect = lambda size=-1: body[:size] if size >= 0 else body
        return answer

    def missing(self, url):
        return ownership.urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    def test_pages_is_asked_first(self):
        with mock.patch.object(ownership.urllib.request, "urlopen", return_value=self.answer(b'{"a": 1}')) as urlopen:
            self.assertEqual(ownership.share_file(TABLE, RECORD_PATH), '{"a": 1}')
        self.assertEqual(urlopen.call_args.args[0].full_url, TABLE["pages"] + RECORD_PATH)

    def test_raw_is_asked_after_a_404_on_pages(self):
        urls = []

        def urlopen(request, timeout):
            urls.append(request.full_url)
            if request.full_url.startswith(TABLE["pages"]):
                raise self.missing(request.full_url)
            return self.answer(b"{}")

        with mock.patch.object(ownership.urllib.request, "urlopen", urlopen):
            self.assertEqual(ownership.share_file(TABLE, RECORD_PATH), "{}")
        self.assertEqual(
            urls,
            [TABLE["pages"] + RECORD_PATH, f"https://raw.githubusercontent.com/{STORAGE}/HEAD/{RECORD_PATH}"],
        )

    def test_without_pages_only_raw_is_asked_and_a_404_there_is_no_file(self):
        table = {key: value for key, value in TABLE.items() if key != "pages"}
        urls = []

        def urlopen(request, timeout):
            urls.append(request.full_url)
            raise self.missing(request.full_url)

        with mock.patch.object(ownership.urllib.request, "urlopen", urlopen):
            self.assertIsNone(ownership.share_file(table, RECORD_PATH))
        self.assertEqual(urls, [f"https://raw.githubusercontent.com/{STORAGE}/HEAD/{RECORD_PATH}"])

    def test_another_answer_or_no_answer_is_unavailable(self):
        failures = (
            ownership.urllib.error.HTTPError("u", 500, "Server Error", {}, io.BytesIO(b"")),
            ownership.urllib.error.URLError("timed out"),
        )
        for failure in failures:
            with self.subTest(failure), mock.patch.object(ownership.urllib.request, "urlopen", side_effect=failure):
                with self.assertRaises(ownership.Unavailable):
                    ownership.share_file(TABLE, RECORD_PATH)

    def test_a_file_above_the_limit_is_unavailable(self):
        body = b" " * (ownership.MAX_SHARE_FILE + 1)
        with mock.patch.object(ownership.urllib.request, "urlopen", return_value=self.answer(body)):
            with self.assertRaises(ownership.Unavailable):
                ownership.share_file(TABLE, RECORD_PATH)


if __name__ == "__main__":
    unittest.main()
