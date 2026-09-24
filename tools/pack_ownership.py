#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate and apply the recorded owner of a mod pack."""

import json
import re
from pathlib import PurePosixPath

import ownership

OWNER_FILE = "owner.json"
PROOF = "pack owner record"
OWNER_KEYS = {"github_login", "github_id"}
LOGIN = re.compile(r"^(?!.*--)[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


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
    if not isinstance(login, str) or not LOGIN.fullmatch(login):
        return None, f"{where}: github_login is not a valid GitHub login"
    if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id < 1:
        return None, f"{where}: github_id must be a positive integer"
    return record, ""


def _read(api, path, ref):
    try:
        text = api.file(api.repository, path, ref=ref)
    except ownership.Unavailable as error:
        return None, str(error)
    if text is None:
        return None, ""
    return parse_record(text, path)


def verify(api, pull, document_path, head_sha):
    """Verify a pack version against the owner recorded on the base branch.

    Only when the base branch records no owner is the pack id free, and then the
    submitted owner record claims it for the account that opened the pull
    request, first come, first served. After that, only the base branch counts.
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
