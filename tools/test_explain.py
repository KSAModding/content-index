#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the prepared explanations. No token, no network."""

import copy
import functools
import io
import json
import os
import re
import socket
import string
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import check_edits
import check_image_references
import check_images
import check_index
import check_layout
import check_license
import check_packs
import check_release
import check_schema
import check_tags
import decide
import explain
import images
import ownership
import validate
from test_images import PUBLIC, Network, Response, png

PREFIX = "listings/LonelyPlanets.toml: the latest release 1.2.2 cannot be stamped: "
FOLDER = (
    PREFIX + "the archive's top-level directory is 'LonelyPlanets-1.2.2', which does not "
    "match the id 'LonelyPlanets'"
)


def releases_root():
    """The checkout of content-index-releases, where CI checks it out."""
    root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
    if not (root / "tools" / "stamp_release.py").is_file():
        raise unittest.SkipTest("content-index-releases is not checked out next to this repository")
    return root


def stamper():
    """The stamper of content-index-releases, where it is checked out as CI checks it out."""
    return check_release.load_stamper(releases_root())


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

    def test_no_archive_names_the_assets_without_the_tag_prefix(self):
        found = explain.explain(
            "listings/gatOS.toml: the latest release gatos-v1.0.0 (tag_prefix `gatos-`) cannot be "
            "stamped: the release carries no archive to download"
        )
        self.assertIn("Release `gatos-v1.0.0` has no zip", found.text)
        self.assertIn("`gatOS.zip`, `gatOS-1.0.0.zip` or `gatOS_1.0.0.zip`", found.text)

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


WHERE = "listings/MyMod.toml"
PACK_WHERE = "packs/my-pack/1.0.0.toml"
DELETE = object()

MOD = {
    "spec_version": 1,
    "id": "MyMod",
    "type": "mod",
    "name": "My Mod",
    "authors": ["Me"],
    "abstract": "A mod.",
    "license": "MIT",
    "links": {"forums": "https://forums.ahwoo.com/threads/my-mod.783/"},
    "compatibility": {"game_min": "2026.10"},
    "releases": {"github": "me/MyMod"},
}
PACK = {
    "spec_version": 1,
    "id": "my-pack",
    "type": "modpack",
    "name": "My Pack",
    "authors": ["Me"],
    "abstract": "A pack.",
    "license": "MIT",
    "links": {"forums": "https://forums.ahwoo.com/threads/my-pack.784/"},
    "compatibility": {"game_min": "2026.10"},
    "version": "1.0.0",
    "released_at": "2026-01-01T00:00:00Z",
    "mods": [{"id": "Lib", "version": "1.0.0"}],
}
IMAGE = {"url": "https://example.invalid/a.png", "sha256": "a" * 64, "width": 512, "height": 512, "size": 1000}
SIGNED = (
    "https://forums.example.invalid/attachments/2036.data?X-Amz-Algorithm=AWS4-HMAC-SHA256&"
    "X-Amz-Expires=60&X-Amz-SignedHeaders=host&X-Amz-Signature=abc"
)
FACTS = {"tag": "v1.2.0", "release_date": "2026-10-01T00:00:00Z", "url": "https://example.invalid/MyMod.zip"}
GOOD = {"MyMod/mod.toml": 'name = "MyMod"\n', "MyMod/MyMod.dll": "x"}
KSA_MOD = {"id": 4256, "game_id": ownership.SPACEDOCK_GAME_ID, "source_code": ""}


def one(messages, needle=""):
    """The first message that has `needle` in it."""
    for message in messages:
        if needle in message:
            return message
    raise AssertionError(f"no message has {needle!r}: {messages!r}")


@functools.cache
def validator():
    return check_schema.validator()


def changed(document, path, value):
    """A copy of `document` with the dotted `path` set to `value`, or removed with DELETE."""
    document = copy.deepcopy(document)
    *parents, key = path.split(".")
    node = document
    for parent in parents:
        node = node.setdefault(parent, {})
    if value is DELETE:
        node.pop(key, None)
    else:
        node[key] = value
    return document


def schema(path, value, base=MOD):
    errors = []
    where = PACK_WHERE if base is PACK else WHERE
    check_schema.check_parsed(where, changed(base, path, value), validator(), errors)
    return errors


