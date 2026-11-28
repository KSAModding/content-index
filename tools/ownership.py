#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Whether the account opening a pull request controls the release host it points at.

RFC 0033 for the marker file and the owner id, RFC 0038 for the topic, RFC 0079
for a fork and for a SpaceDock mod.
"""

import hashlib
import json
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple
from pathlib import Path

VERIFIED = "verified"
UNVERIFIED = "unverified"
COULD_NOT_EVALUATE = "could-not-evaluate"
REJECTED = "rejected"

MARKER_PATH = ".github/ksa-content-index.toml"
TOPIC = "ksa-index-{login}"

# What an unverified pull request tells its author. content-index-releases
# imports this module and shows the same text.
ADVICE = (
    "The proof is something only you can put on the release repository, which "
    "is what says you agree to it being indexed. Either set the topic "
    f"`{TOPIC.format(login='<your-github-username>')}` on it, or, when it "
    f"is not a fork, commit `{MARKER_PATH}` naming your username. A fork "
    "also passes when your account owns it. For a SpaceDock host, set "
    "your GitHub repository as the mod's source code link on SpaceDock, and put "
    "the proof on that repository."
)

# RFC 0085: a vehicle or a save needs no repository of its own, so a document of
# these types with no host is told every path it has.
SHARE_TYPES = ("vehicle", "save")
SHARE_ADVICE = (
    "A vehicle or a save can name a GitHub repository of your own under "
    "`[releases] github`, with a `tag_prefix` when the repository holds more than "
    "one share, and you put the proof on it as on any release repository: the topic "
    f"`{TOPIC.format(login='<your-github-username>')}`, or `{MARKER_PATH}` naming your "
    "username, which then covers every share in that repository. Or it can name a "
    "share host that `hosts.toml` registers, and publish through the host. Without "
    "either, a steward decides, and each release enters by a release pull request in "
    "content-index-releases."
)

# What an unverified listing on a share host tells its author (RFC 0094).
SHARE_HOST_ADVICE = (
    "A listing on a share host is proved by the host. Publish and edit it through the "
    "host, which opens the pull request from its own account with an attestation of "
    "the change, or link your GitHub account to your account on the host and open "
    "the pull request yourself."
)

GITHUB_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
LOGIN = re.compile(r"^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

SPACEDOCK_API = "https://spacedock.info/api"
SPACEDOCK_GAME_ID = 22409
USER_AGENT = "KSAModding-content-index-ownership"

# Which host a verdict about an edit is talking about.
CURRENT_HOST = "the authority the listing already names"
NEW_HOST = "the authority this change moves to"
RENAMED_HOST = "the repository the listing's host was renamed into"

# The keys of [releases] that name no host. `since` (RFC 0079) and `tag_prefix`
# (RFC 0096) only say which releases the watcher stamps, so they never count as a host.
NOT_HOSTS = ("authority", "since", "tag_prefix")

# The hosts every listing can name. Any other key of [releases] names a share
# host of RFC 0094, a table of hosts.toml.
FIXED_HOSTS = ("github", "spacedock")
SHARE_KIND = "share"

# Where a share host keeps what the proofs read, by RFC 0094; these names stay
# here, in one place.
HOSTS_FILE = Path(__file__).resolve().parent.parent / "hosts.toml"
OWNER_RECORD = "owners/{type}/{id}.json"
ATTESTATION = "attestations/{digest}.json"
RAW_FILE = "https://raw.githubusercontent.com/{storage}/HEAD/{path}"
SHARE_FOLDERS = {"vehicles": "vehicle", "saves": "save"}
MAX_SHARE_FILE = 64 * 1024

# A host with `data` serves the signature of each data file at the file's path
# with this appended (RFC 0104). A data file read from there is a SignedFile,
# with the text of the .sig and the key in hosts.toml that it was verified by.
# UNSIGNED stands for a file that has no valid signature by `key`, which
# counts as no file at all.
SIGNATURE = ".sig"
SignedFile = namedtuple("SignedFile", "text signature key")
UNSIGNED = object()

# The exact data file a verified proof rests on, so that the pull request can
# keep a copy of it (RFC 0104, rule 30).
Evidence = namedtuple("Evidence", "path text signature key")

# A listing bound to a share host: the key of the host, the value under
# [releases], and the table of hosts.toml.
Share = namedtuple("Share", "key id table")


def share_keys(releases):
    """The keys of a `[releases]` section that name a share host."""
    if not isinstance(releases, dict):
        return []
    return [key for key in releases if key not in FIXED_HOSTS and key not in NOT_HOSTS]


BLOB = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def canonical_change(changes):
    """The canonical form of a pull request's change, which a share host attests (RFC 0094).

    One line per path the change touches, `<path> <blob>` with the git blob id
    of the file at the head, or `<path> deleted`. A rename deletes the old path.
    The lines are sorted by the UTF-8 bytes of the path, and each ends with LF.
    `changes` are as `check_scope.Change` gives them, with `blob`. Raises
    ValueError for a file that has no blob id.
    """
    lines = {}
    for change in changes:
        if change.status == "removed":
            lines[change.path] = "deleted"
            continue
        if change.status == "renamed" and change.previous_path:
            lines[change.previous_path] = "deleted"
        blob = (change.blob or "").lower()
        if not BLOB.fullmatch(blob):
            raise ValueError(f"GitHub gives no blob id of {change.path}")
        lines[change.path] = blob
    return "".join(
        f"{path} {lines[path]}\n" for path in sorted(lines, key=lambda path: path.encode("utf-8"))
    )


def change_digest(changes):
    """The lowercase hex SHA-256 of the canonical form, which names the attestation file."""
    return hashlib.sha256(canonical_change(changes).encode("utf-8")).hexdigest()


class Unavailable(Exception):
    """The host could not answer, so the check reached no verdict."""


class Result:
    def __init__(self, state, reason, proof=None, instructions=None, evidence=None):
        self.state = state
        self.reason = reason
        self.proof = proof
        self.instructions = instructions
        self.evidence = evidence

    def as_dict(self):
        value = {"state": self.state, "reason": self.reason, "proof": self.proof}
        if self.evidence is not None:
            value["evidence"] = self.evidence._asdict()
        return value


def github_repository(url):
    """`owner/name` from a GitHub URL, or None."""
    try:
        parsed = urllib.parse.urlparse(url or "")
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


def spacedock_mod(mod_id, user_agent=USER_AGENT):
    """SpaceDock's info about a mod, as it gives it. SpaceDock needs no token."""
    url = f"{SPACEDOCK_API}/mod/{urllib.parse.quote(str(mod_id), safe='')}"
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    request = urllib.request.Request(url, headers=headers)
    refused = False
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            text = answer.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        if error.code not in (401, 403):
            raise Unavailable(f"HTTP {error.code} asking SpaceDock for mod {mod_id}")
        refused = True
        text = error.read()
    except OSError as error:
        # A URLError prints as "<urlopen error ...>", which a GitHub comment hides as an
        # HTML tag, so the reason carries only what went wrong.
        detail = error.reason if isinstance(error, urllib.error.URLError) else error
        raise Unavailable(f"SpaceDock did not answer about mod {mod_id}: {detail}") from error

    try:
        document = json.loads(text)
    except ValueError as error:
        raise Unavailable(
            f"SpaceDock answered about mod {mod_id} with something that is not JSON"
        ) from error
    if not isinstance(document, dict):
        raise Unavailable(f"SpaceDock answered about mod {mod_id} with no document")
    if refused and not document.get("error"):
        raise Unavailable(f"HTTP 4xx asking SpaceDock for mod {mod_id}")
    return document


