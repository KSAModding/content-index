#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The rules that need the whole index rather than one document.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

import check_schema

ROOT = Path(__file__).resolve().parent.parent
LISTINGS = ROOT / "listings"
PACKS = ROOT / "packs"
SCHEMA = ROOT / "schemas" / "authored.schema.json"

PACK_TYPE = "modpack"
LOADER_TYPE = "mod-loader"
MOD_TYPE = "mod"

PINNED_SECTIONS = ("mods", "vehicles", "saves")
MEMBER_SECTION = "mods"

REQUIRED = "required"
CONFLICT = "conflict"

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


def _targets(entries):
    """The holder each id resolves to, keyed casefolded."""
    targets = {}
    for entry in entries:
        targets.setdefault(entry.folded, entry)
    return targets


def check_references(entries):
    """Every reference that resolves to a listed id has to name the right type."""
    targets = _targets(entries)
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
    for section, index, member in _pins(entry):
        found = _resolved(entry, targets, member.get("id"), f"{where}: {section}[{index}]", errors)
        if found == PACK_TYPE:
            errors.append(
                f"{where}: {section}[{index}]: '{member['id']}' is itself a pack, "
                "and a pack does not nest in spec_version 1"
            )


def check_members(entries, documents, delisted, releases):
    """The pins of each changed pack version, against the listings and the stamped releases.

    `releases` is the release folder of the generated repository, and one that
    cannot be read raises OSError or ValueError.
    """
    changed = [entry for entry in entries if entry.where in documents and entry.type == PACK_TYPE]
    if not changed:
        return []
    if not releases.is_dir():
        raise FileNotFoundError(f"there is no release folder at {releases}")

    targets = _targets(entries)
    semver = re.compile(_schema_pattern("semver"))
    errors = []
    for entry in changed:
        pinned = {}
        stamped = []
        for section, index, member in _pins(entry):
            where = f"{entry.where}: {section}[{index}]"
            problem, release = _member(section, member, targets, delisted, releases, semver)
            if problem:
                errors.append(f"{where}: {problem}")
            elif release is not None:
                stamped.append((where, member, release))
            if section == MEMBER_SECTION and all(isinstance(member.get(key), str) for key in ("id", "version")):
                pinned.setdefault(member["id"].casefold(), member)
        for where, member, release in stamped:
            errors.extend(f"{where}: {problem}" for problem in _incomplete(member, release, pinned))
    return errors


def _pins(entry):
    for section in PINNED_SECTIONS:
        pinned = entry.document.get(section)
        if not isinstance(pinned, list):
            continue
        for index, member in enumerate(pinned):
            if isinstance(member, dict):
                yield section, index, member


def _member(section, member, targets, delisted, releases, semver):
    """Why a pin is refused, or else the release it pins when there is one to read."""
    identifier = member.get("id")
    version = member.get("version")
    if not isinstance(identifier, str) or not isinstance(version, str):
        return None, None
    if section != MEMBER_SECTION:
        return f"'{identifier}' cannot be pinned, because no content type for {section} is defined yet", None

    target = targets.get(identifier.casefold())
    if target is None:
        return f"'{identifier}' is not a listed mod, and a pack pins only listed mods", None
    if target.type == PACK_TYPE:
        return None, None  # check_references reports a nested pack.
    if target.type != MOD_TYPE:
        return f"'{identifier}' is listed as a {target.type}, and a pack pins only mods", None
    if target.folded in delisted:
        return f"'{identifier}' is delisted, and a pack pins only listed mods", None

    if not semver.match(version):
        return None, None  # check_schema reports it, and it must never become a path.

    path = releases / target.identifier / f"{version}.json"
    if not path.is_file():
        return f"'{identifier}' has no stamped release {version}", None
    release = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(release, dict) or not isinstance(release.get("dependencies", []), list):
        raise ValueError(f"{path} is not a release file")
    if release.get("yanked") is True:
        return f"'{identifier}' {version} is yanked", None
    return None, release


def _incomplete(member, release, pinned):
    """The dependencies of one pinned release that the other pins do not meet."""
    problems = []
    for dependency in release.get("dependencies", []):
        if not isinstance(dependency, dict):
            continue
        kind = dependency.get("kind")
        if kind == REQUIRED:
            options = dependency.get("any_of", [dependency])
            if not any(_pinned_within(option, pinned) for option in options):
                problems.append(
                    f"{_named(member)} requires {_wanted(options)}, and the pack "
                    f"{_pinned_instead(options, pinned)}"
                )
        elif kind == CONFLICT and _folded(dependency) != member["id"].casefold():
            if _pinned_within(dependency, pinned):
                problems.append(
                    f"{_named(member)} conflicts with {_wanted([dependency])}, and the pack "
                    f"pins {_named(pinned[_folded(dependency)])}"
                )
    return problems


def _folded(dependency):
    identifier = dependency.get("id")
    return identifier.casefold() if isinstance(identifier, str) else None


def _pinned_within(dependency, pinned):
    member = pinned.get(_folded(dependency))
    version = check_schema.semver_key(member.get("version")) if member else None
    low = check_schema.semver_key(dependency.get("min"))
    high = check_schema.semver_key(dependency.get("max"))
    return version is not None and (low is None or low <= version) and (high is None or version <= high)


def _wanted(options):
    described = [f"'{option.get('id')}'{_bounds(option)}" for option in options]
    return described[0] if len(described) == 1 else f"one of {', '.join(described)}"


def _bounds(option):
    low, high = option.get("min"), option.get("max")
    if low and high:
        return f" {low} to {high}"
    if low:
        return f" {low} or newer"
    if high:
        return f" {high} or older"
    return ""


def _pinned_instead(options, pinned):
    found = [_named(pinned[key]) for key in map(_folded, options) if key in pinned]
    if found:
        return f"pins {' and '.join(found)}"
    return "does not pin it" if len(options) == 1 else "pins none of them"


def _named(member):
    return f"'{member['id']}' {member['version']}"


def check(entries):
    """Every whole-index rule, over an already loaded set."""
    return check_collisions(entries) + check_references(entries)


def _schema_pattern(name, schema=SCHEMA):
    return json.loads(schema.read_text(encoding="utf-8"))["$defs"][name]["pattern"]


def thread_pattern(schema=SCHEMA):
    """The schema's rule for links.forums, with the thread id captured."""
    rule = _schema_pattern("forumsUrl", schema)
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
