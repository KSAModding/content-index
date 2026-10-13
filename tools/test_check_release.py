#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the archive inspection.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_release


class StampError(Exception):
    """Stands in for the stamper's own, which means the release is wrong."""


class HostError(Exception):
    """Stands in for the hosts' own, which means this run could not tell."""


class FakeRelease:
    def __init__(self, tag, version, date, url="https://example.invalid/a.zip"):
        self.tag = tag
        self.version = version
        self.release_date = date
        self.url = url

    def facts(self):
        return {"tag": self.tag, "release_date": self.release_date, "url": self.url}


class FakeHost:
    key = "github:owner/repo"

    def __init__(self, releases=(), releases_error=None, download_error=None):
        self._releases = list(releases)
        self._releases_error = releases_error
        self._download_error = download_error
        self.downloaded = []

    def releases(self, etag=None):
        if self._releases_error:
            raise self._releases_error
        return self._releases, None

    def download(self, release):
        if self._download_error:
            raise self._download_error
        self.downloaded.append(release)
        return b"archive-bytes", "application/zip"


class FakeStamper:
    """The stamper module, reduced to what the inspection calls."""

    StampError = StampError

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def stamp(self, document, facts, archive, game_versions):
        self.calls.append((document, facts, archive, game_versions))
        if self.error:
            raise self.error
        return {"stamped": True}


class FakeHosts:
    """The hosts module, reduced to what the inspection calls."""

    HostError = HostError

    def __init__(self, authority=None, build_error=None, mirrors=()):
        self.authority = authority
        self.build_error = build_error
        self.mirrors = list(mirrors)

    def build(self, section, http, listing_id=None):
        if self.build_error:
            raise self.build_error
        return self.authority, self.mirrors


MOD = {
    "id": "TestMod",
    "type": "mod",
    "releases": {"github": "owner/repo"},
}


def inspect(document, host=None, stamper=None, hosts=None):
    stamper = stamper or FakeStamper()
    hosts = hosts or FakeHosts(host)
    return check_release.inspect(document, stamper, hosts, ["2026.8.3.5117"], http=None)


class Vacuous(unittest.TestCase):
    """The cases RFC 0033 says pass without an archive being read."""

    def test_a_pack_has_no_archive(self):
        outcome = inspect({"id": "Pack", "type": "modpack"})
        self.assertEqual(outcome.outcome, check_release.PASS)
        # The line tells the author nothing, so it goes into the job summary only.
        self.assertEqual(outcome.messages, [])
        self.assertIn("nothing to inspect", outcome.summary[0])

    def test_a_listing_with_no_release_host(self):
        outcome = inspect({"id": "Mod", "type": "mod"})
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertIn("no release host", outcome.messages[0])

    def test_a_listing_whose_releases_section_is_empty(self):
        outcome = inspect({"id": "Mod", "type": "mod", "releases": {}})
        self.assertEqual(outcome.outcome, check_release.PASS)

    def test_a_host_with_no_release_yet(self):
        outcome = inspect(MOD, host=FakeHost([]))
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertIn("no release yet", outcome.messages[0])

    def test_an_unknown_content_type_is_not_inspected(self):
        outcome = inspect({"id": "V", "type": "vehicle", "releases": {"github": "a/b"}})
        self.assertEqual(outcome.outcome, check_release.PASS)


class Passing(unittest.TestCase):
    def test_a_release_that_stamps_cleanly(self):
        host = FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")])
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertIn("1.0.0", outcome.messages[0])

    def test_only_the_latest_release_is_downloaded(self):
        host = FakeHost(
            [
                FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z"),
                FakeRelease("v1.1.0", "1.1.0", "2026-08-05T00:00:00Z"),
            ]
        )
        inspect(MOD, host=host)
        self.assertEqual([release.tag for release in host.downloaded], ["v1.1.0"])

    def test_the_content_type_the_host_served_reaches_the_stamper(self):
        host = FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")])
        stamper = FakeStamper()
        inspect(MOD, host=host, stamper=stamper)
        self.assertEqual(stamper.calls[0][1]["content_type"], "application/zip")


class Rejecting(unittest.TestCase):
    def test_a_release_the_stamper_refuses(self):
        host = FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")])
        stamper = FakeStamper(error=StampError("the archive is not a readable zip"))
        outcome = inspect(MOD, host=host, stamper=stamper)
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertIn("not a readable zip", outcome.messages[0])
        self.assertIn("v1.0.0", outcome.messages[0])

    def test_a_host_that_says_the_repository_is_gone(self):
        host = FakeHost(releases_error=StampError("the authority host has no repository"))
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.REJECT)

    def test_a_releases_section_the_hosts_refuse_to_build(self):
        hosts = FakeHosts(build_error=StampError("it needs an 'authority' key"))
        outcome = inspect(MOD, hosts=hosts)
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertIn("authority", outcome.messages[0])

    def test_a_gone_archive(self):
        host = FakeHost(
            [FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")],
            download_error=StampError("the archive is gone (HTTP 404)"),
        )
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.REJECT)

    def test_a_host_whose_releases_all_have_unparseable_versions(self):
        host = FakeHost([FakeRelease("rc", None, "2026-08-02T00:00:00Z")])
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertIn("nothing can ever be stamped", outcome.messages[0])


