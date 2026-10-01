#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The note on a listing edit that also reaches a published release (RFC 0081).

The watcher applies an edit to `[compatibility]`, the `[loader]` bounds and `[[dependencies]]` to the newest release with its next tick after the merge.
The note says which release that is, and it never rejects.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_images
import check_release


def load_target(releases=None):
    """The watcher's own choice of the release an edit reaches, from the generated repository."""
    check_release.load_stamper(releases)
    import listing_edit

    return listing_edit.target


def stamped(releases, identifier):
    """Every stamped release file of a listing, by version."""
    folder = check_release.releases_root(releases) / "releases" / identifier
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(folder.glob("*.json"))
    }


def _loader_id(document):
    loader = document.get("loader")
    return loader.get("id") if isinstance(loader, dict) else None


def _loader_bounds(document):
    loader = document.get("loader")
    return (loader.get("min"), loader.get("max")) if isinstance(loader, dict) else None


def _dependencies(document):
    return sorted(json.dumps(entry, sort_keys=True) for entry in document.get("dependencies") or [])


def edited(base, head):
    """The sections the watcher carries to the newest release that the edit changes, and whether the loader id changed."""
    sections = []
    if base.get("compatibility") != head.get("compatibility"):
        sections.append("[compatibility]")
    moved = _loader_id(base) != _loader_id(head)
    if not moved and _loader_bounds(base) != _loader_bounds(head):
        sections.append("[loader]")
    if _dependencies(base) != _dependencies(head):
        sections.append("[[dependencies]]")
    return sections, moved


def _listed(items):
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def notes_for(where, base, head, versions, target):
    """The notes on one listing edit, where `versions` maps each stamped version to its release file."""
    sections, moved = edited(base, head)
    if not versions or not (sections or moved):
        return []

    notes = []
    version = target(versions)
    if sections and version is not None:
        notes.append(
            f"{where}: the change to {_listed(sections)} reaches `{version}`, the newest release, "
            "with the next watcher tick after the merge, unless a release pull request of this "
            "listing is open or a newer release is stamped first, which then carries it. Older "
            "releases keep their stamp, and an amendment pull request to content-index-releases "
            "changes them"
        )
    if moved:
        notes.append(f"{where}: {_loader_change(_loader_id(base), _loader_id(head))}")
    return notes


def _loader_change(old, new):
    if old is None:
        return f"the new loader `{new}` reaches only releases stamped after the merge"
    if new is None:
        return "removing the loader reaches only releases stamped after the merge"
    return f"the loader changes from `{old}` to `{new}`, which reaches only releases stamped after the merge"


def notes(entries, documents, base_ref, releases=None):
    """Every note on the changed listings, measured against the base branch."""
    found = []
    for entry in entries:
        if entry.where not in documents or entry.type not in check_release.WATCHED_TYPES:
            continue
        base = check_images.base_document(base_ref, entry.where)
        if not isinstance(base, dict) or edited(base, entry.document) == ([], False):
            continue
        try:
            versions = stamped(releases, entry.identifier)
            target = load_target(releases)
        except (OSError, ValueError, ImportError, check_release.Unavailable) as error:
            found.append(f"{entry.where}: which release this edit reaches could not be read: {error}")
            continue
        found += notes_for(entry.where, base, entry.document, versions, target)
    return found
