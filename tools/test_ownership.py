#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the ownership proofs. No token, no network."""

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


def repository(full_name, owner_id=1, fork=False):
    return {"full_name": full_name, "fork": fork, "owner": {"id": owner_id}}


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

    def test_a_link_to_a_fork_is_rejected(self):
        result = self.verify(self.api(owner_id=7, fork=True), author_id=7)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("fork", result.reason)

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

    def test_a_fork_never_stands_in_for_a_rename(self):
        api = FakeApi({"Maxi/Old": repository("Maxi/New", owner_id=7, fork=True)})
        self.assertFalse(
            ownership.renamed_into(hosted_at("Maxi/Old"), hosted_at("Maxi/New"), api)
        )

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


if __name__ == "__main__":
    unittest.main()
