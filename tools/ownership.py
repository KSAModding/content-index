#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Whether the account opening a pull request controls the release host it points at.

RFC 0033 for the marker file and the owner id, RFC 0038 for the topic.
"""

import re
import tomllib
from urllib.parse import urlparse

VERIFIED = "verified"
UNVERIFIED = "unverified"
COULD_NOT_EVALUATE = "could-not-evaluate"

MARKER_PATH = ".github/ksa-content-index.toml"
TOPIC = "ksa-index-{login}"

GITHUB_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")

SPACEDOCK_GAME_ID = 22409

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
    owner, name = parts[0], parts[1].removesuffix(".git")
    if not GITHUB_NAME.match(owner) or not GITHUB_NAME.match(name):
        return None
    return f"{owner}/{name}"


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
        if key in ("github", "spacedock"):
            return key, str(hosts[key]), ""
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
    """The proofs on the host the document binds ownership to."""
    listing_id = document.get("id") or ""
    kind, target, reason = authority(document)
    if kind == "github":
        return _verify_repository(target, listing_id, login, author_id, api)
    if kind == "spacedock":
        return _verify_spacedock(target, listing_id, login, author_id, api)
    return Result(UNVERIFIED, reason)


def _verify_spacedock(mod_id, listing_id, login, author_id, api):
    """A SpaceDock mod through its source code link.

    Only the mod's owner, its accepted co-authors and SpaceDock's administrators
    can set that link, and only somebody who controls the repository it names
    can pass a proof there. So the mod's authors decide which repository stands
    for the mod, and whoever controls that repository can list it. A mod
    without a usable link binds to nothing.
    """
    if not mod_id.isdigit():
        return Result(UNVERIFIED, f"'{mod_id}' is not a SpaceDock mod id, which is a number")

    try:
        mod = api.spacedock_mod(mod_id)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))

    if mod is None:
        return Result(UNVERIFIED, f"SpaceDock has no mod {mod_id}")

    if mod.get("error"):
        if "not published" in str(mod.get("reason") or "").lower():
            return Result(UNVERIFIED, f"SpaceDock mod {mod_id} is not published")
        return Result(UNVERIFIED, f"SpaceDock refuses to show mod {mod_id}")

    if str(mod.get("id")) != mod_id:
        return Result(
            COULD_NOT_EVALUATE, f"the answer about SpaceDock mod {mod_id} is not the mod's document"
        )

    if mod.get("game_id") != SPACEDOCK_GAME_ID:
        return Result(UNVERIFIED, f"SpaceDock mod {mod_id} is not a Kitten Space Agency mod")

    link = mod.get("source_code")
    if not link:
        return Result(
            UNVERIFIED,
            f"SpaceDock mod {mod_id} has no source code link, so nothing binds it to a "
            "GitHub repository",
        )

    repository = github_repository(link)
    if repository is None:
        return Result(
            UNVERIFIED,
            f"the source code link of SpaceDock mod {mod_id} does not name a GitHub repository",
        )

    result = _verify_repository(
        repository, listing_id, login, author_id, api, named_by="the link on SpaceDock"
    )
    if result.state == VERIFIED:
        return Result(VERIFIED, "", f"source code link, {result.proof}")
    return Result(
        result.state, f"SpaceDock mod {mod_id} links to {repository}, and {result.reason}"
    )


def _verify_repository(target, listing_id, login, author_id, api, named_by="the listing"):
    """The three proofs on one GitHub repository."""
    try:
        repository = api.repository(target)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))

    if repository is None:
        return Result(UNVERIFIED, f"{target} does not exist or is private")

    full_name = repository.get("full_name") or ""
    if full_name.lower() != target.lower():
        return Result(UNVERIFIED, f"{target} now answers as {full_name}, so {named_by} is stale")

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
