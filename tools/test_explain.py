#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the prepared explanations. No token, no network."""

import io
import os
import sys
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import check_release
import check_tags
import explain
import ownership

PREFIX = "listings/LonelyPlanets.toml: the latest release 1.2.2 cannot be stamped: "
FOLDER = (
    PREFIX + "the archive's top-level directory is 'LonelyPlanets-1.2.2', which does not "
    "match the id 'LonelyPlanets'"
)


def stamper():
    """The stamper of content-index-releases, where it is checked out as CI checks it out."""
    root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
    if not (root / "tools" / "stamp_release.py").is_file():
        raise unittest.SkipTest("content-index-releases is not checked out next to this repository")
    return check_release.load_stamper(root)


def archive(*names):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as handle:
        for name in names:
            handle.writestr(name, "")
    data.seek(0)
    return zipfile.ZipFile(data)


class Release(unittest.TestCase):
    def test_a_folder_that_does_not_match_the_id(self):
        found = explain.explain(FOLDER)
        self.assertTrue(found.outside_pull_request)
        self.assertIn("folder `LonelyPlanets-1.2.2` at the top instead", found.text)
        self.assertIn(
            "When mod.toml is directly in `LonelyPlanets-1.2.2`, renaming that folder to "
            "`LonelyPlanets` is enough",
            found.text,
        )
        self.assertIn("into a new folder `LonelyPlanets`", found.text)
        self.assertIn("release `1.2.2` in place of the old one", found.text)

    def test_an_install_root_that_cannot_be_derived(self):
        found = explain.explain(
            PREFIX + "the install root is neither derivable from the archive nor authored: the "
            "standard layout is one top-level directory containing mod.toml, named 'LonelyPlanets'"
        )
        self.assertTrue(found.outside_pull_request)
        self.assertIn("The zip of release `1.2.2` has no such folder", found.text)
        self.assertIn("into one folder `LonelyPlanets`", found.text)

    def test_a_folder_whose_casing_differs(self):
        found = explain.explain(
            PREFIX + "the archive's top-level directory is 'lonelyplanets' and the id is "
            "'LonelyPlanets': the folder name is the identity the game sees, so the casing "
            "has to match"
        )
        self.assertTrue(found.outside_pull_request)
        self.assertIn("Only the casing differs", found.text)
        self.assertIn("is `lonelyplanets`, and the id is `LonelyPlanets`", found.text)
        self.assertIn("Rename the folder in the zip to `LonelyPlanets`, with mod.toml", found.text)

    def test_no_archive_names_the_assets_the_index_looks_for(self):
        found = explain.explain(
            "listings/LonelyPlanets.toml: the latest release v1.2.2 cannot be stamped: "
            "the release carries no archive to download"
        )
        self.assertTrue(found.outside_pull_request)
        self.assertIn("Release `v1.2.2` has no zip", found.text)
        self.assertIn(
            "`LonelyPlanets.zip`, `LonelyPlanets-1.2.2.zip` or `LonelyPlanets_1.2.2.zip`",
            found.text,
        )

    def test_several_archives_none_named_after_the_listing(self):
        found = explain.explain(
            PREFIX + "the release carries 2 archives and none of them is named after the "
            "listing (a.zip, b.zip), so there is nothing to stamp: the watcher does not guess "
            "which archive a client should verify against"
        )
        self.assertTrue(found.outside_pull_request)
        self.assertIn("(`a.zip, b.zip`)", found.text)
        self.assertIn("`LonelyPlanets-1.2.2.zip`", found.text)

    def test_a_value_cannot_break_out_of_its_code_span(self):
        found = explain.explain(
            PREFIX + "the archive's top-level directory is 'a`[x](y)`b', which does not "
            "match the id 'LonelyPlanets'"
        )
        self.assertIn("`a[x](y)b`", found.text)

    def test_an_unknown_message_has_no_explanation(self):
        self.assertIsNone(explain.explain("listings/X.toml: something nobody knows"))


