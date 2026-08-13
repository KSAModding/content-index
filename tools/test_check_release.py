#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the archive inspection.
"""

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

    def __init__(self, authority=None, build_error=None):
        self.authority = authority
        self.build_error = build_error

    def build(self, section, http, listing_id=None):
        if self.build_error:
            raise self.build_error
        return self.authority, []


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
