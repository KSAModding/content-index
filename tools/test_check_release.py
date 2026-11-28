#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the archive inspection.
"""

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
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
        outcome = inspect({"id": "A", "type": "addon", "releases": {"github": "a/b"}})
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(outcome.messages, [])


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


class FolderStamper(FakeStamper):
    """A stamper that knows vehicles and saves (RFC 0085), reduced to what the inspection calls."""

    def __init__(self, error=None, holders=None, note=None):
        super().__init__(error)
        self.holders = holders or {}
        self.note = note
        self.checked = []

    def stamp(self, document, facts, archive, game_versions, notes=None):
        self.calls.append((document, facts, archive, game_versions))
        if self.error:
            raise self.error
        if self.note:
            notes.append(self.note)
        return {"id": document["id"], "type": document["type"], "install": {"folder": "Example Rover"}}

    def check_folder(self, stamped, holders):
        self.checked.append((stamped, dict(holders)))
        if holders.get("example rover"):
            raise StampError("`OtherRover` installs into the folder `Example Rover`")


VEHICLE = {"id": "OtherRover", "type": "vehicle", "releases": {"github": "owner/repo"}}


class Vehicles(unittest.TestCase):
    """A vehicle or a save is stamped with the notes, and its install folder is compared."""

    def run_inspect(self, document=VEHICLE, stamper=None, folders=None):
        self.host = FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")])
        self.read = []

        def read(content_type):
            self.read.append(content_type)
            if isinstance(folders, Exception):
                raise folders
            return folders or {}

        return check_release.inspect(
            document, stamper or FolderStamper(), FakeHosts(self.host), [], None, read
        )

    def test_a_vehicle_that_stamps_cleanly_passes_with_the_notes(self):
        stamper = FolderStamper(note="the vehicle folder holds files besides meta.toml and vehicle.xml")
        outcome = self.run_inspect(stamper=stamper)
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(
            outcome.messages,
            [
                "the latest release 1.0.0 stamps cleanly",
                "the vehicle folder holds files besides meta.toml and vehicle.xml",
            ],
        )
        self.assertEqual(self.read, ["vehicle"])
        stamped = {"id": "OtherRover", "type": "vehicle", "install": {"folder": "Example Rover"}}
        self.assertEqual(stamper.checked, [(stamped, {})])

    def test_a_save_reads_the_folders_of_saves(self):
        outcome = self.run_inspect(document=dict(VEHICLE, type="save"))
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(self.read, ["save"])

    def test_a_folder_another_listing_holds_is_rejected(self):
        outcome = self.run_inspect(folders={"example rover": ["ExampleRover"]})
        self.assertEqual(outcome.outcome, check_release.REJECT)
        self.assertEqual(
            outcome.messages,
            ["the latest release v1.0.0 cannot be stamped: `OtherRover` installs into the folder `Example Rover`"],
        )

    def test_folders_that_cannot_be_read_are_no_verdict_and_nothing_is_downloaded(self):
        outcome = self.run_inspect(folders=StampError("releases/X/1.0.0.json is not readable JSON"))
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertEqual(
            outcome.messages,
            [
                "the install folders of the other vehicle listings could not be read: "
                "releases/X/1.0.0.json is not readable JSON"
            ],
        )
        self.assertEqual(self.host.downloaded, [])

    def test_a_stamper_without_the_folder_check_is_no_verdict(self):
        outcome = self.run_inspect(stamper=FakeStamper())
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertIn("cannot stamp a vehicle yet", outcome.messages[0])

    def test_a_vehicle_without_a_host_reads_no_folders(self):
        outcome = self.run_inspect(document={"id": "OtherRover", "type": "vehicle"})
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(self.read, [])

    def test_a_mod_is_stamped_as_before_and_reads_no_folders(self):
        # FakeStamper.stamp takes no notes, so a mod still works with any stamper.
        stamper = FakeStamper()
        outcome = self.run_inspect(document=MOD, stamper=stamper)
        self.assertEqual(outcome.outcome, check_release.PASS)
        self.assertEqual(outcome.messages, ["the latest release 1.0.0 stamps cleanly"])
        self.assertEqual(self.read, [])

    def test_a_clean_stamp_holds_its_folder_for_the_rest_of_the_run(self):
        holders = {}
        stamper = FolderStamper()
        outcomes = [
            check_release.inspect(
                dict(VEHICLE, id=listing), stamper,
                FakeHosts(FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")])),
                [], None, lambda content_type: holders,
            )
            for listing in ("OtherRover", "ThirdRover")
        ]
        self.assertEqual([outcome.outcome for outcome in outcomes], [check_release.PASS, check_release.REJECT])
        self.assertEqual(holders, {"example rover": ["OtherRover"]})

    def test_the_folders_are_read_once_per_type_and_run(self):
        calls = []

        class Stamper:
            @staticmethod
            def folder_holders(folder, content_type):
                calls.append((folder.name, content_type))
                return {}

        folders = check_release._stamped_folders(Stamper(), "elsewhere")
        for content_type in ("vehicle", "vehicle", "save", "vehicle"):
            folders(content_type)
        self.assertEqual(calls, [("releases", "vehicle"), ("releases", "save")])


def zipped(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as handle:
        for name, text in files.items():
            handle.writestr(name, text)
    return data.getvalue()


class ZipHost(FakeHost):
    def __init__(self, releases, archive):
        super().__init__(releases)
        self.archive = archive

    def download(self, release):
        self.downloaded.append(release)
        return self.archive, "application/zip"


# As the game writes them, see UncompressedVehicleSave.Write and SaveMetaData.
META = 'name = "Example Rover"\ncreated = 2026-09-22T14:22:28.6152545\nversion = "v2026.9.22.5482"\n'
VEHICLE_XML = '<?xml version="1.0" encoding="utf-8"?>\n<VehicleSaveData><Parts /></VehicleSaveData>\n'
UNIVERSE_XML = '<?xml version="1.0" encoding="utf-8"?>\n<UniverseData />\n'
ROVER = {"Example Rover/meta.toml": META, "Example Rover/vehicle.xml": VEHICLE_XML}

AUTHORED_VEHICLE = {
    "spec_version": 1,
    "id": "ExampleRover",
    "type": "vehicle",
    "name": "Example Rover",
    "authors": ["Maxi"],
    "abstract": "A rover for the Moon.",
    "license": "CC-BY-4.0",
    "releases": {"github": "owner/repo"},
}


class VehiclesWithTheRealStamper(unittest.TestCase):
    """The archive rules of RFC 0085, as the stamper of content-index-releases applies them."""

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        if not (root / "tools" / "stamp_release.py").is_file():
            raise unittest.SkipTest("content-index-releases is not checked out next to this repository")
        cls.stamp_release, cls.hosts = check_release.load_stamper(root)
        if not hasattr(cls.stamp_release, "check_folder"):
            raise unittest.SkipTest("the checkout of content-index-releases cannot stamp a vehicle yet")
        cls.game_versions = check_release.load_game_versions(root)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.releases = Path(folder.name) / "releases"
        self.releases.mkdir()

    def hold(self, listing, folder, content_type="vehicle"):
        """A stamped release of `listing` that installs into `folder`."""
        (self.releases / listing).mkdir()
        document = {"id": listing, "type": content_type, "install": {"folder": folder}}
        (self.releases / listing / "1.0.0.json").write_text(json.dumps(document), encoding="utf-8")

    def inspect(self, files, document=AUTHORED_VEHICLE):
        host = ZipHost([FakeRelease("v1.0.0", "1.0.0", "2026-10-01T00:00:00Z")], zipped(files))

        def folders(content_type):
            return self.stamp_release.folder_holders(self.releases, content_type)

        return check_release.inspect(
            document, self.stamp_release, FakeHosts(host), self.game_versions, None, folders
        )

    def assert_rejected(self, outcome, *words):
        self.assertEqual(outcome.outcome, check_release.REJECT, outcome.messages)
        self.assertTrue(outcome.messages[0].startswith("the latest release v1.0.0 cannot be stamped: "))
        for word in words:
            self.assertIn(word, outcome.messages[0])

    def test_a_vehicle_as_the_game_wrote_it_passes(self):
        outcome = self.inspect(ROVER)
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)
        self.assertEqual(outcome.messages, ["the latest release 1.0.0 stamps cleanly"])

    def test_a_save_as_the_game_wrote_it_passes(self):
        files = {"Example Rover/meta.toml": META, "Example Rover/universe.xml": UNIVERSE_XML}
        outcome = self.inspect(files, dict(AUTHORED_VEHICLE, type="save"))
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)

    def test_other_files_in_a_vehicle_pass_with_a_note(self):
        outcome = self.inspect({**ROVER, "Example Rover/thumbnail.png": "x"})
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)
        self.assertEqual(len(outcome.messages), 2)
        self.assertIn("besides meta.toml and vehicle.xml", outcome.messages[1])
        self.assertIn('"thumbnail.png"', outcome.messages[1])

    def test_a_meta_toml_that_does_not_parse_is_rejected(self):
        outcome = self.inspect({**ROVER, "Example Rover/meta.toml": "name = Example Rover\n"})
        self.assert_rejected(outcome, "Example Rover/meta.toml is not valid TOML")

    def test_a_name_the_game_would_change_is_rejected(self):
        meta = META.replace("Example Rover", "Rover.v2")
        outcome = self.inspect({"Rover.v2/meta.toml": meta, "Rover.v2/vehicle.xml": VEHICLE_XML})
        self.assert_rejected(outcome, "`name` in the archive's Rover.v2/meta.toml is 'Rover.v2'", "(RFC 0085)")

    def test_a_root_folder_that_is_not_the_name_is_rejected(self):
        files = {"Rover/meta.toml": META, "Rover/vehicle.xml": VEHICLE_XML}
        self.assert_rejected(self.inspect(files), "the archive's folder is 'Rover'", "`name` 'Example Rover'")

    def test_a_vehicle_without_its_game_file_is_rejected(self):
        outcome = self.inspect({"Example Rover/meta.toml": META})
        self.assert_rejected(outcome, "has no Example Rover/vehicle.xml, so the game does not see the vehicle")

    def test_a_folder_another_vehicle_holds_is_rejected(self):
        self.hold("ExampleRover", "example rover")
        outcome = self.inspect(ROVER, dict(AUTHORED_VEHICLE, id="OtherRover"))
        self.assert_rejected(
            outcome, "`OtherRover` installs into the folder `Example Rover`", "vehicle listing `ExampleRover`"
        )

    def test_two_vehicles_of_one_run_with_the_same_folder(self):
        # The folders are cached once per run, as inspect_paths reads them.
        folders = check_release._stamped_folders(self.stamp_release, self.releases.parent)
        outcomes = []
        for listing in ("ExampleRover", "OtherRover"):
            host = ZipHost([FakeRelease("v1.0.0", "1.0.0", "2026-10-01T00:00:00Z")], zipped(ROVER))
            outcomes.append(check_release.inspect(
                dict(AUTHORED_VEHICLE, id=listing), self.stamp_release, FakeHosts(host),
                self.game_versions, None, folders,
            ))
        self.assertEqual(outcomes[0].outcome, check_release.PASS, outcomes[0].messages)
        self.assert_rejected(
            outcomes[1], "`OtherRover` installs into the folder `Example Rover`", "vehicle listing `ExampleRover`"
        )

    def test_its_own_older_release_and_a_save_with_the_folder_are_no_collision(self):
        self.hold("ExampleRover", "Example Rover")
        self.hold("ExampleBase", "Example Rover", "save")
        outcome = self.inspect(ROVER)
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)

    def test_a_tag_prefix_takes_the_release_of_this_vehicle_from_a_shared_repository(self):
        listed = [
            ("OtherShip-v2.0.0", "2026-10-02T00:00:00Z", "OtherShip.zip"),
            ("ExampleRover-v1.0.0", "2026-10-01T00:00:00Z", "ExampleRover.zip"),
            ("ExampleBase-v3.0.0", "2026-10-03T00:00:00Z", "ExampleBase.zip"),
        ]
        body = json.dumps([
            {
                "tag_name": tag,
                "published_at": date,
                "assets": [{
                    "name": name,
                    "state": "uploaded",
                    "content_type": "application/zip",
                    "size": 100,
                    "browser_download_url": f"https://example.invalid/{name}",
                }],
            }
            for tag, date, name in listed
        ]).encode()
        archive = zipped(ROVER)
        hosts = self.hosts

        class Http:
            fetched = []

            def get(self, url, **_):
                return hosts.Response(200, {}, body)

            def archive(self, url, **_):
                self.fetched.append(url)
                return archive, {"Content-Type": "application/zip"}

            def log(self, message):
                pass

        http = Http()
        document = dict(AUTHORED_VEHICLE, releases={"github": "owner/shares", "tag_prefix": "ExampleRover-v"})
        outcome = check_release.inspect(
            document, self.stamp_release, self.hosts, self.game_versions, http,
            lambda content_type: self.stamp_release.folder_holders(self.releases, content_type),
        )
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)
        self.assertEqual(outcome.messages, ["the latest release 1.0.0 stamps cleanly"])
        self.assertEqual(http.fetched, ["https://example.invalid/ExampleRover.zip"])


class ShareHosts:
    """The hosts module of a stamper that reads share hosts (RFC 0094)."""

    HostError = HostError

    def __init__(self, authority=None, build_error=None, registry_error=None):
        self.authority = authority
        self.build_error = build_error
        self.registry_error = registry_error
        self.built = []
        self.roots = []

    def registered(self, root):
        self.roots.append(root)
        if self.registry_error:
            raise self.registry_error
        return {"ksamods": {"kind": "share"}}

    def build(self, section, http, listing_id=None, content_type=None, registry=None):
        self.built.append((section, listing_id, content_type, registry))
        if self.build_error:
            raise self.build_error
        return self.authority, []


SHARED = {"id": "ExampleRover", "type": "vehicle", "releases": {"ksamods": "ExampleRover"}}


class ShareHost(unittest.TestCase):
    def inspect(self, document, hosts):
        return check_release.inspect(document, FolderStamper(), hosts, [], None, lambda content_type: {})

    def test_the_type_and_the_tables_of_hosts_toml_reach_the_stamper(self):
        hosts = ShareHosts(FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")]))
        outcome = self.inspect(SHARED, hosts)
        self.assertEqual(outcome.outcome, check_release.PASS, outcome.messages)
        self.assertEqual(hosts.roots, [check_release.ROOT])
        self.assertEqual(
            hosts.built,
            [({"ksamods": "ExampleRover"}, "ExampleRover", "vehicle", {"ksamods": {"kind": "share"}})],
        )

    def test_a_mod_reaches_the_stamper_with_its_type_too(self):
        hosts = ShareHosts(FakeHost())
        check_release.inspect(MOD, FakeStamper(), hosts, [], None)
        self.assertEqual(hosts.built[0][2], "mod")

    def test_a_share_host_the_stamper_refuses_is_rejected(self):
        error = StampError("[releases] names `otherhost`, which is neither github nor spacedock")
        outcome = self.inspect(SHARED, ShareHosts(build_error=error))
        self.assertEqual((outcome.outcome, outcome.messages), (check_release.REJECT, [str(error)]))

    def test_a_table_the_stamper_cannot_read_is_no_verdict(self):
        outcome = self.inspect(SHARED, ShareHosts(build_error=HostError("the host `ksamods` is of kind 'mirror'")))
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertIn("is of kind 'mirror'", outcome.messages[0])

    def test_a_hosts_toml_that_does_not_read_is_no_verdict(self):
        outcome = self.inspect(SHARED, ShareHosts(registry_error=HostError("hosts.toml does not read")))
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE)
        self.assertIn("hosts.toml does not read", outcome.messages[0])

    def test_a_stamper_that_reads_no_share_host_is_no_verdict(self):
        hosts = FakeHosts(FakeHost())
        outcome = self.inspect(SHARED, hosts)
        self.assertEqual(
            (outcome.outcome, outcome.messages),
            (check_release.COULD_NOT_EVALUATE, ["the stamper of content-index-releases cannot read a share host yet"]),
        )

    def test_that_stamper_still_inspects_a_listing_without_a_share_host(self):
        outcome = inspect(MOD, host=FakeHost([FakeRelease("v1.0.0", "1.0.0", "2026-08-01T00:00:00Z")]))
        self.assertEqual(outcome.outcome, check_release.PASS)


class ShareHostWithTheRealStamper(unittest.TestCase):
    """The size limit of a share host, as the stamper of content-index-releases applies it."""

    @classmethod
    def setUpClass(cls):
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        if not (root / "tools" / "stamp_release.py").is_file():
            raise unittest.SkipTest("content-index-releases is not checked out next to this repository")
        cls.stamp_release, cls.hosts = check_release.load_stamper(root)
        if not hasattr(cls.hosts, "registered"):
            raise unittest.SkipTest("the checkout of content-index-releases reads no share host yet")

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        (Path(folder.name) / "hosts.toml").write_text(
            '[ksamods]\nkind = "share"\nstorage = "ksamods-content/share"\ntypes = ["vehicle"]\n'
            "max_bytes = { vehicle = 1048576 }\n",
            encoding="utf-8",
        )
        patch = mock.patch.object(check_release, "ROOT", Path(folder.name))
        patch.start()
        self.addCleanup(patch.stop)

    def inspect(self, size):
        hosts = self.hosts
        listing = {"id": "ExampleRover", "type": "vehicle", "releases": [{"version": "1.0.0", "status": "stable"}]}
        release = {
            "published_at": "2026-10-01T00:00:00Z",
            "assets": [{
                "name": "ExampleRover-1.0.0.zip",
                "state": "uploaded",
                "size": size,
                "content_type": "application/zip",
                "browser_download_url": "https://github.com/ksamods-content/share/releases/download/x/ExampleRover-1.0.0.zip",
            }],
        }
        archives = []

        class Http:
            def get(self, url, **_):
                body = listing if "/contents/" in url else release
                return hosts.Response(200, {}, json.dumps(body).encode())

            def archive(self, url, **_):
                archives.append(url)
                raise hosts.HostError("not downloaded in this test")

            def log(self, message):
                pass

        outcome = check_release.inspect(
            SHARED, self.stamp_release, hosts, [], Http(), lambda content_type: {}
        )
        return outcome, archives

    def test_an_archive_above_max_bytes_of_its_type_is_rejected_unread(self):
        outcome, archives = self.inspect(2 * 1048576)
        self.assertEqual(outcome.outcome, check_release.REJECT, outcome.messages)
        self.assertIn("above the 1 MiB limit", outcome.messages[0])
        self.assertEqual(archives, [])

    def test_an_archive_within_the_limit_is_downloaded(self):
        outcome, archives = self.inspect(1048576)
        self.assertEqual(outcome.outcome, check_release.COULD_NOT_EVALUATE, outcome.messages)
        self.assertEqual(len(archives), 1)


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
