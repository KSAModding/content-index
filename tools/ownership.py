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

# Which host a verdict about an edit is talking about.
CURRENT_HOST = "the authority the listing already names"
NEW_HOST = "the authority this change moves to"
RENAMED_HOST = "the repository the listing's host was renamed into"


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


def _bound(document):
    """The host a document binds ownership to, folded for comparison."""
    kind, target, _ = authority(document)
    return (
        kind.lower() if isinstance(kind, str) else kind,
        target.lower() if isinstance(target, str) else target,
    )


def same_authority(left, right):
    """Whether two documents bind ownership to the same release host.

    Binding to nothing counts as the same: neither moves the authority.
    """
    return _bound(left) == _bound(right)


def renamed_into(base, submitted, api):
    """Whether the base authority redirects to the submitted one.

    GitHub answers the old name with the repository under its new one, and only
    its owner can rename or transfer it, so the redirect says the host moved
    rather than changed. Raises Unavailable: a silent host is neither answer.
    """
    base_kind, base_target, _ = authority(base)
    kind, target, _ = authority(submitted)
    if base_kind != "github" or kind != "github":
        return False

    repository = api.repository(base_target)
    if repository is None or repository.get("fork"):
        return False

    return (repository.get("full_name") or "").lower() == target.lower()


def _about(result, where):
    """Say which authority a verdict is about. A pass needs no explanation."""
    if result.state == VERIFIED:
        return result
    return Result(result.state, f"{where}: {result.reason}", result.proof)


def verify_change(base, submitted, login, author_id, api):
    """Ownership for one changed document.

    An edit is verified against the authority the base version names, because
    the submitted one is written by whoever opened the pull request. Pointing
    the listing at a different host verifies against both. A rename is not a
    different host. A new listing has no base and declares its own.
    """
    if base is None:
        return verify(submitted, login, author_id, api)

    current = verify(base, login, author_id, api)
    if same_authority(base, submitted):
        return current

    if current.state != VERIFIED:
        try:
            renamed = renamed_into(base, submitted, api)
        except Unavailable as error:
            return _about(Result(COULD_NOT_EVALUATE, str(error)), CURRENT_HOST)
        if renamed:
            return _about(verify(submitted, login, author_id, api), RENAMED_HOST)
        return _about(current, CURRENT_HOST)

    moved = verify(submitted, login, author_id, api)
    if moved.state != VERIFIED:
        return _about(moved, NEW_HOST)

    return Result(VERIFIED, "", f"{current.proof}, then {moved.proof}")
