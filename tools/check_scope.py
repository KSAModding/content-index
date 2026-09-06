#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Decide whether a change is narrow enough to merge itself.
"""

import re
from collections import namedtuple

SUFFIX = r"\.[Tt][Oo][Mm][Ll]"
LISTING = re.compile(rf"^listings/[^/]+{SUFFIX}(?![\s\S])")
PACK = re.compile(rf"^packs/[^/]+/[^/]+{SUFFIX}(?![\s\S])")

LISTING_KIND = "listing"
PACK_KIND = "pack"

# In this order wherever a caller reports several, so two kinds always read the
# same way around.
KINDS = ((LISTING_KIND, LISTING), (PACK_KIND, PACK))

WRITING = ("added", "modified")

Change = namedtuple("Change", "path status")


def changes(paths, status="added"):
    return [Change(path, status) for path in paths]


def kind_of(path):
    """The kind of document at `path`, or None when the path is not a document."""
    for kind, pattern in KINDS:
        if pattern.match(path):
            return kind
    return None


def is_document(path):
    return kind_of(path) is not None


def documents(changes):
    """The document paths among `changes`, in the order given."""
    return [change.path for change in changes if is_document(change.path)]


def kinds(changes):
    """The kinds of document `changes` touches, in the order KINDS names them."""
    found = {kind_of(change.path) for change in changes}
    return [kind for kind, _ in KINDS if kind in found]


def evaluate(changes):
    """Whether this set of changes is an auto-merge candidate.

    Returns (candidate, documents, reason). The reason is written for the
    author when the answer is no, and is empty when it is yes.
    """
    changes = list(changes)
    found = documents(changes)
    other = [change.path for change in changes if not is_document(change.path)]

    if not changes:
        return False, [], "the change touches no file at all"
    if not found:
        return False, [], "the change touches no listing or pack document"
    if other:
        listed = ", ".join(sorted(other)[:5])
        if len(other) > 5:
            listed += f", and {len(other) - 5} more"
        return False, found, f"the change also touches {listed}"
    if len(found) > 1:
        return False, found, f"the change touches {len(found)} documents, and one merges itself"

    only = changes[0]
    if only.status not in WRITING:
        return (
            False,
            found,
            f"the change {only.status} {only.path}, and a listing is removed through "
            "index-status.toml so the entry stays as a tombstone",
        )
    return True, found, ""
