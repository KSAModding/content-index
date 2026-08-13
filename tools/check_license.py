#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve the identifiers in a license expression against the SPDX list.
"""

import re
import sys

from license_expression import get_spdx_licensing

# SPDX calls the tail an idstring: letters, digits, `-` and `.`.
IDSTRING = r"[A-Za-z0-9.-]+"
LICENSE_REF = re.compile(
    rf"^(?:DocumentRef-{IDSTRING}:)?LicenseRef-{IDSTRING}(?![\s\S])"
)

_licensing = None


def licensing():
    global _licensing
    if _licensing is None:
        _licensing = get_spdx_licensing()
    return _licensing


def errors_for(expression):
    """What is wrong with `expression`. Empty means nothing is."""
    if not isinstance(expression, str) or not expression.strip():
        return []

    spdx = licensing()

    try:
        result = spdx.validate(expression, strict=True)
    except Exception:
        return [f"'{expression}' does not parse as an SPDX license expression"]

    unknown = [
        symbol for symbol in result.invalid_symbols if not LICENSE_REF.match(str(symbol))
    ]
    if unknown:
        named = ", ".join(sorted(str(symbol) for symbol in unknown))
        return [f"'{expression}' names {named}, which is not on the SPDX license list"]

    if result.errors and not result.invalid_symbols:
        return [f"'{expression}': {'; '.join(result.errors)}"]

    return []


def check_document(where, document, errors):
    """Append any license error of one already parsed document."""
    for message in errors_for(document.get("license")):
        errors.append(f"{where}: license: {message}")


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