class TagPrefix(unittest.TestCase):
    """A tag_prefix takes the other releases of the repository out of the list (RFC 0096)."""

    @staticmethod
    def host(releases, skipped, prefix="gatos-v"):
        host = FakeHost(releases)
        host.key = f"github:o/gatos#{prefix}"
        host.tag_prefix = prefix
        host.skipped = skipped
        return host

    def test_a_prefix_that_matches_no_release_is_rejected(self):
        outcome = inspect(MOD, host=self.host([], skipped=3, prefix="mod-v"))
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertEqual(
            outcome.messages,
            [
                "github:o/gatos#mod-v has 3 release(s) and the tag of none of them starts with "
                "the tag_prefix `mod-v`, so nothing can ever be stamped"
            ],
        )

    def test_a_repository_without_releases_still_passes(self):
        outcome = inspect(MOD, host=self.host([], skipped=0))
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertIn("no release yet", outcome.messages[0])

    def test_a_prefix_that_matches_a_release_inspects_it(self):
        release = FakeRelease("gatos-v1.2.0", "1.2.0", "2026-09-01T00:00:00Z")
        host = self.host([release], skipped=2)
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(host.downloaded, [release])

    def test_a_release_message_names_the_prefix(self):
        release = FakeRelease("gatos-v1.2.0", "1.2.0", "2026-09-01T00:00:00Z")
        release.tag_prefix = "gatos-v"
        stamper = FakeStamper(error=StampError("the release carries no archive to download"))
        outcome = inspect(MOD, host=self.host([release], skipped=0), stamper=stamper)
        self.assertEqual(
            outcome.messages,
            [
                "the latest release gatos-v1.2.0 (tag_prefix `gatos-v`) cannot be stamped: "
                "the release carries no archive to download"
            ],
        )

    def test_a_prefix_on_a_mirror_that_matches_no_release_is_rejected(self):
        authority = FakeHost([])
        authority.key = "spacedock:1"
        mirror = self.host([], skipped=2, prefix="typo-v")
        outcome = inspect(MOD, hosts=FakeHosts(authority, mirrors=[mirror]))
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertEqual(
            outcome.messages,
            [
                "github:o/gatos#typo-v has 2 release(s) and the tag of none of them starts with "
                "the tag_prefix `typo-v`, so nothing can ever be stamped"
            ],
        )

    def test_a_mirror_whose_prefix_matches_still_inspects_the_authority(self):
        release = FakeRelease("1.2.0", "1.2.0", "2026-09-01T00:00:00Z")
        authority = FakeHost([release])
        mirror = self.host([FakeRelease("gatos-v1.2.0", "1.2.0", None)], skipped=1)
        outcome = inspect(MOD, hosts=FakeHosts(authority, mirrors=[mirror]))
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(authority.downloaded, [release])

    def test_a_mirror_that_cannot_be_read_is_not_a_verdict(self):
        mirror = self.host([], skipped=0)
        mirror._releases_error = HostError("HTTP 503")
        outcome = inspect(MOD, hosts=FakeHosts(FakeHost([]), mirrors=[mirror]))
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertEqual(outcome.messages, ["github:o/gatos#gatos-v could not be read: HTTP 503"])

    def test_a_mirror_without_a_prefix_is_not_read(self):
        mirror = FakeHost(releases_error=HostError("HTTP 503"))
        outcome = inspect(MOD, hosts=FakeHosts(FakeHost([]), mirrors=[mirror]))
        self.assertEqual(outcome.outcome, check_release.PASS)


