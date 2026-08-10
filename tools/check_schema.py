#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate every authored document against the schema.

The schema in schemas/authored.schema.json says what a document may contain.
This check runs it, and adds the rules the schema cannot express: whether a
bound pair is the right way round, whether a timestamp names a real moment,
whether the parentheses in a license expression balance, and whether a document
refers to the same id twice.

Where a document lives and whether its id matches its path is check_layout.py.
Whether an id collides with another listing, whether the archive downloads, and
whether the author controls the release host are the validation workflow's job.
"""

import datetime
import json
import re
import sys
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schemas" / "authored.schema.json"
LISTINGS = ROOT / "listings"
PACKS = ROOT / "packs"

REVISION_BOUND = re.compile(r"^[0-9]{4}\.[0-9]+\.[0-9]+\.([0-9]+)(?![\s\S])")
MONTH_BOUND = re.compile(r"^([0-9]{4})\.([0-9]+)(?![\s\S])")

PINNED_SECTIONS = ("mods", "vehicles", "saves")


def normalise(value):
    """Turn TOML's native date and time values into the strings the schema expects.

    TOML lets released_at be written either quoted or as a native datetime, and
    both are correct TOML. The index accepts both and compares the RFC 3339
    string, so every consumer of the schema that parses TOML has to do the same
    before validating.
    """
    if isinstance(value, dict):
        return {key: normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalise(item) for item in value]
    if isinstance(value, datetime.datetime):
        text = value.isoformat()
        return text[:-6] + "Z" if text.endswith("+00:00") else text
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    return value


def load(path, errors):
    """Parse a TOML document. Returns a dict, or None once an error is recorded."""
    try:
        with path.open("rb") as handle:
            return normalise(tomllib.load(handle))
    except tomllib.TOMLDecodeError as error:
        errors.append(f"{path}: not valid TOML, {error}")
        return None


def pointer(error):
    """Render the location of a schema error the way the document reads."""
    if not error.absolute_path:
        return "the document"
    parts = []
    for step in error.absolute_path:
        parts.append(f"[{step}]" if isinstance(step, int) else f".{step}")
    return "".join(parts).lstrip(".")


def explain(error):
    """Say what a rejection means in words.

    The schema forbids a key with {"not": {}} rather than the boolean false
    schema, because a boolean subschema loses the key name from the error path
    and the report then points at the whole document. A "not" that carries a
    pattern says what it rejects in its title, since the raw message would put
    the pattern itself in front of the author.
    """
    if error.validator != "not":
        return error.message
    if error.validator_value == {}:
        return "this key is not allowed here"
    title = error.validator_value.get("title") if isinstance(error.validator_value, dict) else None
    return f"{error.instance!r} is {title}" if title else error.message


def check_schema(path, document, validator, errors):
    for error in sorted(validator.iter_errors(document), key=lambda e: list(map(str, e.absolute_path))):
        deepest = best_match([error]) or error
        errors.append(f"{path}: {pointer(deepest)}: {explain(deepest)}")


def semver_key(version):
    """Sort key for a release version, per SemVer 2.0.0. None when it does not parse."""
    if not isinstance(version, str):
        return None
    core, _, pre = version.partition("+")[0].partition("-")
    numbers = core.split(".")
    if len(numbers) != 3 or not all(part.isdecimal() for part in numbers):
        return None
    core_key = tuple(int(part) for part in numbers)
    if not pre:
        # A release outranks every pre-release of the same core version.
        return (core_key, (1,))
    identifiers = []
    for part in pre.split("."):
        # A numeric identifier compares numerically and ranks below an alphanumeric one.
        identifiers.append((0, int(part), "") if part.isdecimal() else (1, 0, part))
    return (core_key, (0, tuple(identifiers)))


def check_bounds(path, where, bounds, errors):
    """A max below a min describes no version at all.
    """
    if not isinstance(bounds, dict):
        return
    low, high = semver_key(bounds.get("min")), semver_key(bounds.get("max"))
    if low is not None and high is not None and high < low:
        errors.append(f"{path}: {where}: max '{bounds['max']}' is below min '{bounds['min']}'")


def game_bound_key(bound):
    """Sort key for a game compatibility bound, tagged with what it names.

    A bound naming a revision and a bound naming a whole month are not
    comparable here: resolving a month to its first and last revision needs the
    game release list, which lives in the generated repository. Two bounds of
    the same kind are comparable, because revisions ascend across the shipped
    history, so calendar order is revision order.
    """
    if not isinstance(bound, str):
        return None
    revision = REVISION_BOUND.match(bound)
    if revision:
        return ("revision", int(revision.group(1)))
    month = MONTH_BOUND.match(bound)
    return ("month", (int(month.group(1)), int(month.group(2)))) if month else None


def check_game_bounds(path, compatibility, errors):
    low = game_bound_key(compatibility.get("game_min"))
    high = game_bound_key(compatibility.get("game_max"))
    if low is None or high is None or low[0] != high[0]:
        return
    if high[1] < low[1]:
        errors.append(
            f"{path}: compatibility: game_max '{compatibility['game_max']}' "
            f"is older than game_min '{compatibility['game_min']}'"
        )


def check_timestamp(path, value, errors):
    """The schema checks the shape. Whether the date exists is the calendar's business."""
    if not isinstance(value, str):
        return
    try:
        datetime.datetime.fromisoformat(value)
    except ValueError:
        errors.append(f"{path}: released_at: '{value}' is not a real date and time")


