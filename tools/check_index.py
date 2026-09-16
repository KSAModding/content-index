#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The rules that need the whole index rather than one document.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "listings"
PACKS = ROOT / "packs"
SCHEMA = ROOT / "schemas" / "authored.schema.json"

PACK_TYPE = "modpack"
LOADER_TYPE = "mod-loader"
MOD_TYPE = "mod"

PINNED_SECTIONS = ("mods", "vehicles", "saves")

THREAD_ID = "[0-9]+"
ABSTRACT_LIMIT = 280


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
    targets = {}
    for entry in entries:
        targets.setdefault(entry.folded, entry)

    errors = []
    for entry in entries:
        _check_successor(entry, targets, entry.where, errors)
        if entry.type == PACK_TYPE:
            _check_pins(entry, targets, entry.where, errors)
        else:
            _check_loader(entry, targets, entry.where, errors)
            _check_dependencies(entry, targets, entry.where, errors)
    return errors


def _resolved(entry, targets, value, where, errors):
    """The listed type of `value`, or None when unlisted or self-referential.

    check_schema reports a self-reference in the words of its own field.
    """
    if not isinstance(value, str):
        return None
    folded = value.casefold()
    if folded == entry.folded:
        return None
    target = targets.get(folded)
    if target is None:
        return None
    if value != target.identifier:
        errors.append(
            f"{where}: '{value}' does not use the canonical id spelling "
            f"'{target.identifier}'"
        )
    return target.type


def _check_successor(entry, targets, where, errors):
    _resolved(
        entry, targets, entry.document.get("superseded_by"), f"{where}: superseded_by", errors
    )


def _check_loader(entry, targets, where, errors):
    loader = entry.document.get("loader")
    if not isinstance(loader, dict):
        return
    found = _resolved(entry, targets, loader.get("id"), f"{where}: loader", errors)
    if found is not None and found != LOADER_TYPE:
        errors.append(
            f"{where}: loader: '{loader['id']}' is listed as a {found}, "
            f"and a loader has to be a {LOADER_TYPE}"
        )


def _check_dependencies(entry, targets, where, errors):
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
                        entry, targets, f"{where}: dependencies[{index}].any_of[{offset}]",
                        member.get("id"), errors,
                    )
            continue
        _check_dependency_id(
            entry, targets, f"{where}: dependencies[{index}]", dependency.get("id"), errors
        )


def _check_dependency_id(entry, targets, where, value, errors):
    found = _resolved(entry, targets, value, where, errors)
    if found is not None and found != MOD_TYPE:
        errors.append(f"{where}: '{value}' is listed as a {found}, and a dependency has to be a {MOD_TYPE}")


def _check_pins(entry, targets, where, errors):
    for section in PINNED_SECTIONS:
        pinned = entry.document.get(section)
        if not isinstance(pinned, list):
            continue
        for index, member in enumerate(pinned):
            if not isinstance(member, dict):
                continue
            found = _resolved(
                entry, targets, member.get("id"), f"{where}: {section}[{index}]", errors
            )
            if found == PACK_TYPE:
                errors.append(
                    f"{where}: {section}[{index}]: '{member['id']}' is itself a pack, "
                    "and a pack does not nest in spec_version 1"
                )


def check(entries):
    """Every whole-index rule, over an already loaded set."""
    return check_collisions(entries) + check_references(entries)


def thread_pattern(schema=SCHEMA):
    """The schema's rule for links.forums, with the thread id captured."""
    rule = json.loads(schema.read_text(encoding="utf-8"))["$defs"]["forumsUrl"]["pattern"]
    if rule.count(THREAD_ID) != 1:
        raise ValueError(f"{_relative(schema, ROOT)}: forumsUrl has no single thread id to capture")
    return re.compile(rule.replace(THREAD_ID, f"({THREAD_ID})"))


def _thread(entry, pattern):
    links = entry.document.get("links")
    forums = links.get("forums") if isinstance(links, dict) else None
    match = pattern.match(forums) if isinstance(forums, str) else None
    return int(match.group(1)) if match else None


def check_forums(entries, documents, pattern=None):
    """A changed document that names a forums thread another holder already names."""
    changed = [entry for entry in entries if entry.where in documents]
    if not changed:
        return []

    pattern = pattern or thread_pattern()
    notes = []
    for entry in changed:
        thread = _thread(entry, pattern)
        if thread is None:
            continue
        others = sorted(
            {
                other.where
                for other in entries
                if other.holder != entry.holder and _thread(other, pattern) == thread
            }
        )
        if others:
            notes.append(
                f"{entry.where}: links.forums: thread {thread} is also the forums thread of "
                f"{', '.join(others)}, so the thread cannot settle an id dispute between them"
            )
    return notes


def check_abstracts(entries, documents):
    """A changed document whose abstract is too long for a list view."""
    notes = []
    for entry in entries:
        abstract = entry.document.get("abstract")
        if entry.where in documents and isinstance(abstract, str) and len(abstract) > ABSTRACT_LIMIT:
            notes.append(
                f"{entry.where}: abstract: {len(abstract)} characters is longer than "
                f"{ABSTRACT_LIMIT}, and an abstract is one or two sentences for list views"
            )
    return notes


def notes(entries, documents):
    """Every note on the changed documents."""
    return check_forums(entries, documents) + check_abstracts(entries, documents)


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