def share_hosts(path=HOSTS_FILE):
    """The tables of hosts.toml by host key, or none when the file is not there or does not read.

    The checks keep a wrong hosts.toml off the main branch, so a file that does
    not read here only means that nothing verifies through a share host.
    """
    try:
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return {key: table for key, table in document.items() if isinstance(table, dict)}


def authority(document, registry=None):
    """The release host ownership binds to, as (kind, target, reason).

    A share host has the kind `share` and a Share as its target. `registry` is
    the tables of hosts.toml, read from this checkout when it is not given.
    """
    releases = document.get("releases")
    if isinstance(releases, dict) and releases:
        hosts = {key: value for key, value in releases.items() if key not in NOT_HOSTS}
        if not hosts:
            return None, None, "the [releases] section names no host"
        if len(hosts) == 1:
            key = next(iter(hosts))
        else:
            key = releases.get("authority")
            if key not in hosts:
                return None, None, "the [releases] section names no valid authority"
        if key in FIXED_HOSTS:
            return key, str(hosts[key]), ""
        table = (share_hosts() if registry is None else registry).get(key)
        if isinstance(table, dict) and table.get("kind") == SHARE_KIND:
            return SHARE_KIND, Share(key, str(hosts[key]), table), ""
        return key, str(hosts[key]), (
            f"{key} is not a share host that hosts.toml registers, so it offers no "
            "ownership proof a check can read"
        )

    repository = github_repository((document.get("links") or {}).get("repository"))
    if repository:
        return "github", repository, ""
    return None, None, "the document names no release host and no GitHub repository"


