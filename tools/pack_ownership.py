#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate and apply the recorded owner of a mod pack."""

import json
import re
from pathlib import PurePosixPath

import check_scope
import ownership

OWNER_FILE = "owner.json"
PROOF = "pack owner record"
OWNER_KEYS = {"github_login", "github_id"}
# An owner record path that is safe to put into a URL and into Markdown.
OWNER_RECORD = re.compile(r"packs/[A-Za-z0-9._-]+/owner\.json")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate field '{key}'")
        result[key] = value
    return result


def owner_path(document_path):
    """The owner record beside one pack version document."""
    path = PurePosixPath(document_path)
    return (path.parent / OWNER_FILE).as_posix()


def parse_record(text, where):
    """Return a validated owner record and its error."""
    try:
        record = json.loads(text, object_pairs_hook=_unique_object)
    except (TypeError, ValueError) as error:
        return None, f"{where}: the pack owner record is not valid JSON: {error}"
    if not isinstance(record, dict):
        return None, f"{where}: the pack owner record must be an object"
    unknown = sorted(set(record) - OWNER_KEYS)
    missing = sorted(OWNER_KEYS - set(record))
    if unknown:
        return None, f"{where}: unknown pack owner field: {', '.join(unknown)}"
    if missing:
        return None, f"{where}: missing pack owner field: {', '.join(missing)}"

    login = record["github_login"]
    account_id = record["github_id"]
    if not isinstance(login, str) or not ownership.LOGIN.fullmatch(login):
        return None, f"{where}: github_login is not a valid GitHub login"
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id < 1:
        return None, f"{where}: github_id must be a positive integer"
    return record, ""


def record_text(login, account_id):
    """An owner record written as the files in packs/ are."""
    return json.dumps({"github_login": login, "github_id": account_id}, indent=2) + "\n"


def held_ids(api, ref):
    """The ids that the pack folders and listing files on `ref` hold, folded as
    check_index compares them."""
    held = set()
    for name, kind in api.folder("packs", ref):
        if kind == "dir":
            held.add(name.casefold())
    for name, kind in api.folder("listings", ref):
        if kind == "file" and name.lower().endswith(".toml"):
            held.add(name[: -len(".toml")].casefold())
    return held


def missing_records(api, pull, changes):
    """The owner records that the first pack claims of a change still lack.

    A pack counts when the change adds a version of it, the change has no
    record for it, and no pack or listing on the base branch holds its id in
    any case. Only a plain path counts, because the path comes from the pull
    request. A base branch that cannot be read holds every id, so nobody is
    asked for a file that may be there.
    """
    base_ref = (pull.get("base") or {}).get("ref") or ""
    submitted = {change.path for change in changes if change.status in check_scope.WRITING}
    wanted = []
    for change in changes:
        if change.status != "added" or check_scope.kind_of(change.path) != check_scope.PACK_KIND:
            continue
        path = owner_path(change.path)
        if OWNER_RECORD.fullmatch(path) and path not in submitted and path not in wanted:
            wanted.append(path)
    if not wanted or not base_ref:
        return []
    try:
        held = held_ids(api, base_ref)
    except ownership.Unavailable:
        return []
    return [path for path in wanted if PurePosixPath(path).parent.name.casefold() not in held]


def _read(api, path, ref):
    try:
        text = api.file(api.repository, path, ref=ref)
    except ownership.Unavailable as error:
        return None, str(error)
    if text is None:
        return None, ""
    return parse_record(text, path)


def owner_record(api, pack_id, ref):
    """The accepted owner record of a pack on `ref`, as (record, reason).

    A pack without a record has no owner yet, which is not a failure, so both
    are None. A record that cannot be read comes with the reason.
    """
    path = f"packs/{pack_id}/{OWNER_FILE}"
    if not OWNER_RECORD.fullmatch(path):
        return None, "the pack id is not one a path can carry"
    record, problem = _read(api, path, ref)
    return record, problem or None


def verify(api, pull, document_path, head_sha):
    """Verify a pack version against the owner recorded on the base branch.

    A pack version is a first claim only when no pack or listing on the base
    branch holds its id in any case. Then the submitted owner record claims the
    id for the account that opened the pull request, first come, first served.
    After that, only the record on the base branch counts.
    """
    base_ref = (pull.get("base") or {}).get("ref") or ""
    if not base_ref:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            "the pull request names no base branch, so pack ownership could not be read",
        )

    try:
        accepted = api.file(api.repository, document_path, ref=base_ref)
    except ownership.Unavailable as error:
        return ownership.Result(ownership.COULD_NOT_EVALUATE, str(error))
    if accepted is not None:
        return ownership.Result(
            ownership.REJECTED,
            f"{document_path} already exists on {base_ref}; an accepted pack version is immutable",
        )

    path = owner_path(document_path)
    record, problem = _read(api, path, base_ref)
    if problem:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            f"the pack owner on {base_ref} could not be read: {problem}",
        )

    login = (pull.get("user") or {}).get("login") or ""
    account_id = (pull.get("user") or {}).get("id")
    if record is not None:
        if record["github_id"] == account_id:
            return ownership.Result(ownership.VERIFIED, "", PROOF)
        return ownership.Result(
            ownership.UNVERIFIED,
            f"{login} is not the recorded owner of this pack",
            instructions="A steward decides whether the recorded pack owner must change.",
        )

    pack_id = PurePosixPath(document_path).parent.name
    try:
        held = held_ids(api, base_ref)
    except ownership.Unavailable as error:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            f"whether the pack id is free on {base_ref} could not be read: {error}",
        )
    if pack_id.casefold() in held:
        return ownership.Result(
            ownership.UNVERIFIED,
            f"the id '{pack_id}' is already held on {base_ref}, and no owner record "
            "there names the account that may add a version",
            instructions="A steward decides who holds the pack id.",
        )

    submitted, problem = _read(api, path, head_sha)
    if problem:
        return ownership.Result(ownership.REJECTED, problem)
    if submitted is None:
        return ownership.Result(
            ownership.REJECTED,
            f"a first pack claim must add {path}",
        )
    if submitted["github_id"] != account_id or submitted["github_login"].lower() != login.lower():
        return ownership.Result(
            ownership.REJECTED,
            f"{path} must name the account that opened the pull request",
        )
    return ownership.Result(ownership.VERIFIED, "", PROOF)
