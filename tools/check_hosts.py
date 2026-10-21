#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate hosts.toml, the share hosts the index trusts (RFC 0094).

The schema in schemas/hosts.schema.json says what a table may contain. This
check runs it, and adds the rules the schema cannot express: every type a host
takes has a size limit, a host names a storage repository, which is all the
watcher and the ownership check read yet, and `pages` is the GitHub Pages
address of that repository.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_schema

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

    storage = table.get("storage")
    if "data" in table and "storage" not in table:
        errors.append(
            f"{where}: {key}: the host names data and no storage, and the watcher and the "
            "ownership check read only a storage repository yet"
        )

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
            message = "a host names either storage or data, and not both"
        errors.append(f"{where}: {place}: {message}")
    for key, table in document.items():
        if isinstance(table, dict):
            check_table(where, key, table, errors)
    return ({} if errors else document), errors


def _relative(path):
    try:
        return Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    tables, errors = load()
    if errors:
        print("\n".join(errors))
        return 1

    print(f"hosts.toml is well formed and registers {len(tables)} share host(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
