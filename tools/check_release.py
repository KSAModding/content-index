#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect the latest release of a listing, by stamping it and throwing it away.

The stamper's own error split gives the outcomes: StampError is the release
being wrong, so reject; HostError is the host being unreachable this run, so
could-not-evaluate. A pack, a listing with no release host, and a host with no
release yet all pass. A `tag_prefix` that no release of the repository starts
with is rejected, because the watcher would never stamp a release. For a
vehicle or a save, a release whose install folder another listing of that type
already holds is rejected too (RFC 0085).
"""

import argparse
import json
import os
import sys
import tomllib
import urllib.error
from pathlib import Path

# The sibling checkout the workflow makes. A local run either has one next to
# this repository or points at one.
DEFAULT_RELEASES = Path(__file__).resolve().parent.parent.parent / "content-index-releases"

PASS = "pass"
REJECT = "reject"
COULD_NOT_EVALUATE = "could-not-evaluate"

WATCHED_TYPES = ("mod", "mod-loader", "vehicle", "save")

# RFC 0085: a release of these types installs one game folder, and no two
# listings of one type may install into the same folder.
FOLDER_TYPES = ("vehicle", "save")


class Unavailable(Exception):
    """The stamper could not be loaded, so nothing here can reach a verdict."""


class Outcome:
    """What the inspection of one listing came to.

    The summary lines tell the author nothing, so only the job summary shows them.
    """

    def __init__(self, outcome, messages=(), summary=()):
        self.outcome = outcome
        self.messages = list(messages)
        self.summary = list(summary)

    @property
    def rejected(self):
        return self.outcome == REJECT


def releases_root(releases=None):
    """The checkout of the generated repository."""
    return Path(releases or os.environ.get("CONTENT_INDEX_RELEASES") or DEFAULT_RELEASES)


def load_stamper(releases=None):
    """The stamper and the hosts from the generated repository.

    Raises Unavailable when the checkout is missing. The caller reports that as
    could-not-evaluate: a missing checkout says nothing about the listing.
    """
    root = releases_root(releases)
    tools = root / "tools" if (root / "tools").is_dir() else root
    if not (tools / "stamp_release.py").is_file():
        raise Unavailable(
            f"the stamper is not at {tools}: point --releases or CONTENT_INDEX_RELEASES "
            "at a checkout of KSAModding/content-index-releases"
        )

    # hosts.py imports stamp_release by plain name
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import hosts
        import stamp_release
    except Exception as error:
        raise Unavailable(f"the stamper at {tools} does not import: {error!r}") from error
    return stamp_release, hosts


def load_game_versions(releases=None):
    """The game release list an authored month bound resolves against."""
    path = releases_root(releases) / "game-versions.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["versions"]
    except (OSError, ValueError, KeyError) as error:
        raise Unavailable(f"the game release list at {path} is not readable: {error}") from error


def latest(releases):
    """The most recently published release that carries a version at all.
    """
    stampable = [release for release in releases if release.version]
    if not stampable:
        return None
    return max(stampable, key=lambda release: (release.release_date or "", release.tag))


def inspect(document, stamp_release, hosts, game_versions, http, folders=None):
    """Inspect one authored document's latest release.

    For a vehicle or a save, `folders(content_type)` gives the install folders
    that the stamped releases of that type hold, as `folder_holders` of the
    stamper reads them. Without it they are read from the generated repository.
    """
    content_type = document.get("type")
    if content_type not in WATCHED_TYPES:
        return Outcome(
            PASS,
            summary=[f"type '{content_type}' has no release archive, so there is nothing to inspect"],
        )
    if not document.get("releases"):
        return Outcome(PASS, ["the listing names no release host, so releases enter by pull request"])

    try:
        authority, mirrors = hosts.build(document.get("releases"), http, document.get("id"))
    except stamp_release.StampError as error:
        return Outcome(REJECT, [str(error)])
    if authority is None:
        return Outcome(PASS, ["the listing names no release host, so releases enter by pull request"])

    try:
        offered, _ = authority.releases()
    except stamp_release.StampError as error:
        return Outcome(REJECT, [str(error)])
    except (hosts.HostError, urllib.error.HTTPError, OSError) as error:
        return Outcome(COULD_NOT_EVALUATE, [f"{authority.key} could not be read: {error}"])

    # The tag_prefix also applies to a GitHub mirror, so its releases are read only for that.
    for mirror in mirrors or ():
        if not getattr(mirror, "tag_prefix", ""):
            continue
        try:
            listed, _ = mirror.releases()
        except (stamp_release.StampError, hosts.HostError, urllib.error.HTTPError, OSError) as error:
            return Outcome(COULD_NOT_EVALUATE, [f"{mirror.key} could not be read: {error}"])
        if not listed and getattr(mirror, "skipped", 0):
            return Outcome(REJECT, [unmatched(mirror)])

    if not offered:
        if getattr(authority, "skipped", 0):
            return Outcome(REJECT, [unmatched(authority)])
        return Outcome(PASS, [f"{authority.key} has no release yet"])

    release = latest(offered)
    if release is None:
        return Outcome(
            REJECT,
            [
                f"{authority.key} offers {len(offered)} release(s) and none of them carries a "
                "version the index can read, such as 1.2.3 or 0.5, so nothing can ever be stamped"
            ],
        )

    holders, notes, more = None, [], {}
    if content_type in FOLDER_TYPES:
        if not hasattr(stamp_release, "check_folder"):
            return Outcome(
                COULD_NOT_EVALUATE,
                [f"the stamper of content-index-releases cannot stamp a {content_type} yet"],
            )
        try:
            holders = (folders or _stamped_folders(stamp_release))(content_type)
        except stamp_release.StampError as error:
            return Outcome(
                COULD_NOT_EVALUATE,
                [f"the install folders of the other {content_type} listings could not be read: {error}"],
            )
        more = {"notes": notes}

    # The explanation reads the asset names from the tag without its prefix.
    prefix = getattr(release, "tag_prefix", "")
    named = f"{release.tag} (tag_prefix `{prefix}`)" if prefix else release.tag
    try:
        archive, content = authority.download(release)
        facts = release.facts()
        facts["content_type"] = content
        stamped = stamp_release.stamp(document, facts, archive, game_versions, **more)
        if holders is not None:
            stamp_release.check_folder(stamped, holders)
    except stamp_release.StampError as error:
        return Outcome(REJECT, [f"the latest release {named} cannot be stamped: {error}"])
    except (hosts.HostError, urllib.error.HTTPError, OSError) as error:
        return Outcome(COULD_NOT_EVALUATE, [f"the latest release {named} could not be read: {error}"])

    return Outcome(PASS, [f"the latest release {release.version} stamps cleanly", *notes])


def _stamped_folders(stamp_release, releases=None):
    """The install folders by type, read once per type from the generated repository."""
    folder = releases_root(releases) / "releases"
    read = {}

    def folders(content_type):
        if content_type not in read:
            read[content_type] = stamp_release.folder_holders(folder, content_type)
        return read[content_type]

    return folders


def unmatched(host):
    """The rejection of a GitHub host whose tag_prefix starts the tag of none of its releases."""
    return (
        f"{host.key} has {host.skipped} release(s) and the tag of none of them starts "
        f"with the tag_prefix `{host.tag_prefix}`, so nothing can ever be stamped"
    )


def inspect_paths(paths, releases=None, token=None):
    """Inspect each document at `paths`. Returns {path: Outcome}."""
    stamp_release, hosts = load_stamper(releases)
    game_versions = load_game_versions(releases)
    http = hosts.Http(token=token or os.environ.get("GITHUB_TOKEN"))
    folders = _stamped_folders(stamp_release, releases)

    results = {}
    for path in paths:
        try:
            with Path(path).open("rb") as handle:
                document = tomllib.load(handle)
        except FileNotFoundError:
            results[str(path)] = Outcome(PASS, summary=["not inspected, the document is not there"])
            continue
        except (tomllib.TOMLDecodeError, OSError) as error:
            # The schema check reports a document that does not parse.
            results[str(path)] = Outcome(
                PASS, summary=[f"not inspected, the document does not parse: {error}"]
            )
            continue

        try:
            results[str(path)] = inspect(document, stamp_release, hosts, game_versions, http, folders)
        except Exception as error:
            results[str(path)] = Outcome(
                COULD_NOT_EVALUATE, [f"the stamper behaved unexpectedly: {error!r}"]
            )
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("documents", nargs="+", help="the authored documents to inspect")
    parser.add_argument("--releases", help="a checkout of KSAModding/content-index-releases")
    arguments = parser.parse_args(argv)

    try:
        results = inspect_paths(arguments.documents, arguments.releases)
    except Unavailable as error:
        print(f"could not inspect: {error}", file=sys.stderr)
        return 2

    rejected = 0
    for path, outcome in sorted(results.items()):
        for message in outcome.messages + outcome.summary:
            print(f"{path}: {outcome.outcome}: {message}")
        rejected += outcome.rejected

    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
