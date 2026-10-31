#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for hosts.toml and its schema."""

import importlib.util
import json
import os
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_hosts
import check_release
import check_schema

HOST = """[ksamods]
kind = "share"
name = "ksamods.gg"
storage = "ksamods-content/share"
bot = 98765432
api = "https://ksamods.gg/api/share/v1/"
pages = "https://ksamods-content.github.io/share/"
types = ["vehicle", "save"]
max_bytes = { vehicle = 10485760, save = 104857600 }
new_listings_per_day = 5
policy = "https://ksamods.gg/policy"
"""

# Two Ed25519 public keys as base64 of their SubjectPublicKeyInfo. Only their
# form is read here, so they are fixed bytes and not the keys of a signer.
KEY = "MCowBQYDK2VwAyEAAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
OLD_KEY = "MCowBQYDK2VwAyEAICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="
# The identity point, a key of small order that the schema pattern still takes.
IDENTITY_KEY = "MCowBQYDK2VwAyEAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

# The same host without GitHub storage, by RFC 0104.
DATA_HOST = f"""[ksamods]
kind = "share"
name = "ksamods.gg"
data = "https://data.ksamods.gg/share/"
downloads = ["https://files.ksamods.gg/"]
key = "{KEY}"
bot = 98765432
api = "https://ksamods.gg/api/share/v1/"
types = ["vehicle", "save"]
max_bytes = {{ vehicle = 10485760, save = 104857600 }}
new_listings_per_day = 5
policy = "https://ksamods.gg/policy"
"""


def host(replace=None, drop=(), key="ksamods", text=HOST):
    """An example host, with one line replaced or some keys dropped."""
    lines = text.replace("[ksamods]", f"[{key}]").splitlines()
    if replace:
        name = replace.split(" = ")[0]
        lines = [replace if line.startswith(f"{name} = ") else line for line in lines]
    lines = [line for line in lines if line.split(" = ")[0] not in drop]
    return "\n".join(lines) + "\n"