def _marker_login(text, listing_id):
    """The login a marker file names for this listing, or None.

    Naming only a login covers every listing on that repository, which is
    what it proves: write access to the host.
    """
    try:
        marker = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None
    claimed = marker.get("login") or marker.get("account")
    identifier = marker.get("id") or marker.get("listing")
    if not isinstance(claimed, str):
        return None
    if isinstance(identifier, str) and identifier.lower() != listing_id.lower():
        return None
    return claimed


def _marker_names(text, listing_id, login):
    claimed = _marker_login(text, listing_id)
    return claimed is not None and claimed.lower() == login.lower()


def verify(document, login, author_id, api, registry=None):
    """The proofs on the host the document binds ownership to."""
    listing_id = document.get("id") or ""
    kind, target, reason = authority(document, registry)
    if kind == "github":
        return _verify_repository(target, listing_id, login, author_id, api)
    if kind == "spacedock":
        return _verify_spacedock(target, listing_id, login, author_id, api)
    if kind == SHARE_KIND:
        return _verify_share(target, document.get("type"), listing_id, author_id, api)
    if kind is None and document.get("type") in SHARE_TYPES:
        return Result(UNVERIFIED, reason, instructions=SHARE_ADVICE)
    return Result(UNVERIFIED, reason)


def share_file(table, path, user_agent=USER_AGENT):
    """A data file of the storage repository of a share host, as text, or None
    when it is not there.

    The GitHub Pages address of the repository is asked first, when the host
    names one, and raw.githubusercontent.com after a 404 there. Both can answer
    from a cache for some minutes. Raises Unavailable.

    A host with `data` keeps no storage repository, so its file is read with
    share_file_signed, and a file without a valid signature is None here too.
    """
    if isinstance(table.get("data"), str):
        signed = share_file_signed(table, path, user_agent)
        return signed.text if isinstance(signed, SignedFile) else None
    quoted = urllib.parse.quote(path)
    urls = [RAW_FILE.format(storage=table.get("storage"), path=quoted)]
    if isinstance(table.get("pages"), str):
        urls.insert(0, table["pages"] + quoted)
    for url in urls:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:
                body = answer.read(MAX_SHARE_FILE + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise Unavailable(f"HTTP {error.code} asking for {path} of {table.get('storage')}")
        except OSError as error:
            detail = error.reason if isinstance(error, urllib.error.URLError) else error
            raise Unavailable(f"{table.get('storage')} did not answer about {path}: {detail}") from error
        if len(body) > MAX_SHARE_FILE:
            raise Unavailable(f"{path} of {table.get('storage')} is larger than {MAX_SHARE_FILE // 1024} KiB")
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Unavailable(f"{path} of {table.get('storage')} is not UTF-8 text") from error
    return None


def _data_body(url, limit, user_agent):
    """The body at `url` of a host with `data`, cut after `limit` + 1 bytes, or
    None on a 404. A request to such a host never carries a GitHub token, and
    an answer that ends at a URL other than HTTPS is refused. Raises Unavailable.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            final = answer.url
            body = answer.read(limit + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise Unavailable(f"HTTP {error.code} asking for {url}")
    except OSError as error:
        detail = error.reason if isinstance(error, urllib.error.URLError) else error
        raise Unavailable(f"{url} did not answer: {detail}") from error
    if urllib.parse.urlsplit(str(final)).scheme != "https":
        raise Unavailable(f"{url} answered from {final}, which is not HTTPS")
    return body


def share_file_signed(table, path, user_agent=USER_AGENT):
    """A data file of a host with `data`, as a SignedFile, None when it is not
    there, or UNSIGNED when its .sig is missing or is not a valid signature by
    `key` (RFC 0104, rule 22). `retired_keys` never verify a live read.

    The signature is checked over the exact bytes before they are read as
    text. Raises Unavailable, also when the cryptography package is not
    installed, so that a missing package never becomes a verdict.
    """
    # signature.py imports only binascii, and imports cryptography inside its
    # functions, so a check that reads no host with `data` needs no package.
    import signature

    host_key = table.get("key")
    if not isinstance(host_key, str):
        raise Unavailable(f"the host at {table.get('data')} names no key in hosts.toml")
    try:
        loaded = signature.load_key(host_key)
    except ImportError as error:
        raise Unavailable(
            f"the cryptography package is not installed, so no signature can be checked: {error}"
        ) from error
    except ValueError as error:
        raise Unavailable(f"the key of the host at {table.get('data')} does not load: {error}") from error

    url = table["data"] + urllib.parse.quote(path)
    body = _data_body(url, MAX_SHARE_FILE, user_agent)
    if body is None:
        return None
    if len(body) > MAX_SHARE_FILE:
        raise Unavailable(f"{url} is larger than {MAX_SHARE_FILE // 1024} KiB")
    sig = _data_body(url + SIGNATURE, signature.MAX_SIGNATURE, user_agent)
    if sig is None or not signature.verify(loaded, body, sig):
        return UNSIGNED
    try:
        return SignedFile(body.decode("utf-8"), sig.decode("ascii"), host_key)
    except UnicodeDecodeError as error:
        raise Unavailable(f"{url} is not UTF-8 text") from error


def _json_object(text):
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def touched_listings(changes):
    """The `<type>/<id>` of every vehicle and save a change touches, old paths of renames included."""
    found = set()
    for change in changes:
        for path in (change.path, change.previous_path):
            parts = (path or "").split("/")
            if len(parts) == 2 and parts[0] in SHARE_FOLDERS and parts[1].lower().endswith(".toml"):
                found.add(f"{SHARE_FOLDERS[parts[0]]}/{parts[1][:-len('.toml')]}")
    return found


def _verify_share(share, content_type, listing_id, author_id, api):
    """The two proofs of a share host (RFC 0094): the owner record links the
    GitHub account of the pull request author, or the host's bot opened the pull
    request and the host attested the exact change in its storage repository.
    A host with `data` serves both files signed, and an unsigned one counts for
    nothing (RFC 0104).
    """
    key, table = share.key, share.table
    # The release flow of content-index-releases imports this module with
    # lookups of its own that may have no reader for a share host.
    if isinstance(table.get("data"), str):
        place = table["data"]
        read = getattr(api, "share_file_signed", None) or share_file_signed
    elif isinstance(table.get("storage"), str):
        place = table["storage"]
        read = getattr(api, "share_file", None) or share_file
    else:
        return Result(
            UNVERIFIED,
            f"the share host `{key}` names no storage repository and no data URL, so no owner record can be read",
        )
    if share.id != listing_id:
        return Result(
            UNVERIFIED, f"`{key}` under [releases] names `{share.id}`, and not the id of the listing"
        )

    path = OWNER_RECORD.format(type=content_type, id=listing_id)
    record, failure = _read_share(read, share, path, place)
    if failure is not None:
        return failure
    if record is None:
        return Result(UNVERIFIED, f"the share host `{key}` has no owner record {path} in {place}")
    record = _json_object(record.text if isinstance(record, SignedFile) else record)
    account = (record or {}).get("account")
    if (
        record is None
        or (record.get("id"), record.get("type")) != (listing_id, content_type)
        or not isinstance(account, str)
        or not account
    ):
        return Result(UNVERIFIED, f"{path} in {place} is not the owner record of this {content_type}")

    linked = record.get("github_id")
    if author_id is not None and type(linked) is int and linked == author_id:
        return Result(VERIFIED, "", "linked GitHub account")

    bot = table.get("bot")
    if author_id is None or type(bot) is not int or author_id != bot:
        return Result(
            UNVERIFIED,
            f"the owner record {path} of `{key}` links no GitHub account of the pull request "
            f"author, and the pull request is not from the account of `{key}`",
            instructions=SHARE_HOST_ADVICE,
        )
    return _verify_attestation(share, f"{content_type}/{listing_id}", account, read, place, api)


def _read_share(read, share, path, place):
    """A data file through `read`, as (file, None), or (None, the Result the
    proof ends with when the host does not answer or the file is unsigned).
    The file is text from a storage repository,
    a SignedFile from `data`, or None when the host has no such file.
    """
    try:
        found = read(share.table, path)
    except Unavailable as error:
        return None, Result(COULD_NOT_EVALUATE, str(error))
    if found is UNSIGNED:
        return None, Result(
            UNVERIFIED,
            f"{path} in {place} has no valid signature by key, the signing key that hosts.toml "
            f"names for `{share.key}`",
        )
    return found, None


def _verify_attestation(share, name, account, read, place, api):
    """The attestation of the change of a pull request the host's bot opened."""
    key = share.key
    change = getattr(api, "change", None)
    if change is None:
        return Result(
            UNVERIFIED,
            f"the pull request is from the account of `{key}`, and this check cannot read "
            "the change that the host would have attested",
        )
    try:
        changes = change()
        digest = change_digest(changes)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))
    except ValueError as error:
        return Result(UNVERIFIED, f"the change of the pull request cannot be attested: {error}")

    path = ATTESTATION.format(digest=digest)
    found, failure = _read_share(read, share, path, place)
    if failure is not None:
        return failure
    if found is None:
        return Result(
            UNVERIFIED,
            f"`{key}` attested no change with the digest {digest}: {place} has no {path}, so the "
            "pull request differs from what the host attested, or the attestation is not published yet",
        )
    evidence = None
    if isinstance(found, SignedFile):
        evidence = Evidence(path, found.text, found.signature, found.key)
        found = found.text
    attestation = _json_object(found)
    accounts = (attestation or {}).get("accounts")
    if attestation is None or attestation.get("host") != key or not isinstance(accounts, dict):
        return Result(UNVERIFIED, f"{path} in {place} is not an attestation of `{key}`")

    missing = sorted(listing for listing in touched_listings(changes) if not isinstance(accounts.get(listing), str))
    if missing:
        return Result(
            UNVERIFIED,
            f"the attestation {path} of `{key}` names no account for {', '.join(missing)}, "
            "which the pull request touches",
        )
    if accounts.get(name) != account:
        return Result(
            UNVERIFIED,
            f"the attestation {path} of `{key}` names another account for {name} than its owner record",
        )
    return Result(VERIFIED, "", "attestation", evidence=evidence)


