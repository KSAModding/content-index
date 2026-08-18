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

ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "listings"
PACKS = ROOT / "packs"

LISTING_TYPES = ("mod", "mod-loader")
PACK_TYPE = "modpack"


def toml_files(folder):
    """Every TOML file under `folder`, at any depth, matched case-insensitively.
    """
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() == ".toml"
    )


def load(path, where, errors):
    """Parse a TOML document. Returns a dict, or None once an error is recorded."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as error:
        errors.append(f"{where}: not valid TOML, {error}")
        return None
    except OSError as error:
        errors.append(f"{where}: could not be read, {error}")
        return None


def check_suffix(path, where, errors):
    """Lowercase only: the snapshot builder globs '*.toml', case-sensitively on Linux.

    toml_files matches either case so Foo.TOML is rejected here, not skipped.
    """
    if path.suffix != ".toml":
        errors.append(f"{where}: the file name has to end in '.toml', in lowercase")


def check_listing(path, where, errors):
    document = load(path, where, errors)
    if document is None:
        return

    declared = document.get("type")
    if declared == PACK_TYPE:
        errors.append(f"{where}: type '{PACK_TYPE}' belongs under packs/<id>/<version>.toml")
    elif declared not in LISTING_TYPES:
        errors.append(f"{where}: type '{declared}' is not one of {', '.join(LISTING_TYPES)}")

    identifier = document.get("id")
    if identifier != path.stem:
        errors.append(f"{where}: declares id '{identifier}', the file name says '{path.stem}'")


def check_pack(path, where, errors):
    document = load(path, where, errors)
    if document is None:
        return

    declared = document.get("type")
    if declared in LISTING_TYPES:
        errors.append(f"{where}: type '{declared}' belongs under listings/<id>.toml")
    elif declared != PACK_TYPE:
        errors.append(f"{where}: type '{declared}' is not '{PACK_TYPE}'")

    identifier = document.get("id")
    if identifier != path.parent.name:
        errors.append(f"{where}: declares id '{identifier}', the folder says '{path.parent.name}'")

    version = document.get("version")
    if version != path.stem:
        errors.append(f"{where}: declares version '{version}', the file name says '{path.stem}'")


def check(listings=LISTINGS, packs=PACKS):
    """Every layout rule. Paths are reported relative to the folder holding both."""
    errors = []
    base = listings.parent

    def where(path):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            return path.as_posix()

    for path in toml_files(listings):
        check_suffix(path, where(path), errors)
        if path.parent != listings:
            errors.append(f"{where(path)}: listings/ holds no subfolders, one document per listing")
            continue
        check_listing(path, where(path), errors)

    for path in toml_files(packs):
        check_suffix(path, where(path), errors)
        if path.parent.parent != packs:
            errors.append(f"{where(path)}: a pack version goes at packs/<id>/<version>.toml")
            continue
        check_pack(path, where(path), errors)

    return errors


def counted(listings=LISTINGS, packs=PACKS):
    """How many documents sit at the depth the layout puts them at."""
    at_depth = [
        path
        for folder, depth in ((listings, 1), (packs, 2))
        for path in toml_files(folder)
        if len(path.relative_to(folder).parts) == depth
    ]
    return len(at_depth)


def main():
    errors = check()

    if errors:
        print("\n".join(errors))
        return 1

    print(f"checked {counted()} document(s), all in the right place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