class TagPrefixWithTheRealHosts(unittest.TestCase):
    """The hosts of content-index-releases, where the checkout has RFC 0096."""

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        if not (root / "tools" / "stamp_release.py").is_file():
            raise unittest.SkipTest("content-index-releases is not checked out next to this repository")
        cls.stamp_release, cls.hosts = check_release.load_stamper(root)
        if not hasattr(cls.hosts, "tag_prefix"):
            raise unittest.SkipTest("the checkout of content-index-releases has no tag_prefix yet")

    def inspect(self, section, tags):
        body = json.dumps([
            {"tag_name": tag, "published_at": "2026-10-01T00:00:00Z", "assets": []} for tag in tags
        ]).encode()

        class Http:
            def get(self, url, **_):
                if "spacedock" in url:
                    return self.hosts.Response(200, {}, b'{"versions": []}')
                return self.answer

            def log(self, message):
                pass

        http = Http()
        http.hosts = self.hosts
        http.answer = self.hosts.Response(200, {}, body)
        document = {"id": "gatOS", "type": "mod", "releases": section}
        return check_release.inspect(document, self.stamp_release, self.hosts, [], http)

    def test_a_prefix_that_matches_no_tag_is_rejected(self):
        # The match is case-sensitive, as GitHub compares tags.
        for prefix in ("mod-v", "GATOS-"):
            outcome = self.inspect({"github": "o/gatos", "tag_prefix": prefix}, ["gatos-v1.0.0", "vm-images-1"])
            self.assertEqual(outcome.outcome, check_release.REJECT, prefix)
            self.assertIn(f"none of them starts with the tag_prefix `{prefix}`", outcome.messages[0])

    def test_a_prefix_on_a_mirror_that_matches_no_tag_is_rejected(self):
        section = {"github": "o/gatos", "spacedock": 1, "authority": "spacedock", "tag_prefix": "typo-v"}
        outcome = self.inspect(section, ["gatos-v1.0.0", "vm-images-1"])
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertEqual(
            outcome.messages,
            [
                "github:o/gatos#typo-v has 2 release(s) and the tag of none of them starts with "
                "the tag_prefix `typo-v`, so nothing can ever be stamped"
            ],
        )

    def test_the_messages_of_the_watcher_reject_an_invalid_prefix(self):
        for section, words in (
            ({"github": "o/gatos", "tag_prefix": "gatos v"}, "is not a non-empty ASCII string"),
            ({"spacedock": 1, "tag_prefix": "gatos-v"}, "it needs a github key next to it"),
        ):
            outcome = self.inspect(section, [])
            self.assertEqual(outcome.outcome, check_release.REJECT, section)
            self.assertIn(words, outcome.messages[0])


class CouldNotEvaluate(unittest.TestCase):
    def test_a_host_having_a_bad_moment(self):
        host = FakeHost(releases_error=HostError("HTTP 503"))
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertIn("503", outcome.messages[0])

    def test_an_archive_that_did_not_download_this_run(self):
        host = FakeHost(
            [FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")],
            download_error=HostError("HTTP 502"),
        )
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)

    def test_a_network_error_is_not_a_rejection(self):
        host = FakeHost(releases_error=OSError("connection reset"))
        outcome = inspect(MOD, host=host)
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)


class Latest(unittest.TestCase):
    def test_the_most_recently_published_release_wins(self):
        old = FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")
        new = FakeRelease("v0.9.0", "0.9.0", "2026-08-09T00:00:00Z")
        self.assertIs(check_release.latest([old, new]), new)

    def test_a_release_with_no_parseable_version_is_stepped_over(self):
        good = FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")
        bad = FakeRelease("rc", None, "2026-08-09T00:00:00Z")
        self.assertIs(check_release.latest([good, bad]), good)

    def test_nothing_parseable_gives_nothing(self):
        self.assertIsNone(check_release.latest([FakeRelease("rc", None, "2026-08-09T00:00:00Z")]))

    def test_no_releases_at_all_gives_nothing(self):
        self.assertIsNone(check_release.latest([]))

    def test_the_tag_breaks_a_tie_on_the_date(self):
        first = FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")
        second = FakeRelease("v1.0.1", "1.0.1", "2026-08-01T00:00:00Z")
        self.assertIs(check_release.latest([first, second]), second)

    def test_a_release_with_no_date_does_not_crash_the_ordering(self):
        undated = FakeRelease("v1.0.0", "1.0.0", None)
        dated = FakeRelease("v1.1.0", "1.1.0", "2026-08-01T00:00:00Z")
        self.assertIs(check_release.latest([undated, dated]), dated)


class Loading(unittest.TestCase):
    def test_a_missing_stamper_is_reported_rather_than_guessed_at(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(check_release.Unavailable):
                check_release.load_stamper(folder)

    def test_a_missing_game_release_list_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(check_release.Unavailable):
                check_release.load_game_versions(folder)

    def test_the_real_stamper_imports_when_the_checkout_is_there(self):
        # The same two places load_stamper looks, so this runs wherever it can
        # run. CI sets the environment variable and checks the stamper out, and
        # without both this test would only ever pass on a contributor's
        # machine while guarding a cross-repository contract nobody else sees.
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        if not (root / "tools" / "stamp_release.py").is_file():
            self.skipTest("content-index-releases is not checked out next to this repository")
        stamp_release, hosts = check_release.load_stamper(root)
        self.assertTrue(hasattr(stamp_release, "stamp"))
        self.assertTrue(hasattr(stamp_release, "StampError"))
        self.assertTrue(hasattr(hosts, "build"))
        self.assertTrue(hasattr(hosts, "HostError"))
        self.assertTrue(hasattr(hosts, "Http"))
        versions = check_release.load_game_versions(root)
        self.assertTrue(versions)


if __name__ == "__main__":
    unittest.main()