def _verify_spacedock(mod_id, listing_id, login, author_id, api):
    """A SpaceDock mod through its source code link.

    Only the mod's owner, its accepted co-authors and SpaceDock's administrators
    can set that link, and only somebody who controls the repository it names
    can pass a proof there. So the mod's authors decide which repository stands
    for the mod, and whoever controls that repository can list it. A mod
    without a usable link binds to nothing.
    """
    repository, failure = _spacedock_repository(mod_id, api)
    if failure is not None:
        return failure

    result = _verify_repository(
        repository, listing_id, login, author_id, api, named_by="the link on SpaceDock"
    )
    if result.state == VERIFIED:
        return Result(VERIFIED, "", f"source code link, {result.proof}")
    return Result(
        result.state, f"SpaceDock mod {mod_id} links to {repository}, and {result.reason}"
    )


def _spacedock_repository(mod_id, api):
    """The GitHub repository a SpaceDock mod's source code link names, as
    (repository, None), or (None, the Result that says why there is none).
    """
    if not mod_id.isdigit():
        return None, Result(UNVERIFIED, f"'{mod_id}' is not a SpaceDock mod id, which is a number")

    # The release flow of content-index-releases imports this module with
    # lookups of its own that have no SpaceDock reader.
    read = getattr(api, "spacedock_mod", None) or spacedock_mod
    try:
        mod = read(mod_id)
    except Unavailable as error:
        return None, Result(COULD_NOT_EVALUATE, str(error))

    if mod is None:
        return None, Result(UNVERIFIED, f"SpaceDock has no mod {mod_id}")

    if mod.get("error"):
        if "not published" in str(mod.get("reason") or "").lower():
            return None, Result(UNVERIFIED, f"SpaceDock mod {mod_id} is not published")
        return None, Result(UNVERIFIED, f"SpaceDock refuses to show mod {mod_id}")

    if str(mod.get("id")) != mod_id:
        return None, Result(
            COULD_NOT_EVALUATE, f"the answer about SpaceDock mod {mod_id} is not the mod's document"
        )

    if mod.get("game_id") != SPACEDOCK_GAME_ID:
        return None, Result(UNVERIFIED, f"SpaceDock mod {mod_id} is not a Kitten Space Agency mod")

    link = mod.get("source_code")
    if not link:
        return None, Result(
            UNVERIFIED,
            f"SpaceDock mod {mod_id} has no source code link, so nothing binds it to a "
            "GitHub repository",
        )

    repository = github_repository(link)
    if repository is None:
        return None, Result(
            UNVERIFIED,
            f"the source code link of SpaceDock mod {mod_id} does not name a GitHub repository",
        )
    return repository, None


