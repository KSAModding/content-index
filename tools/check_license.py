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
    get_spdx_licensing,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import images

# SPDX calls the tail an idstring: letters, digits, `-` and `.`.
IDSTRING = r"[A-Za-z0-9.-]+"
LICENSE_REF = re.compile(
    rf"^(?:DocumentRef-{IDSTRING}:)?LicenseRef-{IDSTRING}(?![\s\S])"
)
SPDX_LIST = "https://spdx.org/licenses/"

_licensing = None


def licensing():
    global _licensing
    if _licensing is None:
        _licensing = get_spdx_licensing()
    return _licensing


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
        named = ", ".join(sorted(str(symbol) for symbol in unknown))
        return [
            f"'{expression}' names {named}, which is not on the SPDX license list; "
            f"the identifiers are at {SPDX_LIST}"
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