def check_license(path, expression, errors):
    """Balance the parentheses. Which identifiers exist is the SPDX list's business."""
    if not isinstance(expression, str):
        return
    depth = 0
    for character in expression:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        errors.append(f"{path}: license: '{expression}' has unbalanced parentheses")


def check_links(path, links, errors):
    """TOML forbids a duplicate key, but not one that differs only in case."""
    if not isinstance(links, dict):
        return
    seen = {}
    for key in links:
        folded = key.casefold()
        if folded in seen:
            errors.append(f"{path}: links: '{key}' and '{seen[folded]}' are the same key")
        seen[folded] = key


def identifier_of(entry):
    """The id an entry names, folded for comparison. None when it names none."""
    if not isinstance(entry, dict):
        return None
    value = entry.get("id")
    return value.casefold() if isinstance(value, str) else None


def check_loader(path, document, own, errors):
    loader = document.get("loader")
    if not isinstance(loader, dict):
        return
    check_bounds(path, "loader", loader, errors)
    if identifier_of(loader) == own:
        errors.append(f"{path}: loader: a listing cannot be its own loader")


def check_dependencies(path, document, own, errors):
    """A document may name any id once. Naming one twice, or naming itself, is a contradiction."""
    entries = document.get("dependencies")
    if not isinstance(entries, list):
        return

    seen = {}
    for index, dependency in enumerate(entries):
        if not isinstance(dependency, dict):
            continue
        where = f"dependencies[{index}]"
        check_bounds(path, where, dependency, errors)

        alternatives = dependency.get("any_of")
        members = alternatives if isinstance(alternatives, list) else [dependency]
        local = {}
        for offset, member in enumerate(members):
            if alternatives is not None:
                check_bounds(path, f"{where}.any_of[{offset}]", member, errors)
            identifier = identifier_of(member)
            if identifier is None:
                continue
            if identifier == own:
                errors.append(f"{path}: {where}: a listing cannot depend on itself")
            if identifier in local:
                errors.append(f"{path}: {where}: names '{member['id']}' more than once")
            local.setdefault(identifier, member["id"])

        for identifier, written in local.items():
            if identifier in seen:
                errors.append(f"{path}: {where}: '{written}' already has a dependency entry")
            seen.setdefault(identifier, written)


def check_pins(path, document, own, errors):
    """A pack pins each member once, across all three sections: the id namespace is global."""
    pinned = {}
    for section in PINNED_SECTIONS:
        entries = document.get(section)
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            identifier = identifier_of(entry)
            if identifier is None:
                continue
            where = f"{section}[{index}]"
            if identifier == own:
                errors.append(f"{path}: {where}: a pack cannot pin itself")
            elif identifier in pinned:
                errors.append(f"{path}: {where}: '{entry['id']}' is pinned by {pinned[identifier]}")
            pinned.setdefault(identifier, where)


def check_parsed(path, document, validator, errors):
    """Run every check over one already parsed document."""
    check_schema(path, document, validator, errors)

    # The rules below read fields by name. They tolerate a wrong type rather
    # than raising, because the schema has already reported it and a traceback
    # would throw away every other error in the run.
    own = document.get("id")
    own = own.casefold() if isinstance(own, str) else None

    check_links(path, document.get("links"), errors)

    compatibility = document.get("compatibility")
    if isinstance(compatibility, dict):
        check_game_bounds(path, compatibility, errors)

    check_timestamp(path, document.get("released_at"), errors)
    check_license(path, document.get("license"), errors)

    successor = document.get("superseded_by")
    if isinstance(successor, str) and successor.casefold() == own:
        errors.append(f"{path}: superseded_by: a listing cannot supersede itself")

    check_loader(path, document, own, errors)
    check_dependencies(path, document, own, errors)
    check_pins(path, document, own, errors)


def check_document(path, validator, errors):
    document = load(path, errors)
    if document is None:
        return False

    check_parsed(path.relative_to(ROOT).as_posix(), document, validator, errors)
    return True


def documents():
    """Every authored document, matched case-insensitively.

    pathlib globbing is case-sensitive on Linux and not on Windows, so a plain
    *.toml glob would let listings/Evil.TOML through the gate on the runner
    while a contributor on Windows still sees it.
    """
    def toml_files(folder, depth):
        if not folder.is_dir():
            return []
        return sorted(
            path
            for path in folder.rglob("*")
            if path.is_file()
            and path.suffix.lower() == ".toml"
            and len(path.relative_to(folder).parts) == depth
        )

    return toml_files(LISTINGS, 1) + toml_files(PACKS, 2)


def validator():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def main():
    errors = []
    counted = 0

    checker = validator()
    for path in documents():
        if check_document(path, checker, errors):
            counted += 1

    if errors:
        print("\n".join(errors))
        return 1

    print(f"checked {counted} document(s) against the schema, all valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
