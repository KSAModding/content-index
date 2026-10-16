#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve the identifiers in a license expression against the SPDX list.
"""

import re
import sys
from pathlib import Path

from license_expression import (
    PARSE_INVALID_SYMBOL_SEQUENCE,
    ExpressionParseError,
    build_spdx_licensing,
    get_license_index,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import images

# SPDX calls the tail an idstring: letters, digits, `-` and `.`.
IDSTRING = r"[A-Za-z0-9.-]+"
LICENSE_REF = re.compile(
    rf"^(?:DocumentRef-{IDSTRING}:)?LicenseRef-{IDSTRING}(?![\s\S])"
)
SPDX_LIST = "https://spdx.org/licenses/"

# The license list of license-expression also reads a few short names of its
# own, which are not SPDX ids. A bare GPL names no version, and the SPDX list
# has no Assembly-exception or Verbatim-man-pages, so the check refuses these
# names instead of reading them as some other license or exception.
NOT_SPDX = frozenset(
    {"GPL", "GPL 2.0", "GPL 2.0+", "BSD-2", "Assembly-exception", "Verbatim-man-pages"}
)

# How many close ids a message names for an id that is not on the list.
CLOSE_LIMIT = 6

_licensing = None
_known = None
_current = None


def licensing():
    global _licensing
    if _licensing is None:
        index = []
        for entry in get_license_index():
            aliases = [name for name in entry.get("other_spdx_license_keys") or [] if name not in NOT_SPDX]
            index.append(dict(entry, other_spdx_license_keys=aliases))
        _licensing = build_spdx_licensing(index)
    return _licensing


def known(name):
    """Whether `name` is on the license or the exception list, in any case."""
    global _known
    if _known is None:
        _known = {
            alias.lower()
            for symbol in licensing().known_symbols.values()
            for alias in (symbol.key, *symbol.aliases)
        }
    return name.lower() in _known


def current_ids(exceptions=False):
    """The ids a close match can name: every SPDX license id that is not
    deprecated, or with `exceptions` every such exception id."""
    global _current
    if _current is None:
        _current = {False: set(), True: set()}
        for symbol in licensing().known_symbols.values():
            if not symbol.is_deprecated and not LICENSE_REF.match(symbol.key):
                _current[bool(symbol.is_exception)].add(symbol.key)
        _current = {place: sorted(ids) for place, ids in _current.items()}
    return _current[exceptions]


def after_with(expression, name):
    """Whether `name` stands directly after a WITH, where only an exception goes."""
    words = r"\s+".join(re.escape(word) for word in name.split())
    return re.search(rf"(?i)(?<![^\s()])WITH\s+{words}(?![^\s()])", expression) is not None


def close_ids(name, ids):
    """The ids that start like `name`, such as GPL-3.0-only for GPL.

    An id that is the start itself comes first, then the ids that continue with
    a version, then the shorter ones. When no id starts with the whole name, the
    name with - in place of its spaces is tried, and then the letters at its
    start without a v in front of a version. So CC BY-SA 4.0 finds CC-BY-SA-4.0,
    MIT+ finds MIT, Apache2 finds Apache-2.0 and GPLv3 finds GPL-3.0-only.
    """
    letters = re.match(r"[A-Za-z]*", name).group()
    if letters[-1:] in ("v", "V") and name[len(letters):][:1].isdigit():
        letters = letters[:-1]
    for stem in (name, re.sub(r"\s+", "-", name), letters):
        if not stem:
            continue
        folded = stem.lower()
        prefix = folded + "-"

        def rank(identifier):
            if identifier.lower() == folded:
                return (0, False, 0, "", "")
            following = identifier[len(prefix)]
            return (1, not following.isdigit(), len(identifier), identifier.lower(), identifier)

        found = [
            identifier
            for identifier in ids
            if identifier.lower() == folded or identifier.lower().startswith(prefix)
        ]
        if found:
            return sorted(found, key=rank)[:CLOSE_LIMIT]
    return []


def close_text(expression, names):
    """The close ids of each name that is on no list, as clauses of a message.

    A name after WITH gets close exception ids and any other name gets close
    license ids, so a hint never names an id that is wrong in that place.
    """
    clauses = []
    for name in names:
        if known(name):
            continue
        found = close_ids(name, current_ids(exceptions=after_with(expression, name)))
        if len(found) == 1:
            clauses.append(f"; the id close to {name} is {found[0]}")
        elif found:
            clauses.append(f"; ids close to {name} are {', '.join(found[:-1])} and {found[-1]}")
    return "".join(clauses)


def missing_operator(expression):
    """The message for two identifiers written next to each other."""
    return [
        f"'{expression}' has two license identifiers with no operator between "
        "them; join several licenses with AND or OR, such as "
        "GPL-2.0-only AND CC-BY-SA-4.0"
    ]


def holds_a_reference(symbol):
    """Whether one name the library read is a `LicenseRef-` beside another word."""
    words = str(symbol).split()
    return len(words) > 1 and any(LICENSE_REF.match(word) for word in words)


def errors_for(expression):
    """What is wrong with `expression`. Empty means nothing is."""
    if not isinstance(expression, str) or not expression.strip():
        return []

    spdx = licensing()

    # validate() keeps the parse error as a string only, so parse here as well to
    # tell two identifiers with no operator between them from an unknown one.
    try:
        spdx.parse(expression, strict=True)
    except ExpressionParseError as error:
        if getattr(error, "error_code", None) == PARSE_INVALID_SYMBOL_SEQUENCE:
            return missing_operator(expression)
    except Exception:
        # validate() below reads the same expression and reports every other
        # failure, so this one can pass in silence.
        pass

    try:
        result = spdx.validate(expression, strict=True)
    except Exception:
        return [
            f"'{expression}' does not parse as an SPDX license expression; join several "
            "licenses with AND or OR, such as GPL-2.0-only AND CC-BY-SA-4.0"
        ]

    unknown = [
        symbol for symbol in result.invalid_symbols if not LICENSE_REF.match(str(symbol))
    ]
    if unknown:
        # The library reads words it does not know as one name, so a `LicenseRef-`
        # beside another word is a missing operator and not an unknown license.
        if any(holds_a_reference(symbol) for symbol in unknown):
            return missing_operator(expression)
        names = sorted(str(symbol) for symbol in unknown)
        return [
            f"'{expression}' names {', '.join(names)}, which is not on the SPDX license list"
            f"{close_text(expression, names)}; the identifiers are at {SPDX_LIST}"
        ]

    if result.errors and not result.invalid_symbols:
        return [f"'{expression}': {'; '.join(result.errors)}"]

    return []


def check_document(where, document, errors):
    """Append any license error of one already parsed document."""
    for message in errors_for(document.get("license")):
        errors.append(f"{where}: license: {message}")
    for place, _, record in images.records(document):
        for message in errors_for(record.get("license")):
            errors.append(f"{where}: {place}.license: {message}")


def main():
    import check_index

    entries, _ = check_index.load_documents()
    errors = []
    for entry in entries:
        check_document(entry.where, entry.document, errors)

    if errors:
        print("\n".join(errors))
        return 1

    print(f"checked {len(entries)} license expression(s) against the SPDX list, all resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
