#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The note on a listing edit that also reaches a published release (RFC 0081).

The watcher applies an edit to `[compatibility]`, the `[loader]` bounds and `[[dependencies]]` to the newest release with its next tick after the merge.
It waits only while a pull request that adds a release file of the listing is open, and a `game_max` month that is not over yet waits until it is.
The note says which release the edit reaches and when, and it never rejects.
"""

import datetime
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_images
import check_release

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "index-status.toml"

AMEND = "an amendment pull request to content-index-releases can change them"


class Rules:
    """The watcher's own rules: which release an edit reaches, and whether a `game_max` month still runs."""

    def __init__(self, target, month_running):
        self.target = target
        self.month_running = month_running


def load_rules(releases=None):
    """The rules from the generated repository, so the note and the watcher choose the same release."""
    stamp_release, _ = check_release.load_stamper(releases)
    try:
        import listing_edit
    except Exception as error:
        raise check_release.Unavailable(
            f"the listing edit rules of the generated repository do not import: {error!r}"
        ) from error

    def month_running(bound, now):
        try:
            display, _ = stamp_release.resolve_bound(bound, "game_max", [], now)
        except stamp_release.StampError:
            return False
        return display is None

    return Rules(listing_edit.target, month_running)


def stamped(releases, identifier):
    """Every stamped release file of a listing, by version."""
    folder = check_release.releases_root(releases) / "releases" / identifier
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(folder.glob("*.json"))
    }


def index_states(path=STATUS):
    """The casefolded ids that index-status.toml delists or disputes, to that state.

    A file that cannot be read gives no state here, because the status check reports it.
    """
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    entries = document.get("entries")
    if not isinstance(entries, list):
        return {}
    return {
        entry["id"].casefold(): entry.get("state")
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry.get("state") in ("delisted", "disputed")
    }


def _loader_id(document):
    loader = document.get("loader")
    return loader.get("id") if isinstance(loader, dict) else None


def _loader_bounds(document):
    loader = document.get("loader")
    return (loader.get("min"), loader.get("max")) if isinstance(loader, dict) else None


def _dependencies(document):
    entries = document.get("dependencies")
    if not isinstance(entries, list):
        return []
    return sorted(json.dumps(entry, sort_keys=True, default=str) for entry in entries)


def _game_max(document):
    compatibility = document.get("compatibility")
    bound = compatibility.get("game_max") if isinstance(compatibility, dict) else None
    return bound.strip() or None if isinstance(bound, str) else None


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


def notes_for(where, base, head, versions, rules, state=None, now=None):
    """The notes on one listing edit, where `versions` maps each stamped version to its release file."""
    sections, moved = edited(base, head)
    notes = [f"{where}: {text}" for text in _reach(sections, base, head, versions, rules, state, now)]
    if moved:
        notes.append(f"{where}: {_loader_change(_loader_id(base), _loader_id(head))}")
    return notes


def _reach(sections, base, head, versions, rules, state, now):
    """What the note says about the sections the edit changes, one text per note."""
    if not sections:
        return []
    if state == "delisted":
        return [
            f"while the listing is delisted, the watcher stamps no release of it and applies the "
            f"change to {_listed(sections)} to none. Stamped releases keep their stamp, and {AMEND}"
        ]
    if not versions:
        return [
            f"no release of this listing is stamped yet, so the change to {_listed(sections)} "
            "reaches the first release stamped after the merge"
        ]
    if state == "disputed":
        return [
            f"while the listing is disputed, the watcher applies the change to {_listed(sections)} "
            "to no stamped release, and a release stamped after the merge gets it with its own "
            "stamp. Once the dispute ends, the newest release that is neither yanked nor `dev` gets "
            "it with the next watcher tick, unless a release was stamped first. Stamped releases "
            f"keep their stamp, and {AMEND}"
        ]

    version = rules.target(versions)
    if version is None:
        return [
            f"every stamped release of this listing is yanked or `dev`, so the change to "
            f"{_listed(sections)} reaches none of them, only releases stamped after the merge. "
            f"Stamped releases keep their stamp, and {AMEND}"
        ]

    texts = []
    stamped_loader = _loader_id(versions[version])
    if "[loader]" in sections and stamped_loader != _loader_id(head):
        sections = [section for section in sections if section != "[loader]"]
        loader = f"the loader `{stamped_loader}`" if stamped_loader else "no loader"
        text = (
            f"the change to the [loader] bounds reaches only releases stamped after the merge, "
            f"because `{version}`, the newest release, was stamped with {loader}"
        )
        if not sections:
            text += f". Stamped releases keep their stamp, and {AMEND}"
        texts.append(text)
    if sections:
        text = (
            f"the change to {_listed(sections)} reaches `{version}`, the newest release, with the "
            "next watcher tick after the merge. If a pull request that adds a release of this "
            "listing is open in content-index-releases then, the change waits and lands in that "
            "release instead. A release stamped before that tick, `dev` included, gets the change "
            f"with its own stamp, and `{version}` does not."
        )
        month = _game_max(head)
        if (
            "[compatibility]" in sections
            and month is not None
            and month != _game_max(base)
            and rules.month_running(month, now or datetime.datetime.now(datetime.timezone.utc))
        ):
            text += (
                f" The `game_max` month {month} is not over yet, so that bound waits until the "
                "month is over, and the rest of the change does not wait."
            )
        texts.insert(0, f"{text} Older releases keep their stamp, and {AMEND}")
    return texts


def _loader_change(old, new):
    if old is None:
        return f"the new loader `{new}` reaches only releases stamped after the merge"
    if new is None:
        return "removing the loader reaches only releases stamped after the merge"
    return f"the loader changes from `{old}` to `{new}`, which reaches only releases stamped after the merge"


def notes(entries, documents, base_ref, releases=None, status=STATUS):
    """Every note on the changed listings, measured against the base branch."""
    found = []
    states = None
    for entry in entries:
        if entry.where not in documents or entry.type not in check_release.WATCHED_TYPES:
            continue
        base = check_images.base_document(base_ref, entry.where)
        if not isinstance(base, dict):
            continue
        sections, moved = edited(base, entry.document)
        if sections:
            if states is None:
                states = index_states(status)
            try:
                versions = stamped(releases, entry.identifier)
                rules = load_rules(releases)
                texts = _reach(
                    sections, base, entry.document, versions, rules, states.get(entry.folded), None
                )
                found += [f"{entry.where}: {text}" for text in texts]
            except (OSError, ValueError, check_release.Unavailable) as error:
                found.append(f"{entry.where}: which release this edit reaches could not be read: {error}")
        # The loader note needs no release data, so it stays when the releases cannot be read.
        if moved:
            found.append(f"{entry.where}: {_loader_change(_loader_id(base), _loader_id(entry.document))}")
    return found
