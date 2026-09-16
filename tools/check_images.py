#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the [images] table of authored documents, per RFC 0058 and RFC 0065.

The rules that need only the document run over every document: the sides of an
icon are inside their limits, a description image id is used once, and every
ksa-image reference in the description names such an id. The schema bounds each
side alone, so it cannot state the rules for the shorter side and the ratio. An icon that is
not square only gives a note, which names the square that clients show.

With document paths, the images of those documents are fetched and compared
with their records. On an edit, a record the base branch already carries
unchanged only warns when it fails, so a dead image does not block an unrelated
correction.
"""

import argparse
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_image_references
import images

ROOT = Path(__file__).resolve().parent.parent

PASS = "pass"
REJECT = "reject"
COULD_NOT_EVALUATE = "could-not-evaluate"

UNREADABLE = object()


def check_document(where, document, errors, notes):
    """The image rules the schema cannot express, for one parsed document."""
    seen = {}
    for place, role, record in images.records(document):
        width, height = record.get("width"), record.get("height")
        if (
            role == images.ICON
            and isinstance(width, int)
            and isinstance(height, int)
            and images.LIMITS[role].low <= min(width, height)
            and max(width, height) <= images.LIMITS[role].high * images.LIMITS[role].ratio
        ):
            outside = images.outside_limits(role, width, height)
            if outside:
                errors.append(f"{where}: {place}: {outside}")
            elif width != height:
                left, top, right, bottom = images.center_square(width, height)
                notes.append(
                    f"{where}: {place}: the icon is {width} by {height} pixels, "
                    f"so clients show the square from {left},{top} to {right},{bottom}"
                )
        identifier = record.get("id")
        if role == images.DESCRIPTION and isinstance(identifier, str):
            if identifier in seen:
                errors.append(f"{where}: {place}: id '{identifier}' is already used by {seen[identifier]}")
            seen.setdefault(identifier, place)

    check_image_references.check_document(where, document, errors, notes)


def _key(role, record):
    return (role, record.get("id")) if role == images.DESCRIPTION else (role,)


def _comparable(record):
    return {**record, "sha256": str(record.get("sha256") or "").lower()}


def _git(*arguments):
    try:
        answer = subprocess.run(
            ["git", "-C", str(ROOT), *arguments], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return answer.stdout if answer.returncode == 0 else None


def base_document(ref, path, git=_git):
    """The document at `path` on `ref`.

    None when there is no base to compare with, or the document is not there on
    it, so every record counts as new. UNREADABLE when the base could not be read.
    """
    if ref is None:
        return None
    if ref.startswith("-") or git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") is None:
        return UNREADABLE
    if git("cat-file", "-e", f"{ref}:{path}") is None:
        return None
    text = git("show", f"{ref}:{path}")
    if text is None:
        return UNREADABLE
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def inspect_document(where, document, base, verify=images.verify):
    """Fetch every image of one document. Returns (outcome, messages)."""
    kept = {}
    if isinstance(base, dict):
        kept = {_key(role, record): _comparable(record) for _, role, record in images.records(base)}

    outcomes = []
    messages = []
    verified = 0
    for place, role, record in images.records(document):
        label = f"{where}: {place}"
        try:
            verify(record, role)
        except images.Invalid as error:
            failure, reason = REJECT, str(error)
        except images.Unavailable as error:
            failure, reason = COULD_NOT_EVALUATE, str(error)
        except Exception as error:
            failure, reason = COULD_NOT_EVALUATE, f"the image check behaved unexpectedly: {error!r}"
        else:
            verified += 1
            continue

        if kept.get(_key(role, record)) == _comparable(record):
            messages.append(
                f"{label}: {reason}. The record is unchanged from the base branch, "
                "so this does not block the change"
            )
        elif base is UNREADABLE and failure == REJECT:
            outcomes.append(COULD_NOT_EVALUATE)
            messages.append(
                f"{label}: {reason}. The base branch could not be read, so whether the record "
                "is new is not known"
            )
        else:
            outcomes.append(failure)
            messages.append(f"{label}: {reason}")

    if verified:
        messages.append(f"{where}: {verified} image(s) match their records")
    for outcome in (REJECT, COULD_NOT_EVALUATE):
        if outcome in outcomes:
            return outcome, messages
    return PASS, messages


def inspect_path(path, base_ref=None, verify=images.verify):
    """Fetch the images of the document at `path`, relative to the repository root."""
    try:
        with (ROOT / path).open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError:
        return PASS, [f"{path}: not fetched, the document is not there"]
    except (tomllib.TOMLDecodeError, OSError) as error:
        return PASS, [f"{path}: not fetched, the document does not parse: {error}"]
    return inspect_document(path, document, base_document(base_ref, path), verify)


def main(argv=None):
    import check_index

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("documents", nargs="*", help="the documents whose images to fetch")
    parser.add_argument("--base", help="a git revision of the base branch, so an unchanged record only warns")
    arguments = parser.parse_args(argv)

    entries, _ = check_index.load_documents()
    errors = []
    notes = []
    for entry in entries:
        check_document(entry.where, entry.document, errors, notes)

    rejected = bool(errors)
    for note in notes:
        print(f"note: {note}")

    paths = []
    for document in arguments.documents:
        try:
            paths.append(Path(document).resolve().relative_to(ROOT).as_posix())
        except ValueError:
            parser.error(f"{document} is not in this repository")

    for path in paths:
        outcome, messages = inspect_path(path, arguments.base)
        for message in messages:
            print(f"{outcome}: {message}")
        rejected = rejected or outcome == REJECT

    if errors:
        print("\n".join(errors))
    if rejected:
        return 1

    print(f"checked the images of {len(entries)} document(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