class RealMessages(unittest.TestCase):
    """The rules match what the code says today, not a copy of it."""

    def test_the_folder_messages_of_the_stamper(self):
        stamp_release, _ = stamper()
        for folder in ("LonelyPlanets-1.2.2", "lonelyplanets"):
            with self.subTest(folder=folder):
                with self.assertRaises(stamp_release.StampError) as raised:
                    stamp_release.derive_root(archive(f"{folder}/mod.toml"), "LonelyPlanets", "mod")
                found = explain.explain(f"{PREFIX}{raised.exception}")
                self.assertIsNotNone(found)
                self.assertIn(f"`{folder}`", found.text)

    def test_a_folder_without_mod_toml_is_not_only_renamed(self):
        # The stamper names the only folder even when mod.toml is not in it. A
        # rename alone would then stamp cleanly and install the wrong files.
        stamp_release, _ = stamper()
        layouts = {
            "Assets": ("mod.toml", "LonelyPlanets.dll", "Assets/x.png"),
            "release": ("release/LonelyPlanets/mod.toml", "release/LonelyPlanets/a.dll"),
        }
        for folder, names in layouts.items():
            with self.subTest(folder=folder):
                with self.assertRaises(stamp_release.StampError) as raised:
                    stamp_release.derive_root(archive(*names), "LonelyPlanets", "mod")
                found = explain.explain(f"{PREFIX}{raised.exception}")
                self.assertIn(f"the folder `{folder}` at the top", found.text)
                self.assertIn(f"When mod.toml is directly in `{folder}`", found.text)
                self.assertIn("Otherwise, put mod.toml and the other files", found.text)
                self.assertNotIn("keep everything in it", found.text)

    def test_the_install_root_message_of_the_stamper(self):
        stamp_release, _ = stamper()
        for names in (("mod.toml", "LonelyPlanets.dll"), ("LonelyPlanets/mod.toml", "Other/mod.toml")):
            with self.subTest(names=names):
                with self.assertRaises(stamp_release.StampError) as raised:
                    stamp_release.install_object(archive(*names), "LonelyPlanets", "mod", None)
                found = explain.explain(f"{PREFIX}{raised.exception}")
                self.assertIsNotNone(found)
                self.assertIn("into one folder `LonelyPlanets`", found.text)

    def test_the_archive_messages_of_the_host(self):
        stamp_release, hosts = stamper()
        for candidates in ((), ("a.zip", "b.zip")):
            with self.subTest(candidates=candidates):
                release = SimpleNamespace(url=None, candidates=candidates, size=None)
                with self.assertRaises(stamp_release.StampError) as raised:
                    hosts.download(None, release)
                self.assertIsNotNone(explain.explain(f"{PREFIX}{raised.exception}"))

    def test_the_tag_notes(self):
        notes = check_tags.check_document(
            "listings/Mod.toml", {"type": "mod", "tags": ["shiny"]}, {"mod": ["parts"]}
        )
        self.assertEqual(len(notes), 2)
        first, second = (explain.explain(note) for note in notes)
        self.assertIn("The tag `shiny` can stay", first.text)
        self.assertIn(f"[the curated list]({check_tags.SPEC_URL})", first.text)
        self.assertFalse(first.outside_pull_request)
        self.assertIn("Add at least one tag", second.text)

    def test_the_ownership_reasons(self):
        class Api:
            def __init__(self, fork):
                self.fork = fork

            def repository(self, full_name):
                return {"full_name": full_name, "fork": self.fork, "owner": {"id": 1}}

            def topics(self, full_name):
                return []

            def file(self, full_name, path):
                return None

        listing = {"id": "LonelyPlanets", "releases": {"github": "Jared/KSA-LonelyPlanets"}}
        for fork in (False, True):
            with self.subTest(fork=fork):
                result = ownership.verify(listing, "Jared-Melchers", 9, Api(fork))
                self.assertEqual(result.state, ownership.UNVERIFIED)
                found = explain.explain(result.reason)
                self.assertTrue(found.outside_pull_request)
                self.assertIn(
                    "Add the topic `ksa-index-jared-melchers` to Jared/KSA-LonelyPlanets.",
                    found.text,
                )
                self.assertIn(
                    "[Jared/KSA-LonelyPlanets](https://github.com/Jared/KSA-LonelyPlanets)",
                    found.text,
                )


if __name__ == "__main__":
    unittest.main()