def _read_repository(target, api, named_by):
    """GitHub's answer about `target`, as (repository, None), or (None, the
    Result that says why it cannot stand for the listing).
    """
    try:
        repository = api.repository(target)
    except Unavailable as error:
        return None, Result(COULD_NOT_EVALUATE, str(error))

    if repository is None:
        return None, Result(UNVERIFIED, f"{target} does not exist or is private")

    full_name = repository.get("full_name") or ""
    if full_name.lower() != target.lower():
        return None, Result(
            UNVERIFIED, f"{target} now answers as {full_name}, so {named_by} is stale"
        )
    return repository, None


def _verify_repository(target, listing_id, login, author_id, api, named_by="the listing"):
    """The three proofs on one GitHub repository."""
    repository, failure = _read_repository(target, api, named_by)
    if failure is not None:
        return failure

    # The owner of a fork is the account that forked it, and GitHub copies no
    # topic to a fork, but a fork inherits its parent's marker file (RFC 0079).
    owner_id = (repository.get("owner") or {}).get("id")
    if author_id is not None and owner_id == author_id:
        return Result(VERIFIED, "", "owner id")

    try:
        topics = api.topics(target)
    except Unavailable as error:
        return Result(COULD_NOT_EVALUATE, str(error))
    if TOPIC.format(login=login.lower()) in topics:
        return Result(VERIFIED, "", "topic")

    if repository.get("fork"):
        return Result(
            UNVERIFIED,
            f"{login} did not prove control of the fork {target}: no matching owner and no "
            f"{TOPIC.format(login=login.lower())} topic, and a fork's {MARKER_PATH} does "
            "not count, because a fork inherits its files",
        )

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


