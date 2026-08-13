#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The rules that need the whole index rather than one document.
"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "listings"
PACKS = ROOT / "packs"

PACK_TYPE = "modpack"
LOADER_TYPE = "mod-loader"
MOD_TYPE = "mod"

PINNED_SECTIONS = ("mods", "vehicles", "saves")


class Entry:
    """One authored document, with the id namespace holder it belongs to."""

    def __init__(self, path, where, holder, identifier, document):
        self.path = path
        self.where = where
        self.holder = holder
        self.identifier = identifier
        self.document = document

    @property
    def folded(self):
        return self.identifier.casefold()

    @property
    def type(self):
        return self.document.get("type")


def _relative(path, base):
    """The path as the repository reads it, or in full when it lies outside."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def load_documents(listings=LISTINGS, packs=PACKS):
    """Every authored document, keyed by the holder that owns its id.

    A holder is one listing file, or one pack folder with every version under
    it. The id comes from the path.
    """
    entries = []
    skipped = []
    base = listings.parent

    for path in _toml_files(listings, depth=1):
        document = _load(path, base, skipped)
        if document is not None:
            entries.append(
                Entry(path, _relative(path, base), ("listing", path.stem), path.stem, document)
            )

    for path in _toml_files(packs, depth=2):
        document = _load(path, base, skipped)
        if document is not None:
            folder = path.parent.name
            entries.append(
                Entry(path, _relative(path, base), ("pack", folder), folder, document)
            )

    return entries, skipped


def _toml_files(folder, depth):
    """The TOML files at exactly `depth` parts below `folder`, matched case-insensitively."""
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and path.suffix.lower() == ".toml"
        and len(path.relative_to(folder).parts) == depth
    )


def _load(path, base, skipped):
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError):
        skipped.append(_relative(path, base))
        return None


def check_collisions(entries):
    """No two holders may own the same id, compared case-insensitively."""
    errors = []
    owners = {}

    for entry in entries:
        first = owners.get(entry.folded)
        if first is None:
            owners[entry.folded] = entry
            continue
        if first.holder == entry.holder:
            continue  # Another version of the same pack.
        errors.append(
            f"{entry.where}: the id '{entry.identifier}' is already held by "
            f"{first.where}, and ids compare case-insensitively"
        )
        # Keep the first holder, so a third document reports against the same one.

    return errors


def check_references(entries):
    """Every reference that resolves to a listed id has to name the right type."""
    types = {}
    for entry in entries:
        types.setdefault(entry.folded, entry.type)

    errors = []
    for entry in entries:
        if entry.type == PACK_TYPE:
            _check_pins(entry, types, entry.where, errors)
        else:
            _check_loader(entry, types, entry.where, errors)
            _check_dependencies(entry, types, entry.where, errors)
    return errors


def _resolved(entry, types, value):
    """The listed type of `value`, or None when unlisted or self-referential.

    check_schema reports a self-reference in the words of its own field.
    """
    if not isinstance(value, str):
        return None
    folded = value.casefold()
    if folded == entry.folded:
        return None
    return types.get(folded)


def _check_loader(entry, types, where, errors):
    loader = entry.document.get("loader")
    if not isinstance(loader, dict):
        return
    found = _resolved(entry, types, loader.get("id"))
    if found is not None and found != LOADER_TYPE:
        errors.append(
            f"{where}: loader: '{loader['id']}' is listed as a {found}, "
            f"and a loader has to be a {LOADER_TYPE}"
        )


def _check_dependencies(entry, types, where, errors):
    entries = entry.document.get("dependencies")
    if not isinstance(entries, list):
        return

    for index, dependency in enumerate(entries):
        if not isinstance(dependency, dict):
            continue
        alternatives = dependency.get("any_of")
        if isinstance(alternatives, list):
            for offset, member in enumerate(alternatives):
                if isinstance(member, dict):
                    _check_dependency_id(
                        entry, types, f"{where}: dependencies[{index}].any_of[{offset}]",
                        member.get("id"), errors,
                    )
            continue
        _check_dependency_id(
            entry, types, f"{where}: dependencies[{index}]", dependency.get("id"), errors
        )


def _check_dependency_id(entry, types, where, value, errors):
    found = _resolved(entry, types, value)
    if found is not None and found != MOD_TYPE:
        errors.append(f"{where}: '{value}' is listed as a {found}, and a dependency has to be a {MOD_TYPE}")


def _check_pins(entry, types, where, errors):
    for section in PINNED_SECTIONS:
        pinned = entry.document.get(section)
        if not isinstance(pinned, list):
            continue
        for index, member in enumerate(pinned):
            if not isinstance(member, dict):
                continue
            found = _resolved(entry, types, member.get("id"))
            if found == PACK_TYPE:
                errors.append(
                    f"{where}: {section}[{index}]: '{member['id']}' is itself a pack, "
                    "and a pack does not nest in spec_version 1"
                )


def check(entries):
    """Every whole-index rule, over an already loaded set."""
    return check_collisions(entries) + check_references(entries)


def main():
    entries, skipped = load_documents()
    errors = check(entries)

    if skipped:
        print(f"note: {len(skipped)} document(s) do not parse and were skipped: {', '.join(skipped)}")
    if errors:
        print("\n".join(errors))
        return 1

    print(f"checked {len(entries)} document(s) against the index, no collisions or wrong references")
    return 0


if __name__ == "__main__":
    sys.exit(main())
