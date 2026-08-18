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
        api = FakeApi({"Maxi/Mod": repository("Maxi/Mod", owner_id=7)})
        result = self.change(
            api,
            {"id": "AutoStage", "releases": dict(hosts, authority="github")},
            {"id": "AutoStage", "releases": dict(hosts, authority="spacedock")},
            login="Maxi",
        )
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("moves to", result.reason)
        self.assertIn("no ownership proof", result.reason)

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
