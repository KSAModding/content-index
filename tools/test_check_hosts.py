#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for hosts.toml and its schema."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_hosts

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


def host(replace=None, drop=(), key="ksamods"):
    """The example host of RFC 0094, with one line replaced or some keys dropped."""
    lines = HOST.replace("[ksamods]", f"[{key}]").splitlines()
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

    def test_a_host_names_storage_or_data(self):
        words = "ksamods: a host names either storage or data, and not both"
        self.assert_refused(host(drop=("storage", "pages")), words)
        both = host().replace("bot = ", 'data = "https://ksamods.gg/data/"\nbot = ')
        self.assert_refused(both, words)

    def test_a_host_with_data_alone_is_valid_by_the_schema_and_not_read_yet(self):
        text = host(drop=("storage", "pages")).replace("bot = ", 'data = "https://ksamods.gg/data/"\nbot = ')
        self.assert_refused(text, "names data and no storage")

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


if __name__ == "__main__":
    unittest.main()
