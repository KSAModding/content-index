#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Whether the account opening a pull request controls the release host it points at.

RFC 0033 for the marker file and the owner id, RFC 0038 for the topic.
"""

import tomllib
from urllib.parse import urlparse

VERIFIED = "verified"
UNVERIFIED = "unverified"
COULD_NOT_EVALUATE = "could-not-evaluate"

MARKER_PATH = ".github/ksa-content-index.toml"
TOPIC = "ksa-index-{login}"


class Unavailable(Exception):
    """The host could not answer, so the check reached no verdict."""


class Result:
    def __init__(self, state, reason, proof=None):
        self.state = state
        self.reason = reason
        self.proof = proof

    def as_dict(self):
        return {"state": self.state, "reason": self.reason, "proof": self.proof}


def github_repository(url):
    """`owner/name` from a GitHub URL, or None."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return None
    if parsed.netloc.lower() not in ("github.com", "www.github.com"):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def authority(document):
    """The release host ownership binds to, as (kind, target, reason)."""
    releases = document.get("releases")
    if isinstance(releases, dict) and releases:
        hosts = {key: value for key, value in releases.items() if key != "authority"}
        if not hosts:
            return None, None, "the [releases] section names no host"
        if len(hosts) == 1:
            key = next(iter(hosts))
        else:
            key = releases.get("authority")
            if key not in hosts:
                return None, None, "the [releases] section names no valid authority"
        if key == "github":
            return "github", str(hosts[key]), ""
        return key, str(hosts[key]), f"{key} offers no ownership proof a check can read"

    repository = github_repository((document.get("links") or {}).get("repository"))
    if repository:
        return "github", repository, ""
    return None, None, "the document names no release host and no GitHub repository"


def _marker_names(text, listing_id, login):
    """Naming only a login covers every listing on that repository, which is
    what it proves: write access to the host.
    """
    try:
        marker = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    claimed = marker.get("login") or marker.get("account")
    identifier = marker.get("id") or marker.get("listing")
    if not isinstance(claimed, str) or claimed.lower() != login.lower():
        return False
    return not isinstance(identifier, str) or identifier.lower() == listing_id.lower()


def verify(document, login, author_id, api):
    """The three proofs, cheapest first."""
    listing_id = document.get("id") or ""
    kind, target, reason = authority(document)
    if kind != "github":
        return Result(UNVERIFIED, reason)

    try:
        repository = api.repository(target)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))

    if repository is None:
        return Result(UNVERIFIED, f"{target} does not exist or is private")

    full_name = repository.get("full_name") or ""
    if full_name.lower() != target.lower():
        return Result(UNVERIFIED, f"{target} now answers as {full_name}, so the listing is stale")

    if repository.get("fork"):
        return Result(UNVERIFIED, f"{target} is a fork")  # forks inherit files

    owner_id = (repository.get("owner") or {}).get("id")
    if author_id is not None and owner_id == author_id:
        return Result(VERIFIED, "", "owner id")

    try:
        topics = api.topics(target)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))
    if TOPIC.format(login=login.lower()) in topics:
        return Result(VERIFIED, "", "topic")

    try:
        marker = api.file(target, MARKER_PATH)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))
    if marker is not None and _marker_names(marker, listing_id, login):
        return Result(VERIFIED, "", "marker file")

    return Result(
        UNVERIFIED,
        f"{login} did not prove control of {target}: no matching owner, no "
        f"{TOPIC.format(login=login.lower())} topic, and no {MARKER_PATH}",
    )