def owner_logins(document, api, registry=None):
    """The accounts the proofs above name as the owners of a document's host,
    as (logins, reason). Nothing is stored, so this asks the host every time.

    A personal repository names its owner. An organization repository names
    every `ksa-index-<login>` topic and the login of its marker file, and a fork
    of one names only its topics. A SpaceDock mod names the owners of the
    repository its source code link names. No login comes with the reason, and
    a host that does not answer is such a reason, never an exception.
    """
    listing_id = document.get("id") or ""
    kind, target, reason = authority(document, registry)
    named_by = "the listing"
    if kind == SHARE_KIND:
        return (), f"the share host `{target.key}` names its owners by its own accounts"
    if kind == "spacedock":
        target, failure = _spacedock_repository(target, api)
        if failure is not None:
            return (), failure.reason
        kind, named_by = "github", "the link on SpaceDock"
    if kind != "github":
        return (), reason

    repository, failure = _read_repository(target, api, named_by)
    if failure is not None:
        return (), failure.reason

    owner = repository.get("owner") or {}
    if owner.get("type") == "User":
        login = owner.get("login")
        if isinstance(login, str) and LOGIN.fullmatch(login):
            return (login,), ""
        return (), f"GitHub names no owner of {target}"

    try:
        topics = api.topics(target)
    except Unavailable as error:
        return (), str(error)
    prefix = TOPIC.format(login="")
    logins = [topic[len(prefix):] for topic in topics if topic.startswith(prefix)]

    if not repository.get("fork"):
        try:
            marker = api.file(target, MARKER_PATH)
        except Unavailable as error:
            marker = None
            if not logins:
                return (), str(error)
        if marker is not None:
            claimed = _marker_login(marker, listing_id)
            if claimed is not None:
                logins.append(claimed)

    found = {}
    for login in logins:
        if LOGIN.fullmatch(login):
            found.setdefault(login.lower(), login)
    if found:
        return tuple(found[key] for key in sorted(found)), ""
    # The reason reaches a GitHub comment, which hides a bare <login> as an HTML
    # tag, so the placeholder and the path stay in code spans.
    topic = TOPIC.format(login="<login>")
    if repository.get("fork"):
        return (), f"no `{topic}` topic on the fork {target} names an owner"
    return (), f"no `{topic}` topic and no `{MARKER_PATH}` on {target} names an owner"