def layout(files):
    """The layout errors of `files`, written into an empty repository."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        for name in ("listings", "packs"):
            (root / name).mkdir()
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return check_layout.check(root / "listings", root / "packs")


def edited_pack():
    with tempfile.TemporaryDirectory() as folder:
        packs = Path(folder) / "packs"
        (packs / "my-pack").mkdir(parents=True)
        (packs / "my-pack" / "1.0.0.toml").write_text('id = "my-pack"\n', encoding="utf-8")
        owner = {"github_login": "me", "github_id": 1}
        (packs / "my-pack" / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
        change = SimpleNamespace(path=PACK_WHERE, previous_path=None, status="modified")
        return check_packs.check([change], packs)


def entry(where, document):
    identifier = document["id"]
    holder = ("pack" if document["type"] == "modpack" else "listing", identifier)
    return check_index.Entry(Path(where), where, holder, identifier, document)


def pack_members(*pins):
    with tempfile.TemporaryDirectory() as folder:
        releases = Path(folder)
        (releases / "Lib").mkdir()
        (releases / "Lib" / "1.0.0.json").write_text("{}", encoding="utf-8")
        entries = [
            entry("listings/Lib.toml", dict(MOD, id="Lib")),
            entry(PACK_WHERE, dict(PACK, mods=[{"id": name, "version": version} for name, version in pins])),
        ]
        return check_index.check_members(entries, [PACK_WHERE], set(), releases)


def index_notes():
    entries = [entry(WHERE, MOD), entry("listings/Lib.toml", dict(MOD, id="Lib", abstract="x" * 300))]
    return check_index.notes(entries, ["listings/Lib.toml"])


def game_max_notes():
    document = changed(MOD, "compatibility.game_max", "2026.10.13.5602")
    bounds = check_index.bounded([entry(WHERE, document)], [WHERE])
    return check_index.game_max_notes(bounds, ["2026.10.10.5554", "2026.10.13.5602"])


def image_checks(document):
    errors, notes = [], []
    check_images.check_document(WHERE, document, errors, notes)
    return errors + notes


def references(description, record_id):
    errors, notes = [], []
    document = {"description": description, "images": {"description": [dict(IMAGE, id=record_id)]}}
    check_image_references.check_document(WHERE, document, errors, notes)
    return errors + notes


def fetched(url, answer, record=IMAGE, role="icon"):
    """The lines of the image fetch when the host of `url` gives `answer`."""
    network = Network({urllib.parse.urlsplit(url).hostname: [PUBLIC]}, {url: answer})
    record = dict(record, url=url)
    if role == "icon":
        document = {"images": {"icon": record}}
    else:
        document = {"images": {"description": [dict(record, id="shot")]}}
    found = check_images.inspect_document(
        WHERE, document, None, verify=lambda record, role: images.verify(record, role, network.fetch)
    )
    return found.errors + found.unchecked


class Authority:
    key = "github:me/mymod"

    def __init__(self, offered=(), error=None, download=None):
        self.offered, self.error, self._download = list(offered), error, download

    def releases(self):
        if self.error:
            raise self.error
        return self.offered, None

    def download(self, release):
        return self._download(release)


def prefixed(prefix, skipped=2, offered=()):
    """A GitHub host with a tag_prefix, which leaves out `skipped` releases."""
    authority = Authority(offered)
    authority.key, authority.tag_prefix, authority.skipped = f"github:me/mymod#{prefix}", prefix, skipped
    return authority


class HostError(Exception):
    pass


NO_STAMPER = SimpleNamespace(StampError=type("StampError", (Exception,), {}))


def inspected(document, authority, stamp_release=NO_STAMPER, game_versions=(), host_error=HostError):
    """The release lines of `document`, with the path in front as validate.py writes them."""
    fake = SimpleNamespace(build=lambda *_: (authority, None), HostError=host_error)
    outcome = check_release.inspect(document, stamp_release, fake, game_versions, None)
    return [f"{WHERE}: {message}" for message in outcome.messages]


def zipped(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as handle:
        for name, text in files.items():
            handle.writestr(name, text)
    return data.getvalue()


def stamped(files=GOOD, document=MOD, data=None, download=None, release=None):
    """The release lines when the latest release holds `files`, through the real stamper."""
    stamp_release, hosts = stamper()
    game_versions = check_release.load_game_versions(releases_root())
    release = release or SimpleNamespace(
        version="1.2.0", tag="v1.2.0", release_date=FACTS["release_date"], facts=lambda: dict(FACTS)
    )
    archive = zipped(files) if data is None else data
    authority = Authority([release], download=download or (lambda _: (archive, "application/zip")))
    return inspected(document, authority, stamp_release, game_versions, hosts.HostError)


def offering(*names):
    """A download of a release that offers the archives `names` and no direct link."""
    def download(release):
        _, hosts = stamper()
        return hosts.download(None, SimpleNamespace(url=None, candidates=names, size=None))
    return download


class Gone:
    """A host that answers HTTP 404 to everything."""

    def get(self, url, **_):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    archive = get


class Refused(Gone):
    """A host that answers HTTP 403 with no rate limit, as SpaceDock does for a hidden mod."""

    def get(self, url, **_):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    archive = get


def hosted(releases, http=None):
    """The release lines of a listing whose host has nothing under `releases`."""
    stamp_release, hosts = stamper()
    outcome = check_release.inspect(
        changed(MOD, "releases", releases), stamp_release, hosts, [], http or Gone()
    )
    return [f"{WHERE}: {message}" for message in outcome.messages]


def unresolved(addresses=None):
    """The image lines when the host name of the url is not found, or has no address."""
    if addresses is None:
        def fetch(url, cap):
            error = socket.gaierror(11001, "getaddrinfo failed")
            with mock.patch.object(images.socket, "getaddrinfo", side_effect=error):
                return images.fetch(url, cap)
    else:
        fetch = Network({"example.invalid": addresses}, {}).fetch
    found = check_images.inspect_document(
        WHERE, {"images": {"icon": IMAGE}}, None, verify=lambda record, role: images.verify(record, role, fetch)
    )
    return found.unchecked


class SpaceDock:
    def __init__(self, mod):
        self.mod = mod

    def spacedock_mod(self, mod_id):
        return self.mod


def spacedock_reason(mod):
    listing = {"id": "MyMod", "releases": {"spacedock": 4256}}
    return ownership.verify(listing, "me", 1, SpaceDock(mod)).reason


def passing(name):
    return lambda *args, **kwargs: validate.Check(name, validate.PASS)


def not_inspected():
    names = ("run_layout", "run_tags", "run_packs", "run_index", "run_license", "run_status",
             "run_images", "run_edits", "run_release", "run_image_fetch")
    with mock.patch.multiple(validate, **{name: passing(name) for name in names}), mock.patch.object(
        validate, "run_schema", lambda: validate.Check("schema", validate.REJECT, ["bad"])
    ), mock.patch.object(validate.check_index, "load_documents", lambda *a, **k: ([], [])):
        checks = validate.run_checks(validate.check_scope.changes([WHERE]))
    return [note for check in checks for note in check.notes]


def unreadable_pins():
    with mock.patch.object(validate.check_index, "check_members", side_effect=OSError("gone")):
        return validate.run_members([], [PACK_WHERE]).messages


def missing(load):
    with tempfile.TemporaryDirectory() as folder:
        try:
            load(Path(folder))
        except check_release.Unavailable as error:
            return str(error)
    raise AssertionError("an empty folder loaded")


def edit_note():
    rules = check_edits.Rules(max, lambda bound, now: False)
    base = changed(MOD, "compatibility.game_min", "2026.8")
    return check_edits.notes_for(WHERE, base, MOD, {"1.0.0": {}, "1.1.0": {}}, rules)


def license_errors(expression):
    errors = []
    check_license.check_document(WHERE, {"license": expression}, errors)
    return errors


TRANSIENT = "This is a problem on the host or in the bot"
RECORD_AGAIN = "make its record again with [the listing page]"

# Each case is (a phrase of the explanation, whether the fix is outside the
# pull request, how the real code writes the message).
CASES = [
    # The rules from before, through the code paths of today.
    ("renaming that folder to `MyMod` is enough", True, lambda: one(stamped({"MyMod-1.2.0/mod.toml": ""}))),
    ("Only the casing differs", True, lambda: one(stamped({"mymod/mod.toml": ""}))),
    ("has no such folder", True, lambda: one(stamped({"mod.toml": "", "MyMod.dll": ""}))),
    ("has no zip that the index can download", True, lambda: one(stamped(download=offering()))),
    ("does not guess which one", True, lambda: one(stamped(download=offering("a.zip", "b.zip")))),
    ("The tag `shiny` can stay", False, lambda: one(
        check_tags.check_document(WHERE, {"type": "mod", "tags": ["shiny"]}, {"mod": ["parts"]}),
        "shiny")),
    ("Add at least one tag", False, lambda: one(
        check_tags.check_document(WHERE, {"type": "mod", "tags": ["shiny"]}, {"mod": ["parts"]}),
        "no curated tag")),
    ("Add the topic", True, lambda: ownership.verify(
        MOD, "me", 1, SimpleNamespace(
            repository=lambda name: {"full_name": name, "fork": False, "owner": {"id": 2}},
            topics=lambda name: [], file=lambda name, path: None)).reason),
    # Lines about the run itself.
    (TRANSIENT, True, lambda: one(fetched(IMAGE["url"], TimeoutError("the time ran out")))),
    (TRANSIENT, True, lambda: one(fetched(IMAGE["url"], Response(503)))),
    (TRANSIENT, True, lambda: one(fetched(IMAGE["url"], Response(429)))),
    (TRANSIENT, True, lambda: one(
        inspected(MOD, Authority(error=HostError("the releases answered HTTP 502"))))),
    (TRANSIENT, True, lambda: one(check_images.inspect_document(
        WHERE, {"images": {"icon": IMAGE}}, None, verify=mock.Mock(side_effect=KeyError("x"))).unchecked)),
    (TRANSIENT, True, lambda: missing(check_release.load_stamper)),
    (TRANSIENT, True, lambda: missing(check_release.load_game_versions)),
    (TRANSIENT, True, lambda: one(unreadable_pins())),
    ("Check the spelling of the address", False, lambda: one(unresolved())),
    ("Check the spelling of the address", False, lambda: one(unresolved([]))),
    ("This is not a pass", False, lambda: one(not_inspected())),
    # The release on GitHub or SpaceDock.
    ("Publish a release whose tag is the version", True, lambda: one(inspected(
        MOD, Authority([SimpleNamespace(version=None, release_date="2026-10-01", tag="beta")])))),
    ("This error is in `MyMod/mod.toml` inside the zip", True, lambda: one(
        stamped({"MyMod/mod.toml": "name = x\n"}))),
    ("save the file as UTF-8 when the message names a byte", True, lambda: one(
        stamped({"MyMod/mod.toml": b'name = "M\xe4x"\n'}))),
    ("Pack the mod folder as a zip again", True, lambda: one(stamped(data=b"Rar!\x1a\x07\x00"))),
    ("Remove target and path from `[install]`", False, lambda: one(
        schema("install", {"target": "game-root"}))),
    ("Remove target and path from `[install]`", False, lambda: one(schema("install", {"target": "mods"}))),
    ("Remove target and path from `[install]`", False, lambda: one(schema("install", {"path": "x"}))),
    ("Remove target and path from `[install]`", False, lambda: one(
        stamped(document=changed(MOD, "install", {"target": "mods"})))),
    ("Most mods need no install.root", False, lambda: one(
        stamped(document=changed(MOD, "install", {"root": "Nope"})))),
    ("no game version came out in that month", False, lambda: one(
        stamped(document=changed(MOD, "compatibility.game_min", "2020.1")))),
    ("Check releases.github in the listing", False, lambda: one(hosted({"github": "me/MyMod"}))),
    ("releases.spacedock is the number", False, lambda: one(hosted({"spacedock": 1234}))),
    ("releases.spacedock is the number", False, lambda: spacedock_reason(None)),
    ("a tag alone or a draft release does not count", False, lambda: one(inspected(MOD, Authority()))),
    ("Compare `mymod-v` with the tags of the releases on GitHub", False, lambda: one(
        inspected(MOD, prefixed("mymod-v")))),
    ("Check that `tag_prefix` under `[releases]` ends where the version starts", False, lambda: one(
        inspected(MOD, prefixed("mymod", skipped=0, offered=[
            SimpleNamespace(version=None, release_date="2026-10-01", tag="mymod-v1.2.3")])))),
    ("`MyMod-1.2.0.zip`", True, lambda: one(stamped(
        download=offering(), release=SimpleNamespace(
            version="1.2.0", tag="mymod-v1.2.0", tag_prefix="mymod-", release_date=FACTS["release_date"],
            facts=lambda: dict(FACTS))))),
    ("each release needs its own pull request", False, lambda: one(
        inspected(changed(MOD, "releases", DELETE), Authority()))),
    # The images of a listing.
    ("short-lived download link", False, lambda: one(fetched(SIGNED, Response(403)))),
    ("Open the address in a private browser window", False, lambda: one(
        fetched(IMAGE["url"], Response(404)))),
    ("refused the download (HTTP `403`)", False, lambda: one(fetched(IMAGE["url"], Response(403)))),
    ("refused the download (HTTP `401`)", False, lambda: one(fetched(IMAGE["url"], Response(401)))),
    ("which the Raw button on GitHub opens", False, lambda: one(
        fetched(IMAGE["url"], Response(200, b"<!DOCTYPE html><html></html>")))),
    ("An icon needs a shorter side", False, lambda: one(schema("images", {"icon": dict(IMAGE, width=100)}))),
    ("An icon needs a shorter side", False, lambda: one(
        image_checks({"images": {"icon": dict(IMAGE, width=1920, height=1080)}}))),
    ("An icon needs a shorter side", False, lambda: one(fetched(IMAGE["url"], Response(200, png(1920, 1080))))),
    ("The image file is too large", False, lambda: one(schema("images", {"icon": dict(IMAGE, size=300000)}))),
    ("The image file is too large", False, lambda: one(
        schema("images", {"description": [dict(IMAGE, id="shot", size=2000000)]}))),
    ("The image file is too large", False, lambda: one(
        fetched(IMAGE["url"], Response(200, headers={"Content-Length": "300000"})))),
    ("The image file is too large", False, lambda: one(
        fetched(IMAGE["url"], Response(200, b"x" * 300000)))),
    ("is not the file that its record describes", False, lambda: one(fetched(
        IMAGE["url"], Response(200, png(900, 500)), dict(IMAGE, width=900, height=500), "description"))),
    ("Clients show only the square in the center of the icon", False, lambda: one(
        image_checks({"images": {"icon": dict(IMAGE, width=1000, height=800)}}))),
    ("`![short text](ksa-image:unused)`", False, lambda: one(references("No image.", "unused"))),
    ('has `id = "missing"`', False, lambda: one(references("![a](ksa-image:missing)", "shot"), "missing")),
    # The listing file, from the TOML through the layout to the schema.
    ("sets a key or a section twice", False, lambda: one(layout({"listings/Dup.toml": 'id = "Dup"\nid = "Dup"\n'}))),
    ("sets a key or a section twice", False, lambda: one(
        layout({"listings/Twice.toml": 'id = "Twice"\n[links]\na = "b"\n[links]\nc = "d"\n'}))),
    ("text needs straight double quotes", False, lambda: one(
        layout({"listings/Bad.toml": 'id = "Bad"\nname = My Mod\n'}))),
    ("text needs straight double quotes", False, lambda: one(
        layout({"listings/Bom.toml": b'\xef\xbb\xbfid = "Bom"\n'}))),
    ("Open a thread in [Mod Releases]", False, lambda: one(schema("links.forums", DELETE))),
    ("Open a thread in [Mod Releases]", False, lambda: one(schema("links", DELETE))),
    ("Open a thread in [Mod Releases]", False, lambda: one(
        schema("links.forums", "https://forums.ahwoo.com/members/me.5/"))),
    ("Add a `[compatibility]` section with game_min", False, lambda: one(schema("compatibility", DELETE))),
    ("Add a `[compatibility]` section with game_min", False, lambda: one(schema("compatibility", {}))),
    ("The file has no `abstract`", False, lambda: one(schema("abstract", DELETE))),
    ("rename the file to `Other.toml`, or change id to `MyMod`", False, lambda: one(
        layout({WHERE: 'id = "Other"\ntype = "mod"\n'}))),
    ("named after `name` in its meta.toml, not after the id", False, lambda: one(
        layout({"vehicles/Rover.toml": 'id = "ExampleRover"\ntype = "vehicle"\n'}))),
    ("rename the file to `Base.toml`, or change id to `OldBase`", False, lambda: one(
        layout({"saves/OldBase.toml": 'id = "Base"\ntype = "save"\n'}))),
    ("next to it, with that version inside", False, lambda: one(
        layout({"packs/p/1.0.0.toml": 'id = "p"\ntype = "modpack"\nversion = "1.0.1"\n'}), "version")),
    ("you do not need a new one", False, lambda: one(edited_pack(), "immutable")),
    ("A leading v, a version with three numbers", False, lambda: one(
        schema("compatibility.game_min", "2026.7.1"))),
    ("A leading v, a version with three numbers", False, lambda: one(
        schema("compatibility.game_max", "v2026.10.10.5554"))),
    ("Change it to `me/MyMod`, without", False, lambda: one(
        schema("releases.github", "https://github.com/me/MyMod"))),
    ("Change it to `me/My.Mod`, without", False, lambda: one(
        schema("releases.github", "https://github.com/me/My.Mod.git"))),
    ("Change it to `elevatorctln/KSA-Public-Telemetry`, without", False, lambda: one(
        schema("releases.github", "https://github.com/elevatorctln/KSA-Public-Telemetry/"))),
    ("Nothing else goes there", False, lambda: one(
        schema("releases.github", "https://github.com/me/MyMod/tree/main"))),
    ("Nothing else goes there", False, lambda: one(schema("releases.github", "me"))),
    ("is a full web address", False, lambda: one(schema("links.repository", "github.com/me/MyMod"))),
    ("is a full web address", False, lambda: one(schema("links.abstract", "One sentence about it."))),
    ("is a full web address", False, lambda: one(schema("links.abstract", "It's a mod."))),
    ("is a full web address", False, lambda: one(schema("links.authors", ["Me"]))),
    ("is a full web address", False, lambda: one(schema("links.forums", 783))),
    ("is also the name of its folder in the zip", False, lambda: one(schema("id", "My Mod"))),
    ("is also the name of its folder in the zip", False, lambda: one(
        schema("dependencies", [{"id": "My Dep", "kind": "required"}]))),
    ("`authors` is a list in square brackets", False, lambda: one(schema("authors", "Me"))),
    ("`dependencies` is a list of entries", False, lambda: one(
        schema("dependencies", {"id": "Lib", "kind": "required"}))),
    ("`images.description` is a list of entries", False, lambda: one(
        schema("images", {"description": dict(IMAGE, id="shot")}))),
    ("`mods` is a list of entries", False, lambda: one(
        schema("mods", {"id": "Lib", "version": "1.0.0"}, PACK))),
    ("`releases.spacedock` is a whole number", False, lambda: one(schema("releases", {"spacedock": "123"}))),
    ("`name` is text in double quotes", False, lambda: one(schema("name", 5))),
    ("A listing of a mod has no `version`", False, lambda: one(schema("version", "1.0.0"))),
    ("The format has no key `'homepage'`", False, lambda: one(schema("homepage", "https://example.com"))),
    ("names where the releases of the mod are", False, lambda: one(schema("releases", {}))),
    ("names where the releases of the mod are", False, lambda: one(
        schema("releases", {"github": "me/MyMod", "spacedock": 1}))),
    ("names where the releases of the mod are", False, lambda: one(
        schema("releases", {"github": "me/MyMod", "authority": "spacedock"}))),
    ("so it needs `github = \"owner/repository\"` next to it", False, lambda: one(
        schema("releases", {"spacedock": 1, "tag_prefix": "mymod-"}))),
    ("entry needs a kind", False, lambda: one(schema("dependencies", [{"id": "a"}]))),
    ("An image record needs url, sha256", False, lambda: one(
        schema("images", {"icon": {"url": IMAGE["url"]}}))),
    ("never with a comma", False, lambda: one(schema("license", "MIT, Apache"))),
    ("never with a comma", False, lambda: one(license_errors("MIT, Apache"))),
    ("never with a comma", False, lambda: one(license_errors("CC-BY-SA"))),
    ("never with a comma", False, lambda: one(license_errors("All rights reserved"))),
    ("never with a comma", False, lambda: one(license_errors("MIT Apache-2.0"))),
    ("never with a comma", False, lambda: one(license_errors("GPL"))),
    # The listing against the rest of the index.
    ("This file and `listings/MyMod.toml` have the same id", False, lambda: one(check_index.check(
        [entry(WHERE, MOD), entry("listings/mymod.toml", dict(MOD, id="mymod"))]), "already held")),
    # The new file can sort first, so the line can name it as the holder.
    ("keep the file that is already in the index", False, lambda: one(check_index.check(
        [entry("listings/AMod.toml", dict(MOD, id="AMod")), entry("listings/amod.toml", dict(MOD, id="amod"))]),
        "already held")),
    ("or the folder of a pack, to match", False, lambda: one(check_index.check(
        [entry("listings/Lib.toml", dict(MOD, id="Lib")), entry("packs/lib/1.0.0.toml", dict(PACK, id="lib"))]),
        "already held")),
    ("goes into `[loader]`, not into", False, lambda: one(check_index.check([
        entry("listings/StarMap.toml", dict(MOD, id="StarMap", type="mod-loader")),
        entry(WHERE, dict(MOD, dependencies=[{"id": "StarMap", "kind": "required"}])),
    ]), "a dependency has to be a mod")),
    ("spelled exactly as the name of its file in listings", False, lambda: one(check_index.check([
        entry("listings/StarMap.toml", dict(MOD, id="StarMap", type="mod-loader")),
        entry(WHERE, dict(MOD, dependencies=[{"id": "starmap", "kind": "required"}])),
    ]), "a dependency has to be a mod")),
    ("Check the spelling of `Lib2`", False, lambda: one(pack_members(("Lib2", "1.0.0")), "Lib2")),
    ("The index has no release `9.9.9` of `Lib`", False, lambda: one(pack_members(("Lib", "9.9.9")), "9.9.9")),
    ("Mods of one family can share a forum thread", False, lambda: one(index_notes(), "forums")),
    ("of at most 280 characters", False, lambda: one(index_notes(), "abstract")),
    ("Keep it only when the content is known to break", False, lambda: one(game_max_notes())),
    ("copies this change into release `1.1.0`", False, lambda: one(edit_note())),
    # The lines of the reason why ownership is not verified.
    ("Edit SpaceDock mod `4256` and set its source code link", True, lambda: spacedock_reason(KSA_MOD)),
    ("must be the address of a GitHub repository", True, lambda: spacedock_reason(
        dict(KSA_MOD, source_code="https://gitlab.com/me/mymod"))),
]


def rule_of(message):
    """The index of the rule that explains `message`, or None."""
    for index, (pattern, _, _) in enumerate(explain.RULES):
        if pattern.search(message):
            return index
    return None


class EveryRule(unittest.TestCase):
    """Each rule explains a message as the code writes it today."""

    def test_each_message_gets_its_explanation(self):
        for phrase, outside, produce in CASES:
            with self.subTest(phrase=phrase):
                message = produce()
                found = explain.explain(message)
                self.assertIsNotNone(found, message)
                self.assertIn(phrase, found.text, message)
                self.assertEqual(found.outside_pull_request, outside, message)

    def test_every_rule_has_a_case(self):
        covered = {rule_of(produce()) for _, _, produce in CASES}
        missed = [
            pattern.pattern for index, (pattern, _, _) in enumerate(explain.RULES) if index not in covered
        ]
        self.assertEqual(missed, [])

    def test_lines_that_need_no_help_get_none(self):
        for message in (
            f"{WHERE}: the latest release 1.2.0 stamps cleanly",
            f"{WHERE}: 3 image(s) match their records",
            one(stamped()),
            # The schema says the rule of a tag in words, which is all the author needs.
            one(schema("tags", ["Parts"])),
            # A missing key names the line to write.
            one(layout({WHERE: 'name = "My Mod"\n'}), "type is missing"),
            one(layout({WHERE: 'name = "My Mod"\n'}), "id is missing"),
        ):
            with self.subTest(message=message):
                self.assertIsNone(explain.explain(message))

    def test_lines_whose_fix_is_not_known_get_none(self):
        # A new record does not help with an animated image or a picture that
        # is too large, because the record tools refuse both. A release host
        # that answers HTTP 4xx can mean a mod that is not published yet.
        big = png(3000, 1000)
        for index, produce in enumerate((
            lambda: fetched(IMAGE["url"], Response(200, png(512, 512, animated=True))),
            lambda: fetched(IMAGE["url"], Response(200, big), dict(IMAGE, width=3000, height=1000), "description"),
            lambda: hosted({"spacedock": 4256}, Refused()),
            lambda: hosted({"github": "me/MyMod"}, Refused()),
        )):
            with self.subTest(index=index):
                message = one(produce())
                self.assertIsNone(explain.explain(message), message)

    def test_a_record_that_differs_still_gets_its_text(self):
        message = (
            f"{WHERE}: images.description[0]: width is 2034 and the bytes show 2047; "
            "size is 566322 and the bytes show 445446"
        )
        self.assertIn("is not the file that its record describes", explain.explain(message).text)

    def test_a_group_with_safe_characters_is_not_put_in_a_code_span(self):
        found = explain.explain(one(references("No image.", "unused")))
        self.assertIn("`![short text](ksa-image:unused)`", found.text)
        self.assertNotIn("``", found.text)


class Texts(unittest.TestCase):
    """What every text has to be, so that a GitHub comment shows it as written."""

    def test_every_text(self):
        for pattern, template, outside in explain.RULES:
            with self.subTest(pattern=pattern.pattern):
                fields = {field for _, field, _, _ in string.Formatter().parse(template) if field}
                derived = {"assets"} if {"id", "tag"} <= set(pattern.groupindex) else set()
                if "login" in pattern.groupindex:
                    derived.add("topic")
                self.assertLessEqual(fields, set(pattern.groupindex) | derived)
                text = template.format(**{field: "`x`" for field in fields})
                self.assertTrue(text.isascii())
                # GitHub drops an unknown tag such as <name> from a comment.
                plain = re.sub(r"\]\([^)]*\)", "]", re.sub(r"`[^`]*`", "", text))
                self.assertNotRegex(plain, "[<>]")
                self.assertLessEqual(len(re.findall(r"[.!?](?:\s|$)", plain)), 5)
                self.assertIsInstance(outside, bool)


class Constants(unittest.TestCase):
    """The numbers and links in the texts are the ones the checks use."""

    def test_the_image_limits(self):
        icon, description = images.LIMITS[images.ICON], images.LIMITS[images.DESCRIPTION]
        pixels = explain.explain(one(schema("images", {"icon": dict(IMAGE, width=100)}))).text
        self.assertIn(f"{icon.low} to {icon.high} pixels", pixels)
        self.assertEqual(icon.ratio, 2)
        self.assertIn("at most twice the shorter side", pixels)
        size = explain.explain(one(schema("images", {"icon": dict(IMAGE, size=300000)}))).text
        self.assertIn(f"{icon.cap // 1024} KiB ({icon.cap} bytes)", size)
        self.assertIn(f"{description.cap // 1024 // 1024} MiB ({description.cap} bytes)", size)

    def test_the_abstract_limit(self):
        text = explain.explain(one(index_notes(), "abstract")).text
        self.assertIn(f"at most {check_index.ABSTRACT_LIMIT} characters", text)

    def test_the_links(self):
        root = Path(__file__).resolve().parent.parent
        self.assertEqual(explain.SPDX, check_license.SPDX_LIST)
        self.assertIn(explain.PAGE, (root / "README.md").read_text(encoding="utf-8"))
        self.assertTrue(explain.GUIDE.endswith("/CONTRIBUTING.md"))
        self.assertTrue((root / "CONTRIBUTING.md").is_file())
        self.assertTrue((Path(__file__).parent / "image_record.py").is_file())

    def test_explain_needs_no_installed_package(self):
        # decide.py imports explain on a runner with no pip install.
        code = (
            f"import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); import explain; "
            "print(sorted(set(sys.modules) & {'jsonschema', 'license_expression', 'markdown_it'}))"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "[]")


def comment(checks, result=None):
    verdict = {
        "schema_version": validate.VERDICT_SCHEMA_VERSION,
        "verdict": validate.worst([check["outcome"] for check in checks] or [validate.PASS]),
        "auto_merge_candidate": True,
        "pull_request": 5,
        "head_sha": "abc",
        "documents": [WHERE],
        "scope_reason": "",
        "checks": checks,
    }
    verified = ownership.Result(ownership.VERIFIED, "", "topic")
    return decide.decide(verdict, True, result or verified).comment


def rejected(name, errors):
    return {"name": name, "outcome": "reject", "errors": errors, "notes": [], "summary": []}


class InTheComment(unittest.TestCase):
    def test_one_cause_is_explained_once(self):
        errors = schema("images", {"icon": {"url": IMAGE["url"]}})
        self.assertEqual(len(errors), 4)
        text = comment([rejected("schema", errors)])
        self.assertEqual(text.count("An image record needs url, sha256"), 1)
        for error in errors:
            self.assertIn(error, text)

    def test_a_toml_error_names_the_file_as_the_layout_does(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "listings").mkdir()
            (root / "packs").mkdir()
            path = root / "listings" / "Bad.toml"
            path.write_text('id = "Bad"\nname = My Mod\n', encoding="utf-8")
            schema_errors = []
            with mock.patch.object(check_schema, "ROOT", root):
                check_schema.load(path, schema_errors)
            layout_errors = check_layout.check(root / "listings", root / "packs")
        self.assertEqual(schema_errors, layout_errors)
        self.assertTrue(schema_errors[0].startswith("listings/Bad.toml: not valid TOML, "))
        text = comment([rejected("layout", layout_errors), rejected("schema", schema_errors)])
        self.assertEqual(text.count("text needs straight double quotes"), 1)
        # The two checks report the same line, so the comment shows it once and names both.
        self.assertEqual(text.count(schema_errors[0]), 1)
        self.assertIn(f"- `layout`, `schema`: {schema_errors[0]}", text)
        self.assertNotIn(root.as_posix(), text)
        self.assertNotIn(str(root), text)

    def test_a_toml_error_comes_once_with_the_index_check_too(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "listings").mkdir()
            (root / "packs").mkdir()
            (root / "listings" / "Bad.toml").write_text('id = "Bad"\nname = My Mod\n', encoding="utf-8")
            schema_errors = []
            with mock.patch.object(check_schema, "ROOT", root):
                check_schema.load(root / "listings" / "Bad.toml", schema_errors)
            layout_errors = check_layout.check(root / "listings", root / "packs")
            entries, skipped = check_index.load_documents(root / "listings", root / "packs")
        self.assertEqual(skipped, ["listings/Bad.toml"])
        index = validate.run_index(entries, skipped).as_dict()
        # The skipped line stays in the job summary, and the comment leaves it out.
        self.assertEqual(index["summary"], ["not read, they do not parse: listings/Bad.toml"])
        text = comment([rejected("layout", layout_errors), rejected("schema", schema_errors), index])
        self.assertEqual(text.count("listings/Bad.toml"), 1)
        self.assertNotIn("do not parse", text)

    def test_a_toml_error_outside_the_repository_keeps_its_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Bad.toml"
            path.write_text("name = My Mod\n", encoding="utf-8")
            errors = []
            check_schema.load(path, errors)
        self.assertTrue(errors[0].startswith(f"{path}: not valid TOML, "))

    def test_an_install_target_is_fixed_in_the_pull_request(self):
        errors = stamped(document=changed(MOD, "install", {"target": "mods"}))
        text = comment([rejected("release", errors)])
        self.assertIn(decide.PUSH_AGAIN, text)
        self.assertNotIn(decide.RELEASE_AGAIN, text)

    def test_mod_toml_in_the_zip_is_fixed_in_the_release(self):
        errors = stamped({"MyMod/mod.toml": "name = x\n"})
        text = comment([rejected("release", errors)])
        self.assertIn(decide.RELEASE_AGAIN, text)
        self.assertNotIn(decide.PUSH_AGAIN, text)

    def test_a_release_without_a_version_is_fixed_on_the_host(self):
        errors = inspected(MOD, Authority([SimpleNamespace(version=None, release_date="2026-10-01", tag="beta")]))
        text = comment([rejected("release", errors)])
        self.assertIn("Publish a release whose tag is the version", text)
        self.assertIn(decide.RELEASE_AGAIN, text)
        self.assertNotIn("zip", decide.RELEASE_AGAIN)

    def test_a_host_name_that_is_not_found_can_be_fixed_by_a_push(self):
        unchecked = {"name": "image_fetch", "outcome": "could-not-evaluate", "errors": [],
                     "unchecked": unresolved(), "notes": [], "summary": []}
        text = comment([unchecked])
        self.assertIn("Check the spelling of the address", text)
        self.assertIn(decide.FIX_OR_RUN_AGAIN, text)
        self.assertNotIn(decide.RUN_AGAIN, text)

    def test_a_host_that_did_not_answer_needs_only_a_new_run(self):
        unchecked = {"name": "image_fetch", "outcome": "could-not-evaluate", "errors": [],
                     "unchecked": fetched(IMAGE["url"], Response(503)), "notes": [], "summary": []}
        text = comment([unchecked])
        self.assertIn(decide.RUN_AGAIN, text)

    def test_a_spacedock_mod_without_a_source_code_link_asks_for_the_proof(self):
        result = ownership.verify(
            {"id": "MyMod", "releases": {"spacedock": 4256}}, "me", 1, SpaceDock(KSA_MOD)
        )
        text = comment([], result)
        self.assertIn("Edit SpaceDock mod `4256` and set its source code link", text)
        self.assertIn(decide.PROOF_AGAIN, text)


if __name__ == "__main__":
    unittest.main()
