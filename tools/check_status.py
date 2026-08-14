#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check index-status.toml: its shape, and that every id in it resolves.

A state the builder cannot place fails the build, and a failed build publishes
nothing, so a delisting with a typo in it never reaches a client.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_index
import check_schema

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "index-status.schema.json"
STATUS = ROOT / "index-status.toml"

DELISTED = "delisted"
RETRACTED = "retracted"

PACK_HOLDER = "pack"


def validator(schema=SCHEMA):
    document = json.loads(schema.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def inventory(entries):
    """What the ids in the file may resolve to, keyed casefolded.

    The location decides the holder, exactly as check_layout enforces it.
    """
    listings = set()
    packs = {}
    for entry in entries:
        if entry.holder[0] == PACK_HOLDER:
            versions = packs.setdefault(entry.folded, set())
            version = entry.document.get("version")
            if isinstance(version, str):
                versions.add(version)
        else:
            listings.add(entry.folded)
    return listings, packs


def check_shape(path, document, checker, errors):
    """The schema, plus the one rule it cannot express: an entry named twice."""
    check_schema.check_schema(path, document, checker, errors)

    seen = set()
    entries = document.get("entries")
    if not isinstance(entries, list):
        return

    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str):
            continue
        # A retracted state scopes to one version, so an id may appear once per
        # version plus once whole. A non-string version cannot key that.
        retracted = entry.get("state") == RETRACTED
        version = entry.get("version")
        if retracted and not isinstance(version, str):
            continue
        scope = (identifier.casefold(), version if retracted else None)
        if scope in seen:
            errors.append(f"{path}: entries[{position}]: '{identifier}' already has this state")
        seen.add(scope)


def check_resolves(path, document, listings, packs, errors, notes):
    """Every state has to name something the snapshot can attach it to."""
    entries = document.get("entries")
    if not isinstance(entries, list):
        return

    delisted = {
        entry["id"].casefold()
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry.get("state") == DELISTED
    }

    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str):
            continue
        where = f"{path}: entries[{position}]"
        folded = identifier.casefold()

        if entry.get("state") != RETRACTED:
            if folded not in listings and folded not in packs:
                errors.append(
                    f"{where}: '{identifier}' is neither a listing nor a pack, so the state "
                    f"cannot be placed and the snapshot would refuse to build"
                )
            continue

        versions = packs.get(folded)
        if versions is None:
            errors.append(
                f"{where}: '{identifier}' is not a pack, and only a pack version is retracted. "
                f"A listing's release is yanked in the generated repository instead"
            )
            continue

        version = entry.get("version")
        if isinstance(version, str) and version not in versions:
            errors.append(f"{where}: '{identifier}' has no version {version} to retract")
        elif folded in delisted:
            notes.append(
                f"{where}: '{identifier}' is delisted, so retracting its version {version} "
                f"changes nothing"
            )


def check(entries, path=STATUS, checker=None):
    """Every index-status rule. Returns (errors, notes)."""
    errors = []
    notes = []

    if not path.is_file():
        return errors, notes

    where = _relative(path)
    document = check_schema.load(path, errors)
    if document is None:
        return errors, notes

    check_shape(where, document, checker or validator(), errors)
    listings, packs = inventory(entries)
    check_resolves(where, document, listings, packs, errors, notes)
    return errors, notes


def _relative(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    entries, skipped = check_index.load_documents()
    errors, notes = check(entries)

    if skipped:
        print(
            f"note: {len(skipped)} document(s) do not parse and were not counted as "
            f"listings, so a state naming one reports as unresolved: {', '.join(skipped)}"
        )
    for note in notes:
        print(f"note: {note}")
    if errors:
        print("\n".join(errors))
        return 1

    print("index-status.toml is well formed and every state resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
