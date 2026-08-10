#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that every authored document sits where its type says it belongs.

RFC 0033 keeps listings and packs in separate folders, and the id and version a
document declares are the path it lives at. This check enforces that agreement
in both directions. Everything else about a document, the schema and the id
rules, is the validation workflow's job.
"""

import sys
import tomllib
from pathlib import Path

LISTINGS = Path("listings")
PACKS = Path("packs")

LISTING_TYPES = ("mod", "mod-loader")
PACK_TYPE = "modpack"


def load(path, errors):
    """Parse a TOML document. Returns a dict, or None once an error is recorded."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        errors.append(f"{path}: not valid TOML, {error}")
        return None


def check_listing(path, errors):
    document = load(path, errors)
    if document is None:
        return

    declared = document.get("type")
    if declared == PACK_TYPE:
        errors.append(f"{path}: type '{PACK_TYPE}' belongs under packs/<id>/<version>.toml")
    elif declared not in LISTING_TYPES:
        errors.append(f"{path}: type '{declared}' is not one of {', '.join(LISTING_TYPES)}")

    identifier = document.get("id")
    if identifier != path.stem:
        errors.append(f"{path}: declares id '{identifier}', the file name says '{path.stem}'")


def check_pack(path, errors):
    document = load(path, errors)
    if document is None:
        return

    declared = document.get("type")
    if declared in LISTING_TYPES:
        errors.append(f"{path}: type '{declared}' belongs under listings/<id>.toml")
    elif declared != PACK_TYPE:
        errors.append(f"{path}: type '{declared}' is not '{PACK_TYPE}'")

    identifier = document.get("id")
    if identifier != path.parent.name:
        errors.append(f"{path}: declares id '{identifier}', the folder says '{path.parent.name}'")

    version = document.get("version")
    if version != path.stem:
        errors.append(f"{path}: declares version '{version}', the file name says '{path.stem}'")


def main():
    errors = []
    counted = 0

    for path in sorted(LISTINGS.rglob("*.toml")) if LISTINGS.is_dir() else []:
        if path.parent != LISTINGS:
            errors.append(f"{path}: listings/ holds no subfolders, one document per listing")
            continue
        check_listing(path, errors)
        counted += 1

    for path in sorted(PACKS.rglob("*.toml")) if PACKS.is_dir() else []:
        if path.parent.parent != PACKS:
            errors.append(f"{path}: a pack version goes at packs/<id>/<version>.toml")
            continue
        check_pack(path, errors)
        counted += 1

    if errors:
        print("\n".join(errors))
        return 1

    print(f"checked {counted} document(s), all in the right place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