class Load(unittest.TestCase):
    def load(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "hosts.toml"
        path.write_text(text, encoding="utf-8")
        return check_hosts.load(path)

    def assert_refused(self, text, *words):
        tables, errors = self.load(text)
        self.assertEqual(tables, {})
        self.assertTrue(errors)
        for word in words:
            self.assertTrue(any(word in error for error in errors), errors)

    def test_the_example_of_rfc_0094_is_a_valid_host(self):
        tables, errors = self.load(HOST)
        self.assertEqual(errors, [])
        self.assertEqual(list(tables), ["ksamods"])
        self.assertEqual(tables["ksamods"]["types"], ["vehicle", "save"])

    def test_an_empty_file_registers_no_host(self):
        self.assertEqual(self.load("# no host yet\n"), ({}, []))

    def test_no_file_registers_no_host(self):
        self.assertEqual(check_hosts.load(Path(tempfile.gettempdir()) / "no-such" / "hosts.toml"), ({}, []))

    def test_the_file_of_this_repository_is_valid(self):
        _, errors = check_hosts.load()
        self.assertEqual(errors, [])

    def test_a_storage_repository_of_ksamodding_is_refused(self):
        for owner in ("KSAModding", "ksamodding", "KSAMODDING"):
            with self.subTest(owner):
                self.assert_refused(
                    host(replace=f'storage = "{owner}/share"'),
                    "ksamods.storage",
                    "a repository of the KSAModding organization",
                )

    def test_a_reserved_key_is_refused_as_a_table_name(self):
        for key in ("github", "spacedock", "authority", "since"):
            with self.subTest(key):
                self.assert_refused(host(key=key), f"'{key}' is not a host key")

    def test_a_key_of_another_form_is_refused(self):
        for key in ("KSAMods", "k", "share_host", "9lives"):
            with self.subTest(key):
                self.assert_refused(host(key=f'"{key}"'), "is not a host key")

    def test_another_kind_is_refused(self):
        self.assert_refused(host(replace='kind = "mirror"'), "ksamods.kind")

    def test_a_type_without_a_host_is_refused(self):
        self.assert_refused(host(replace='types = ["mod"]'), "ksamods.types[0]")

    def test_a_type_the_host_takes_needs_a_size(self):
        self.assert_refused(
            host(replace="max_bytes = { vehicle = 10485760 }"),
            "ksamods.max_bytes: there is no size for 'save'",
        )

    def test_a_size_is_a_positive_integer(self):
        self.assert_refused(host(replace="max_bytes = { vehicle = 0, save = 1 }"), "ksamods.max_bytes.vehicle")

    def test_a_host_with_data_downloads_and_key_is_valid(self):
        tables, errors = self.load(DATA_HOST)
        self.assertEqual(errors, [])
        self.assertEqual(tables["ksamods"]["key"], KEY)
        retired = DATA_HOST.replace("bot = ", f'retired_keys = ["{OLD_KEY}"]\nbot = ')
        self.assertEqual(self.load(retired)[1], [])

    def test_a_host_names_storage_or_data(self):
        words = "ksamods: a host names storage, or data with downloads and key, and not keys of both"
        cases = {
            "neither": host(drop=("storage", "pages")),
            "storage and data": DATA_HOST.replace("bot = ", 'storage = "ksamods-content/share"\nbot = '),
            "storage and key": host().replace("bot = ", f'key = "{KEY}"\nbot = '),
            "pages with data": DATA_HOST.replace("bot = ", 'pages = "https://ksamods-content.github.io/share/"\nbot = '),
            "data without key": host(drop=("key",), text=DATA_HOST),
            "data without downloads": host(drop=("downloads",), text=DATA_HOST),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assert_refused(text, words)

    def test_a_key_is_standard_base64_of_an_ed25519_public_key(self):
        url_safe = "MCowBQYDK2VwAyEA-__7__v_-__7__v_-__7__v_-__7__v_-__7__v_-_8="
        x25519 = "MCowBQYDK2VuAyEAAAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
        for value in (url_safe, x25519, KEY.rstrip("=")):
            with self.subTest(value):
                self.assert_refused(
                    host(replace=f'key = "{value}"', text=DATA_HOST),
                    f"ksamods.key: {value!r} is not an Ed25519 public key as standard base64 of its "
                    "SubjectPublicKeyInfo",
                )

    def test_a_small_order_key_is_refused(self):
        self.assert_refused(
            host(replace=f'key = "{IDENTITY_KEY}"', text=DATA_HOST),
            "ksamods.key: the key is a small-order point, so it protects nothing",
        )
        retired = DATA_HOST.replace("bot = ", f'retired_keys = ["{IDENTITY_KEY}"]\nbot = ')
        self.assert_refused(retired, "ksamods.retired_keys[0]: the key is a small-order point, so it protects nothing")

    def test_a_download_prefix_is_an_https_url(self):
        self.assert_refused(
            host(replace='downloads = ["http://files.ksamods.gg/"]', text=DATA_HOST),
            "ksamods.downloads[0]: 'http://files.ksamods.gg/' is not an https URL that ends with /",
        )

    def test_the_current_key_is_not_retired(self):
        text = DATA_HOST.replace("bot = ", f'retired_keys = ["{OLD_KEY}", "{KEY}"]\nbot = ')
        self.assert_refused(text, "ksamods.retired_keys: the host lists its current key as retired too")

    def test_pages_is_the_github_pages_address_of_storage(self):
        self.assert_refused(
            host(replace='pages = "https://other.github.io/share/"'),
            "ksamods.pages: 'https://other.github.io/share/' is not the GitHub Pages address of "
            "ksamods-content/share, which is https://ksamods-content.github.io/share/",
        )
        tables, errors = self.load(host(replace='pages = "https://KSAMods-Content.github.io/Share/"'))
        self.assertEqual(errors, [])
        site = host(replace='storage = "ksamods-content/ksamods-content.github.io"')
        tables, errors = self.load(site.replace("github.io/share/", "github.io/"))
        self.assertEqual(errors, [])

    def test_pages_is_optional(self):
        self.assertEqual(self.load(host(drop=("pages",)))[1], [])

    def test_a_url_ends_with_a_slash(self):
        self.assert_refused(host(replace='api = "https://ksamods.gg/api"'), "ksamods.api")
        self.assert_refused(host(replace='api = "http://ksamods.gg/api/"'), "ksamods.api")

    def test_an_unknown_key_is_refused(self):
        self.assert_refused(host().replace("bot = ", 'token = "x"\nbot = '), "ksamods")

    def test_a_file_that_does_not_parse(self):
        self.assert_refused("[ksamods\n", "cannot read the share hosts")


TABLES = {"ksamods": tomllib.loads(HOST)["ksamods"]}
SAVES_ONLY = {"ksamods": dict(TABLES["ksamods"], types=["save"])}


def vehicle(**releases):
    return {"id": "ExampleRover", "type": "vehicle", "releases": releases}


class Documents(unittest.TestCase):
    def errors(self, document, tables=TABLES):
        return check_hosts.check_document("vehicles/ExampleRover.toml", document, tables)

    def test_a_vehicle_on_a_registered_host_passes(self):
        self.assertEqual(self.errors(vehicle(ksamods="ExampleRover")), [])

    def test_a_key_hosts_toml_does_not_register_is_refused(self):
        self.assertEqual(
            self.errors(vehicle(otherhost="ExampleRover")),
            [
                "vehicles/ExampleRover.toml: releases.otherhost: 'otherhost' is not a share host "
                "that hosts.toml registers"
            ],
        )

    def test_no_key_is_registered_while_hosts_toml_is_empty(self):
        self.assertIn("is not a share host that hosts.toml registers", self.errors(vehicle(ksamods="ExampleRover"), {})[0])

    def test_a_vehicle_on_a_host_that_takes_only_saves_is_refused(self):
        self.assertEqual(
            self.errors(vehicle(ksamods="ExampleRover"), SAVES_ONLY),
            [
                "vehicles/ExampleRover.toml: releases.ksamods: the share host 'ksamods' takes save, "
                "and this document is a vehicle"
            ],
        )

    def test_a_mod_cannot_name_a_share_host(self):
        document = {"id": "ExampleMod", "type": "mod", "releases": {"ksamods": "ExampleMod"}}
        self.assertIn("this document is a mod", self.errors(document)[0])

    def test_the_value_is_the_id_of_the_listing(self):
        for value in ("OtherRover", "examplerover"):
            with self.subTest(value):
                self.assertEqual(
                    self.errors(vehicle(ksamods=value)),
                    [
                        "vehicles/ExampleRover.toml: releases.ksamods: a share host is named with the "
                        f"id of the listing, 'ExampleRover', and not '{value}'"
                    ],
                )

    def test_a_share_host_and_another_host_need_an_authority(self):
        self.assertIn(
            "releases: the section names several hosts, so it needs an 'authority' key that "
            "names one of github, ksamods",
            self.errors(vehicle(ksamods="ExampleRover", github="a/b"))[0],
        )
        self.assertEqual(self.errors(vehicle(ksamods="ExampleRover", github="a/b", authority="ksamods")), [])

    def test_the_authority_names_a_host_of_the_section(self):
        self.assertEqual(
            self.errors(vehicle(github="a/b", authority="ksamods")),
            ["vehicles/ExampleRover.toml: releases.authority: 'ksamods' is not a host this section names"],
        )

    def test_github_spacedock_and_the_other_keys_are_not_share_hosts(self):
        document = vehicle(github="a/b", spacedock=4, authority="github", since="1.0", tag_prefix="x-")
        self.assertEqual(self.errors(document, {}), [])

    def test_a_document_without_releases_has_nothing_to_check(self):
        self.assertEqual(self.errors({"id": "ExampleRover", "type": "vehicle"}), [])

    def test_every_listing_of_this_repository_still_passes(self):
        tables, errors = check_hosts.load()
        self.assertEqual(errors, [])
        found = []
        for path in check_schema.documents():
            with path.open("rb") as handle:
                document = tomllib.load(handle)
            found += check_hosts.check_document(path.relative_to(check_hosts.ROOT).as_posix(), document, tables)
        self.assertEqual(found, [])

    def test_check_reads_the_documents_and_skips_one_that_does_not_parse(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        hosts = Path(folder.name) / "hosts.toml"
        hosts.write_text(HOST, encoding="utf-8")
        good = Path(folder.name) / "Good.toml"
        good.write_text('id = "Good"\ntype = "vehicle"\n[releases]\nksamods = "Good"\n', encoding="utf-8")
        bad = Path(folder.name) / "Bad.toml"
        bad.write_text('id = "Bad"\ntype = "mod"\n[releases]\nksamods = "Bad"\n', encoding="utf-8")
        broken = Path(folder.name) / "Broken.toml"
        broken.write_text("[releases\n", encoding="utf-8")
        errors = check_hosts.check([good, bad, broken, Path(folder.name) / "Gone.toml"], hosts)
        self.assertEqual(len(errors), 1)
        self.assertIn("this document is a mod", errors[0])

    def test_a_broken_hosts_toml_is_reported_before_any_document(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        hosts = Path(folder.name) / "hosts.toml"
        hosts.write_text(host(replace='kind = "mirror"'), encoding="utf-8")
        errors = check_hosts.check([], hosts)
        self.assertEqual(len(errors), 1)
        self.assertIn("ksamods.kind", errors[0])


class HostKey(unittest.TestCase):
    """The host key form has copies in two schemas here and in the watcher."""

    def test_every_copy_of_the_pattern_is_the_same(self):
        hosts = json.loads(check_hosts.SCHEMA.read_text(encoding="utf-8"))
        authored = json.loads(check_schema.SCHEMA.read_text(encoding="utf-8"))
        pattern = hosts["$defs"]["hostKey"]["pattern"]
        self.assertEqual(authored["$defs"]["hostKey"]["pattern"], pattern)
        self.assertEqual(list(authored["properties"]["releases"]["patternProperties"]), [pattern])
        self.assertEqual(hosts["$defs"]["hostKey"]["title"], authored["$defs"]["hostKey"]["title"])

    def test_the_pattern_is_the_one_of_the_watcher(self):
        root = Path(os.environ.get("CONTENT_INDEX_RELEASES") or check_release.DEFAULT_RELEASES)
        tools = root / "tools" if (root / "tools").is_dir() else root
        if not (tools / "authored.py").is_file():
            self.skipTest("content-index-releases is not checked out next to this repository")
        spec = importlib.util.spec_from_file_location("releases_authored", tools / "authored.py")
        authored = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(authored)
        if not hasattr(authored, "host_key"):
            self.skipTest("the checkout of content-index-releases reads no share host yet")

        pattern = re.compile(json.loads(check_hosts.SCHEMA.read_text(encoding="utf-8"))["$defs"]["hostKey"]["pattern"])
        keys = [
            "ksamods", "ab", "a" * 32, "a" * 33, "a", "share-host", "s3", "9lives", "KSAMods",
            "share_host", "-x", "github", "spacedock", "authority", "since", "tag_prefix",
            "githubs", "sincere", "ksamods\n", "",
        ]
        for key in keys:
            with self.subTest(key):
                self.assertEqual(pattern.search(key) is not None, authored.host_key(key))


if __name__ == "__main__":
    unittest.main()
