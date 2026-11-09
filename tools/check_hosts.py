#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate hosts.toml, the share hosts the index trusts (RFC 0094), and the
share host keys of the documents a change touches.

The schema in schemas/hosts.schema.json says what a table may contain. This
check runs it, and adds the rules the schema cannot express: every type a host
takes has a size limit, `pages` is the GitHub Pages address of the `storage`
repository, and a host with `data` does not list its current `key` among its
`retired_keys`. A key that is a point of small order is refused, because under
such a key one signature fits every file. No signature is checked here, and a
key is only read as text, so this check needs no crypto package.

Only the documents a change touches are checked against the tables, so a
steward who removes a host does not stop every later pull request. Its
listings no longer verify ownership, and a steward handles them (RFC 0094).
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_schema
import ownership
import signature

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

ROOT = Path(__file__).resolve().parent.parent
HOSTS = ROOT / "hosts.toml"
SCHEMA = ROOT / "schemas" / "hosts.schema.json"


def validator(schema=SCHEMA):
    document = json.loads(schema.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def pages_of(storage):
    """The GitHub Pages address of the repository `storage`, as owner/repo."""
    owner, _, name = storage.partition("/")
    if name.lower() == f"{owner}.github.io".lower():
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{name}/"


def check_table(where, key, table, errors):
    """The rules of one host table that the schema cannot express."""
    types = table.get("types")
    limits = table.get("max_bytes")
    if isinstance(types, list) and isinstance(limits, dict):
        for content_type in types:
            if isinstance(content_type, str) and content_type not in limits:
                errors.append(
                    f"{where}: {key}.max_bytes: there is no size for '{content_type}', "
                    "a type the host takes"
                )

    current = table.get("key")
    retired = table.get("retired_keys")
    if isinstance(current, str) and isinstance(retired, list) and current in retired:
        errors.append(f"{where}: {key}.retired_keys: the host lists its current key as retired too")
    keys = [("key", current)]
    if isinstance(retired, list):
        keys += [(f"retired_keys[{index}]", value) for index, value in enumerate(retired)]
    for name, value in keys:
        if isinstance(value, str) and signature.small_order_key(value):
            errors.append(f"{where}: {key}.{name}: the key is a small-order point, so it protects nothing")

    storage = table.get("storage")
    pages = table.get("pages")
    if isinstance(pages, str) and isinstance(storage, str):
        wanted = pages_of(storage)
        if pages.lower() != wanted.lower():
            errors.append(
                f"{where}: {key}.pages: '{pages}' is not the GitHub Pages address of "
                f"{storage}, which is {wanted}"
            )


def load(path=HOSTS, schema=SCHEMA):
    """The host tables by key, and every error of the file.

    No file registers no host. A file with an error registers none either, so
    nothing verifies through a table that is wrong.
    """
    where = _relative(path)
    if not path.is_file():
        return {}, []
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError) as error:
        return {}, [f"{where}: cannot read the share hosts: {error}"]

    errors = []
    checker = validator(schema)
    for error in sorted(checker.iter_errors(document), key=lambda e: list(map(str, e.absolute_path))):
        deepest = best_match([error]) or error
        place = check_schema.pointer(deepest)
        message = check_schema.explain(deepest)
        if not deepest.absolute_path and isinstance(deepest.instance, str):
            # A table name has no place of its own in the document.
            place = f"[{deepest.instance}]"
        elif deepest.validator == "oneOf":
            message = "a host names storage, or data with downloads and key, and not keys of both"
        errors.append(f"{where}: {place}: {message}")
    for key, table in document.items():
        if isinstance(table, dict):
            check_table(where, key, table, errors)
    return ({} if errors else document), errors


def check_document(where, document, tables):
    """The errors of the share host keys under `[releases]` of one document.

    The schema takes any key of the host key form, so whether it names a host
    that hosts.toml registers, and one that takes this type, is checked here.
    """
    releases = document.get("releases")
    if not isinstance(releases, dict):
        return []

    errors = []
    content_type = document.get("type")
    listing_id = document.get("id")
    shares = ownership.share_keys(releases)
    for key in shares:
        table = tables.get(key)
        if not isinstance(table, dict) or table.get("kind") != ownership.SHARE_KIND:
            errors.append(f"{where}: releases.{key}: '{key}' is not a share host that hosts.toml registers")
            continue
        types = [name for name in table.get("types") or [] if isinstance(name, str)]
        if content_type not in types:
            errors.append(
                f"{where}: releases.{key}: the share host '{key}' takes {', '.join(types) or 'no type'}, "
                f"and this document is a {content_type}"
            )
        if releases[key] != listing_id:
            errors.append(
                f"{where}: releases.{key}: a share host is named with the id of the listing, "
                f"'{listing_id}', and not {releases[key]!r}"
            )

    hosts = [key for key in releases if key not in ownership.NOT_HOSTS]
    authority = releases.get("authority")
    if shares and len(hosts) > 1 and authority is None:
        errors.append(
            f"{where}: releases: the section names several hosts, so it needs an 'authority' "
            f"key that names one of {', '.join(sorted(hosts))}"
        )
    if isinstance(authority, str) and authority not in ownership.FIXED_HOSTS and authority not in hosts:
        errors.append(f"{where}: releases.authority: '{authority}' is not a host this section names")
    return errors


def check(paths=(), hosts_path=HOSTS):
    """Validate hosts.toml, then the share host keys of the given documents.

    A document that does not parse is left to the schema check.
    """
    tables, errors = load(hosts_path)
    if errors:
        return errors

    for path in paths:
        path = Path(path)
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError):
            continue
        errors.extend(check_document(_relative(path), document, tables))
    return errors


def _relative(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="authored documents to check")
    arguments = parser.parse_args(argv)

    tables, _ = load()
    errors = check(arguments.paths)
    if errors:
        print("\n".join(errors))
        return 1

    print(f"hosts.toml is well formed and registers {len(tables)} share host(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
