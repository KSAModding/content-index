#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the privileged mod pack ownership decision."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import ownership
import pack_ownership

PATH = "packs/Starter/1.0.0.toml"
OWNER = "packs/Starter/owner.json"
HEAD = "head1234567890"
BASE = "main"


def owner(login="Maxi", account_id=7):
    return json.dumps({"github_login": login, "github_id": account_id})


def pull(login="Maxi", account_id=7, base=BASE):
    return {"user": {"login": login, "id": account_id}, "base": {"ref": base}}


class Api:
    repository = "KSAModding/content-index"

    def __init__(self, files=None):
        self.files = files or {}
        self.reads = []

    def file(self, repository, path, ref=None):
        self.reads.append((path, ref))
        return self.files.get((path, ref))


class PackOwnership(unittest.TestCase):
    def test_a_first_claim_by_its_own_author_verifies(self):
        api = Api({(OWNER, HEAD): owner()})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, pack_ownership.PROOF)

    def test_a_first_claim_matches_the_login_in_any_case(self):
        api = Api({(OWNER, HEAD): owner("maxi")})
        result = pack_ownership.verify(api, pull("Maxi"), PATH, HEAD)
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_a_first_claim_must_name_the_login_of_the_author_too(self):
        api = Api({(OWNER, HEAD): owner("Somebody", 7)})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.REJECTED)

    def test_a_first_claim_must_record_the_pull_request_author(self):
        api = Api({(OWNER, HEAD): owner("Attacker", 9)})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.REJECTED)
        self.assertIn("account that opened", result.reason)

    def test_head_content_cannot_replace_the_recorded_owner(self):
        api = Api({(OWNER, BASE): owner("Victim", 8), (OWNER, HEAD): owner()})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.UNVERIFIED)
        self.assertIn("not the recorded owner", result.reason)
        self.assertNotIn((OWNER, HEAD), api.reads)

    def test_the_recorded_account_can_add_a_version(self):
        api = Api({(OWNER, BASE): owner()})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.VERIFIED)
        self.assertEqual(result.proof, "pack owner record")

    def test_the_numeric_account_id_survives_a_login_change(self):
        api = Api({(OWNER, BASE): owner("OldName", 7)})
        result = pack_ownership.verify(api, pull("NewName", 7), PATH, HEAD)
        self.assertEqual(result.state, ownership.VERIFIED)

    def test_an_existing_version_is_rejected_even_when_the_diff_calls_it_added(self):
        api = Api({(PATH, BASE): 'id = "Starter"\n', (OWNER, BASE): owner()})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.REJECTED)
        self.assertIn("immutable", result.reason)

    def test_a_malformed_base_record_reaches_no_verdict(self):
        api = Api({(OWNER, BASE): "not json"})
        result = pack_ownership.verify(api, pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.COULD_NOT_EVALUATE)

    def test_a_first_claim_without_an_owner_record_is_rejected(self):
        result = pack_ownership.verify(Api(), pull(), PATH, HEAD)
        self.assertEqual(result.state, ownership.REJECTED)
        self.assertIn(OWNER, result.reason)


if __name__ == "__main__":
    unittest.main()