def _bound(document, registry=None):
    """The host a document binds ownership to, folded for comparison."""
    kind, target, _ = authority(document, registry)
    if kind == SHARE_KIND:
        return kind, (target.key.lower(), target.id.lower())
    return (
        kind.lower() if isinstance(kind, str) else kind,
        target.lower() if isinstance(target, str) else target,
    )


def same_authority(left, right, registry=None):
    """Whether two documents bind ownership to the same release host.

    Binding to nothing counts as the same: neither moves the authority.
    """
    return _bound(left, registry) == _bound(right, registry)


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
    if repository is None:
        return False

    return (repository.get("full_name") or "").lower() == target.lower()


def _about(result, where):
    """Say which authority a verdict is about. A pass needs no explanation."""
    if result.state == VERIFIED:
        return result
    return Result(result.state, f"{where}: {result.reason}", result.proof, result.instructions, result.evidence)


def verify_change(base, submitted, login, author_id, api, registry=None):
    """Ownership for one changed document.

    An edit is verified against the authority the base version names, because
    the submitted one is written by whoever opened the pull request. Pointing
    the listing at a different host verifies against both. A rename is not a
    different host. A new listing has no base and declares its own.
    """
    if registry is None:
        registry = share_hosts()
    if base is None:
        return verify(submitted, login, author_id, api, registry)

    current = verify(base, login, author_id, api, registry)
    if same_authority(base, submitted, registry):
        return current

    if current.state != VERIFIED:
        try:
            renamed = renamed_into(base, submitted, api)
        except Unavailable as error:
            return _about(Result(COULD_NOT_EVALUATE, str(error)), CURRENT_HOST)
        if renamed:
            return _about(verify(submitted, login, author_id, api, registry), RENAMED_HOST)
        return _about(current, CURRENT_HOST)

    moved = verify(submitted, login, author_id, api, registry)
    if moved.state != VERIFIED:
        return _about(moved, NEW_HOST)

    # An attestation passes only for a pull request from the host's own bot, so
    # at most one of the two passes by an attestation while no two hosts share
    # a bot (spec/share-host.md, rule 4).
    return Result(
        VERIFIED, "", f"{current.proof}, then {moved.proof}", evidence=current.evidence or moved.evidence
    )
