#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inspect the latest release of a listing, by stamping it and throwing it away.

The stamper's own error split gives the outcomes: StampError is the release
being wrong, so reject; HostError is the host being unreachable this run, so
could-not-evaluate. A pack, a listing with no release host, and a host with no
release yet all pass.
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

WATCHED_TYPES = ("mod", "mod-loader")


class Unavailable(Exception):
    """The stamper could not be loaded, so nothing here can reach a verdict."""


class Outcome:
    """What the inspection of one listing came to."""

    def __init__(self, outcome, messages=()):
        self.outcome = outcome
        self.messages = list(messages)

    @property
    def rejected(self):
        return self.outcome == REJECT


def load_stamper(releases=None):
    """The stamper and the hosts from the generated repository.

    Raises Unavailable when the checkout is missing. The caller reports that as
    could-not-evaluate: a missing checkout says nothing about the listing.
    """
    root = Path(releases or os.environ.get("CONTENT_INDEX_RELEASES") or DEFAULT_RELEASES)
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
    root = Path(releases or os.environ.get("CONTENT_INDEX_RELEASES") or DEFAULT_RELEASES)
    path = root / "game-versions.json"
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


def inspect(document, stamp_release, hosts, game_versions, http):
    """Inspect one authored document's latest release."""
    content_type = document.get("type")
    if content_type not in WATCHED_TYPES:
        return Outcome(
            PASS, [f"type '{content_type}' has no release archive, so there is nothing to inspect"]
        )
    if not document.get("releases"):
        return Outcome(PASS, ["the listing names no release host, so releases enter by pull request"])

    try:
        authority, _ = hosts.build(document.get("releases"), http, document.get("id"))
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

    if not offered:
        return Outcome(PASS, [f"{authority.key} has no release yet"])

    release = latest(offered)
    if release is None:
        return Outcome(
            REJECT,
            [
                f"{authority.key} offers {len(offered)} release(s) and none of them carries a "
                "version that parses as SemVer 2.0.0, so nothing can ever be stamped"
            ],
        )

    try:
        archive, content = authority.download(release)
        facts = release.facts()
        facts["content_type"] = content
        stamp_release.stamp(document, facts, archive, game_versions)
    except stamp_release.StampError as error:
        return Outcome(REJECT, [f"the latest release {release.tag} cannot be stamped: {error}"])
    except (hosts.HostError, urllib.error.HTTPError, OSError) as error:
        return Outcome(COULD_NOT_EVALUATE, [f"the latest release {release.tag} could not be read: {error}"])

    return Outcome(PASS, [f"the latest release {release.version} stamps cleanly"])


def inspect_paths(paths, releases=None, token=None):
    """Inspect each document at `paths`. Returns {path: Outcome}."""
    stamp_release, hosts = load_stamper(releases)
    game_versions = load_game_versions(releases)
    http = hosts.Http(token=token or os.environ.get("GITHUB_TOKEN"))

    results = {}
    for path in paths:
        try:
            with Path(path).open("rb") as handle:
                document = tomllib.load(handle)
        except FileNotFoundError:
            results[str(path)] = Outcome(PASS, ["not inspected, the document is not there"])
            continue
        except (tomllib.TOMLDecodeError, OSError) as error:
            results[str(path)] = Outcome(PASS, [f"not inspected, the document does not parse: {error}"])
            continue

        try:
            results[str(path)] = inspect(document, stamp_release, hosts, game_versions, http)
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
        for message in outcome.messages:
            print(f"{path}: {outcome.outcome}: {message}")
        rejected += outcome.rejected

    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
