#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate the curated vocabulary and report authored tags outside it.
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAGS = ROOT / "tags.toml"

SPEC_VERSION = 1
TAG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONTENT_TYPES = {"mod": "mod", "mod-loader": "mod", "modpack": "mod"}
ENTRY_KEYS = {"tag", "name", "meaning", "forum_prefix"}
REQUIRED_ENTRY_KEYS = {"tag", "name", "meaning"}
SPEC_URL = "https://github.com/KSAModding/content-manager-design/blob/main/spec/tags.md"


def load_vocabulary(path=TAGS):
    """Return the curated tags by content type and all vocabulary errors."""
    errors = []
    where = _relative(path)
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError) as error:
        return {}, [f"{where}: cannot read the curated tag vocabulary: {error}"]

    version = document.get("spec_version")
    if type(version) is not int or version != SPEC_VERSION:
        errors.append(f"{where}: spec_version must be {SPEC_VERSION}")

    unknown = sorted(set(document) - {"spec_version", "mod"})
    for key in unknown:
        errors.append(f"{where}: '{key}' is not a known tag vocabulary")

    vocabulary = {}
    _check_entries(where, "mod", document.get("mod"), vocabulary, errors)
    return vocabulary, errors


def _check_entries(where, content_type, entries, vocabulary, errors):
    if not isinstance(entries, list) or not entries:
        errors.append(f"{where}: [[{content_type}]] must contain at least one tag")
        return

    curated = []
    seen = set()
    vocabulary[content_type] = curated
    for position, entry in enumerate(entries):
        location = f"{where}: {content_type}[{position}]"
        if not isinstance(entry, dict):
            errors.append(f"{location}: the entry must be a table")
            continue

        for key in sorted(set(entry) - ENTRY_KEYS):
            errors.append(f"{location}: '{key}' is not a known field")
        for key in sorted(REQUIRED_ENTRY_KEYS - set(entry)):
            errors.append(f"{location}: '{key}' is required")

        tag = entry.get("tag")
        if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
            errors.append(
                f"{location}: tag must be lowercase words or numbers joined by '-'"
            )
        elif tag in seen:
            errors.append(f"{location}: tag '{tag}' is already defined")
        else:
            curated.append(tag)
            seen.add(tag)

        for key in ("name", "meaning", "forum_prefix"):
            value = entry.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                errors.append(f"{location}: '{key}' must be a non-empty string")


def check_document(path, document, vocabulary):
    """Return warning notes for one schema-valid authored document."""
    content_type = document.get("type")
    vocabulary_name = CONTENT_TYPES.get(content_type)
    if vocabulary_name is None:
        return []

    curated = vocabulary.get(vocabulary_name, set())
    tags = document.get("tags") or []
    where = _relative(path)
    notes = []
    for tag in tags:
        if tag not in curated:
            notes.append(
                f"{where}: tags: '{tag}' is not a curated tag, so no client shows it as "
                f"a filter; the list is at {SPEC_URL}"
            )
    if not any(tag in curated for tag in tags):
        notes.append(
            f"{where}: tags: the document has no curated tag, so no client can include it "
            f"through a curated filter; the list is at {SPEC_URL}"
        )
    return notes


def check(paths=(), tags_path=TAGS):
    """Validate the vocabulary, then report notes for the selected documents."""
    vocabulary, errors = load_vocabulary(tags_path)
    if errors:
        return errors, []

    notes = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError):
            continue
        notes.extend(check_document(path, document, vocabulary))
    return [], notes


def _relative(path):
    try:
        return Path(path).relative_to(ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="authored documents to inspect")
    arguments = parser.parse_args(argv)

    errors, notes = check(arguments.paths)
    for note in notes:
        print(f"note: {note}")
    if errors:
        print("\n".join(errors))
        return 1

    print("tags.toml is well formed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
