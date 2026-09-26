#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Act on a validation verdict: the commit status, auto-merge, and the steward queue.

The privileged half of RFC 0033's listing flow.
"""

import argparse
import base64
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_scope
import ownership
import pack_ownership

GITHUB_API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
USER_AGENT = ownership.USER_AGENT

# The required check in the branch ruleset. No job may carry this name.
STATUS_CONTEXT = "validate"
STEWARD_LABEL = "needs-steward"
STEWARD_TEAM = "content-manager-stewards"

# The labels this workflow writes, each with the colour and the description a
# missing one is created from.
LABELS = {
    STEWARD_LABEL: ("d93f0b", "waiting on a steward"),
    check_scope.LISTING_KIND: ("0e8a16", "changes a listing document"),
    check_scope.PACK_KIND: ("0e8a16", "changes a pack document"),
}

# One label per kind of document, so the queue separates a submission from a
# change to the checks that gate it.
DOCUMENT_LABELS = tuple(kind for kind, _ in check_scope.KINDS)

COMMENT_MARKER = "<!-- content-index:verdict -->"

PULL_REQUEST_EVENT = "pull_request"

STATUS_FILE = "index-status.toml"
# A listing path that is safe to put into a URL and into Markdown.
PLAIN_LISTING = re.compile(r"listings/[A-Za-z0-9._-]+\.toml")

PASS = "pass"
REJECT = "reject"
COULD_NOT_EVALUATE = "could-not-evaluate"


class Decision:
    def __init__(self, status, description, auto_merge=False, needs_steward=False, comment=None):
        self.status = status
        self.description = description
        self.auto_merge = auto_merge
        self.needs_steward = needs_steward
        self.comment = comment


def _messages(verdict):
    lines = []
    for check in verdict.get("checks") or []:
        for message in check.get("messages") or []:
            lines.append(f"- `{check.get('name')}`: {message}")
    return lines


def _comment(first, verdict, paragraphs=(), run_url="", rerun=False):
    sections = [first]
    messages = _messages(verdict)
    if messages:
        sections.append("Notes:\n" + "\n".join(messages))
    sections.extend(paragraphs)
    if rerun:
        sections.append("Push a fix and the checks run again.")
    if run_url:
        sections.append(f"[The validation run]({run_url})")
    return "\n\n".join(sections)


def decide(verdict, candidate, ownership_result, run_url="", advice=()):
    """The status reports validation alone. Ownership is a separate axis, so a
    listing that validates but cannot prove it is green and waits for a steward.

    `advice` goes into the comment whatever the outcome.
    """
    outcome = verdict.get("verdict")

    def comment(first, paragraphs=(), rerun=False):
        return _comment(first, verdict, [*paragraphs, *advice], run_url, rerun)

    if outcome == REJECT:
        return Decision(
            "failure",
            "the validation rejected this change",
            comment=comment("The validation rejected this change.", rerun=True),
        )

    if outcome != PASS:
        return Decision(
            "error",
            "the validation could not reach a verdict",
            comment=comment(
                "The validation could not reach a verdict, so nothing is decided yet.", rerun=True
            ),
        )

    if ownership_result.state == ownership.REJECTED:
        return Decision(
            "failure",
            "the pack ownership check rejected this change",
            comment=comment(
                "The pack ownership check rejected this change.",
                [_sentence(ownership_result.reason)],
                rerun=True,
            ),
        )

    if not candidate:
        reason = verdict.get("scope_reason") or "the change is outside what merges itself"
        return Decision(
            "success",
            "validated, and a steward decides",
            needs_steward=True,
            comment=comment("Validated.", [f"A steward has to merge this one, because {reason}."]),
        )

    if ownership_result.state == ownership.VERIFIED:
        if ownership_result.proof == pack_ownership.PROOF:
            next_step = "This pull request merges on its own once the checks finish. The snapshot follows."
        else:
            next_step = (
                "This pull request merges on its own once the checks finish. The watcher "
                "stamps the first release within about ten minutes after the merge, and the "
                "snapshot follows."
            )
        return Decision(
            "success",
            "validated, arming auto-merge",
            auto_merge=True,
            comment=comment("Validated.", [next_step]),
        )

    if ownership_result.state == ownership.COULD_NOT_EVALUATE:
        return Decision(
            "success",
            "validated, ownership could not be checked",
            needs_steward=True,
            comment=comment(
                "Validated.",
                [
                    "The ownership check reached no verdict, so this waits for a steward.",
                    _sentence(ownership_result.reason),
                ],
            ),
        )

    instructions = ownership_result.instructions or ownership.ADVICE
    return Decision(
        "success",
        "validated, ownership not verified",
        needs_steward=True,
        comment=comment(
            "Validated, and ownership is not verified, so a steward decides.",
            [_sentence(ownership_result.reason), instructions],
        ),
    )


class Api:
    """The REST and GraphQL calls this workflow makes."""

    def __init__(self, repository, token, public_token=None, dry_run=False, log=print):
        self.repository = repository
        # Scoped to the installed repositories, so a release host needs the other.
        self.token = token
        self.public_token = public_token or token
        self.dry_run = dry_run
        self.log = log

    def _call(self, url, token, method="GET", payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as answer:
            text = answer.read()
            return json.loads(text) if text else {}

    def get(self, path, **query):
        url = f"{GITHUB_API}/repos/{self.repository}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            return self._call(url, self.token)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def send(self, method, path, payload, token=None):
        if self.dry_run:
            self.log(f"dry run: {method} {path} {json.dumps(payload)[:200]}")
            return {}
        return self._call(
            f"{GITHUB_API}/repos/{self.repository}{path}", token or self.token, method, payload
        )

    def _other(self, path, **query):
        """Any repository. Every failure becomes Unavailable, never a rejection."""
        url = f"{GITHUB_API}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            return self._call(url, self.public_token)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise ownership.Unavailable(f"HTTP {error.code} asking for {path}")
        except (OSError, json.JSONDecodeError) as error:
            raise ownership.Unavailable(str(error)) from error

    def repository_of(self, full_name):
        return self._other(f"/repos/{full_name}")

    def topics(self, full_name):
        answer = self._other(f"/repos/{full_name}/topics")
        return list((answer or {}).get("names") or [])

    def file(self, full_name, path, ref=None):
        query = {"ref": ref} if ref else {}
        answer = self._other(f"/repos/{full_name}/contents/{path}", **query)
        if not isinstance(answer, dict):
            return None
        if answer.get("encoding") != "base64":
            raise ownership.Unavailable(f"{path} is too large to read inline")
        try:
            return base64.b64decode(answer.get("content") or "").decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    def folder(self, path, ref):
        """The (name, type) entries of a folder of this repository on `ref`.

        A folder that is not there has none. The contents API lists at most
        1000 entries, so a longer listing is Unavailable, never cut short.
        """
        answer = self._other(f"/repos/{self.repository}/contents/{path}", ref=ref)
        if answer is None:
            return []
        if not isinstance(answer, list):
            raise ownership.Unavailable(f"{path} on {ref} is not a folder")
        if len(answer) >= 1000:
            raise ownership.Unavailable(f"{path} on {ref} has too many entries to list")
        return [
            (entry.get("name") or "", entry.get("type") or "")
            for entry in answer
            if isinstance(entry, dict)
        ]

    def spacedock_mod(self, mod_id):
        return ownership.spacedock_mod(mod_id, USER_AGENT)

    def merge_base(self, base_ref, head_sha):
        """The commit that the diff of a pull request and its merge start from."""
        base = urllib.parse.quote(base_ref, safe="/")
        answer = self._other(f"/repos/{self.repository}/compare/{base}...{head_sha}", per_page=1)
        sha = ((answer or {}).get("merge_base_commit") or {}).get("sha")
        if not isinstance(sha, str) or not sha:
            raise ownership.Unavailable(f"GitHub names no merge base of {base_ref} and {head_sha[:7]}")
        return sha

    def graphql(self, query, variables):
        if self.dry_run:
            self.log(f"dry run: graphql {json.dumps(variables)}")
            return {}
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        headers = {
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(GRAPHQL, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=30) as answer:
            return json.loads(answer.read())


class OwnershipApi:
    """`ownership.verify` talks to the target repository through this."""

    def __init__(self, api):
        self.api = api

    def repository(self, full_name):
        return self.api.repository_of(full_name)

    def topics(self, full_name):
        return self.api.topics(full_name)

    def file(self, full_name, path):
        return self.api.file(full_name, path)

    def spacedock_mod(self, mod_id):
        return self.api.spacedock_mod(mod_id)


AUTO_MERGE = """
mutation($id: ID!) {
  enablePullRequestAutoMerge(input: {pullRequestId: $id, mergeMethod: SQUASH}) {
    clientMutationId
  }
}
"""


def post_status(api, sha, decision, run_url):
    api.send(
        "POST",
        f"/statuses/{sha}",
        {
            "state": decision.status,
            "context": STATUS_CONTEXT,
            "description": decision.description[:140],
            "target_url": run_url,
        },
        token=api.public_token,  # the Actions app, which the ruleset entry names
    )


def upsert_comment(api, number, body):
    """One comment per pull request, edited in place, never a second one."""
    existing = None
    for comment in api.get(f"/issues/{number}/comments", per_page=100) or []:
        if COMMENT_MARKER in (comment.get("body") or ""):
            existing = comment
            break

    if body is None:
        if existing is not None:
            api.send(
                "PATCH",
                f"/issues/comments/{existing['id']}",
                {"body": f"{COMMENT_MARKER}\nValidated and ownership verified."},
            )
        return

    payload = {"body": f"{COMMENT_MARKER}\n{body}"}
    if existing is None:
        api.send("POST", f"/issues/{number}/comments", payload)
    elif (existing.get("body") or "") != payload["body"]:
        api.send("PATCH", f"/issues/comments/{existing['id']}", payload)


def _labels(api, number):
    return {label.get("name") for label in api.get(f"/issues/{number}/labels") or []}


def _put_label(api, number, name):
    """Put one label on, and create it first when the repository has none."""
    try:
        api.send("POST", f"/issues/{number}/labels", {"labels": [name]})
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        colour, description = LABELS[name]
        api.send("POST", "/labels", {"name": name, "color": colour, "description": description})
        api.send("POST", f"/issues/{number}/labels", {"labels": [name]})


def add_steward_label(api, number):
    if STEWARD_LABEL in _labels(api, number):
        return
    _put_label(api, number, STEWARD_LABEL)


def remove_steward_label(api, number):
    """Only on the way to a merge, so a steward's own labelling survives a reject."""
    if STEWARD_LABEL in _labels(api, number):
        api.send("DELETE", f"/issues/{number}/labels/{STEWARD_LABEL}", None)


def sync_document_labels(api, number, wanted):
    """Say which kinds of document the pull request touches.

    The kind is a fact about the diff and not about the verdict, so a listing
    that a steward has to merge still reads as a listing. Both directions are
    kept, because a pull request can stop touching a document, and no label
    outside DOCUMENT_LABELS is looked at.
    """
    present = _labels(api, number)
    for name in DOCUMENT_LABELS:
        if name in wanted and name not in present:
            _put_label(api, number, name)
        elif name not in wanted and name in present:
            api.send("DELETE", f"/issues/{number}/labels/{name}", None)


def _requested(api, number):
    requested = api.get(f"/pulls/{number}/requested_reviewers") or {}
    return any(team.get("slug") == STEWARD_TEAM for team in requested.get("teams") or [])


def request_stewards(api, number):
    if _requested(api, number):
        return
    try:
        api.send("POST", f"/pulls/{number}/requested_reviewers", {"team_reviewers": [STEWARD_TEAM]})
    except urllib.error.HTTPError as error:
        api.log(f"could not request the stewards team: HTTP {error.code}")


def withdraw_stewards(api, number):
    """A standing request would hold up the merge this run just armed."""
    if not _requested(api, number):
        return
    try:
        api.send(
            "DELETE", f"/pulls/{number}/requested_reviewers", {"team_reviewers": [STEWARD_TEAM]}
        )
    except urllib.error.HTTPError as error:
        api.log(f"could not withdraw the stewards team: HTTP {error.code}")


def arm_auto_merge(api, node_id):
    """Whether auto-merge is armed. False sends the pull request to a steward."""
    try:
        answer = api.graphql(AUTO_MERGE, {"id": node_id})
    except (urllib.error.HTTPError, OSError, json.JSONDecodeError) as error:
        api.log(f"auto-merge not armed: {error}")
        return False
    errors = answer.get("errors") or []
    for error in errors:
        api.log(f"auto-merge not armed: {error.get('message')}")
    return not errors


def pull_request_for(api, event, head_repository, head_branch, head_sha):
    """The open pull request a workflow_run event belongs to, or None.

    Only a `pull_request` run belongs to one.
    """
    if event != PULL_REQUEST_EVENT:
        return None

    owner = head_repository.split("/")[0]
    for pull in api.get("/pulls", state="open", head=f"{owner}:{head_branch}") or []:
        head = pull.get("head") or {}
        if head.get("sha") != head_sha:
            continue
        if ((head.get("repo") or {}).get("full_name") or "") != head_repository:
            continue
        return pull
    return None


def changed_paths(api, number):
    changes = []
    page = 1
    while True:
        batch = api.get(f"/pulls/{number}/files", per_page=100, page=page) or []
        for entry in batch:
            changes.append(
                check_scope.Change(
                    entry["filename"],
                    entry.get("status") or "modified",
                    entry.get("previous_filename"),
                )
            )
        if len(batch) < 100:
            return changes
        page += 1


def authored_document(api, path, ref):
    """One authored document at `ref`, and what stopped the read.

    (None, None) means the path is not there, which is a fact, not a failure.
    """
    try:
        text = api.file(api.repository, path, ref=ref)
    except ownership.Unavailable as error:
        return None, str(error)
    if text is None:
        return None, None
    try:
        return tomllib.loads(text), ""
    except tomllib.TOMLDecodeError as error:
        return None, f"{path} does not parse at {ref}: {error}"


def ownership_for_all(api, pull, paths, head_sha):
    """One result for every document of the change.

    Auto-merge needs every document verified. The worst state decides, in the
    order REJECTED, COULD_NOT_EVALUATE, UNVERIFIED, VERIFIED: a rejection is
    about the change itself, and an unverified document only waits for a
    steward. The reason names every document that is not verified, so an
    author fixes them all in one round and not one per push.
    """
    results = [(path, ownership_for(api, pull, path, head_sha)) for path in paths]
    if not results:
        return ownership.Result(ownership.UNVERIFIED, "not checked")

    order = [ownership.REJECTED, ownership.COULD_NOT_EVALUATE, ownership.UNVERIFIED, ownership.VERIFIED]
    _, worst = min(results, key=lambda entry: order.index(entry[1].state))
    if worst.state == ownership.VERIFIED:
        # Only a change of packs alone keeps the pack wording, because a listing
        # in it is stamped by the watcher.
        proof = pack_ownership.PROOF if all(
            result.proof == pack_ownership.PROOF for _, result in results
        ) else None
        return ownership.Result(ownership.VERIFIED, worst.reason, proof)

    if len(results) == 1:
        return worst

    failed = [
        _named(path, result.reason)
        for path, result in results
        if result.state != ownership.VERIFIED
    ]
    reason = failed[0] if len(failed) == 1 else "\n".join(f"- {line}" for line in failed)
    return ownership.Result(worst.state, reason, worst.proof, worst.instructions)


def new_file_url(repository, branch, path, text):
    """GitHub's page that commits a new file to `branch`, with the content filled in."""
    return (
        f"https://github.com/{repository}/new/{urllib.parse.quote(branch, safe='/')}"
        f"?filename={urllib.parse.quote(path, safe='/')}&value={urllib.parse.quote(text, safe='')}"
    )


def owner_advice(pull, paths):
    """The owner records a first pack claim lacks, each as a comment paragraph
    with its content and a link that adds it to the head branch. A commit there
    runs the checks again. A head repository that is gone gets no link.
    """
    user = pull.get("user") or {}
    text = pack_ownership.record_text(user.get("login"), user.get("id"))
    _, problem = pack_ownership.parse_record(text, "the pull request author")
    if problem:
        return []

    head = pull.get("head") or {}
    repository = (head.get("repo") or {}).get("full_name") or ""
    branch = head.get("ref") or ""
    owner, _, name = repository.partition("/")
    reachable = bool(branch) and all(ownership.GITHUB_NAME.match(part) for part in (owner, name))

    paragraphs = []
    for path in paths:
        # The path comes from the pull request, so only a plain one goes into Markdown.
        if not pack_ownership.OWNER_RECORD.fullmatch(path):
            continue
        lines = [
            f"A first pack claim also adds `{path}`, naming the account that opened this "
            "pull request:",
            "",
            "```json",
            text.rstrip("\n"),
            "```",
            "",
        ]
        if reachable:
            lines.append(
                f"[Add {path} to this pull request]({new_file_url(repository, branch, path, text)}). "
                "GitHub opens the new file on the branch of this pull request with this content, "
                "and a commit there runs the checks again. If the file opens empty, paste the "
                "content above."
            )
        else:
            lines.append(
                "The head repository of this pull request cannot be reached, so there is no "
                "link. Add the file with this content next to the pack version."
            )
        paragraphs.append("\n".join(lines))
    return paragraphs


def _states(text):
    """The (state, version) pairs of every id in an index-status.toml text,
    keyed casefolded, or None when the text does not parse.
    """
    try:
        document = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError:
        return None
    entries = document.get("entries")
    states = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        version = entry.get("version")
        pair = (str(entry.get("state")), version if isinstance(version, str) else None)
        states.setdefault(entry["id"].casefold(), set()).add(pair)
    return states


def status_subjects(api, base_ref, head_sha):
    """The listings and packs on `base_ref` whose index state the change sets,
    lifts or changes, as (kind, name) pairs in the base branch's spelling, and
    what stopped the read. A file that does not parse names nothing, because
    the validation rejects it.

    The states are compared with the merge base, as the diff and the merge are,
    so a state that another pull request changed on the base branch after this
    one was cut is not counted as a change of this one.
    """
    try:
        merge_base = api.merge_base(base_ref, head_sha)
        base = _states(api.file(api.repository, STATUS_FILE, ref=merge_base))
        head = _states(api.file(api.repository, STATUS_FILE, ref=head_sha))
        listings = {
            name[: -len(".toml")].casefold(): name
            for name, kind in api.folder("listings", base_ref)
            if kind == "file" and name.lower().endswith(".toml")
        }
        packs = {name.casefold(): name for name, kind in api.folder("packs", base_ref) if kind == "dir"}
    except ownership.Unavailable as error:
        return [], str(error)
    if base is None or head is None:
        return [], ""

    subjects = []
    for folded in sorted(set(base) | set(head)):
        if base.get(folded, set()) == head.get(folded, set()):
            continue
        if folded in listings:
            subjects.append((check_scope.LISTING_KIND, f"listings/{listings[folded]}"))
        elif folded in packs:
            subjects.append((check_scope.PACK_KIND, packs[folded]))
    return subjects, ""


def _mention(logins):
    names = " ".join(f"@{login}" for login in logins)
    return f"{names} {'owns' if len(logins) == 1 else 'own'}"


def owner_notes(api, pull, changes, head_sha):
    """Tell the owners of what the change touches, when somebody else opened it.

    A listing's owner is who its host proves on the base branch, a pack's is
    its accepted owner record, and a state in index-status.toml tells the owner
    of the listing or pack it names. A new listing or a first pack claim has no
    owner yet. Only a plain path is looked up, because the path comes from the
    pull request, and a failed lookup is said and never stops the run.
    """
    base_ref = (pull.get("base") or {}).get("ref") or ""
    if not base_ref:
        return []
    user = pull.get("user") or {}
    author = (user.get("login") or "").lower()

    changed = "which this pull request changes"
    subjects = []
    for change in changes:
        path = change.previous_path or change.path
        parts = path.split("/")
        if check_scope.kind_of(path) == check_scope.LISTING_KIND:
            subjects.append((check_scope.LISTING_KIND, path, changed))
        elif len(parts) == 3 and parts[0] == "packs":
            subjects.append((check_scope.PACK_KIND, parts[1], changed))
    lines = []
    if any(change.path == STATUS_FILE for change in changes):
        named, problem = status_subjects(api, base_ref, head_sha)
        state = f"whose state in `{STATUS_FILE}` this pull request changes"
        subjects.extend((kind, name, state) for kind, name in named)
        if problem:
            lines.append(
                f"- Nobody is told about the states in `{STATUS_FILE}`, because they could "
                f"not be read: {problem}."
            )

    for kind, name, what in dict.fromkeys(subjects):
        if kind == check_scope.PACK_KIND:
            if not pack_ownership.OWNER_RECORD.fullmatch(f"packs/{name}/{pack_ownership.OWNER_FILE}"):
                continue
            record, reason = pack_ownership.owner_record(api, name, base_ref)
            if record is None and reason is None:
                continue
            if record is not None and record["github_id"] == user.get("id"):
                continue
            subject = f"the pack `packs/{name}`"
            logins = () if record is None else (record["github_login"],)
        else:
            if not PLAIN_LISTING.fullmatch(name):
                continue
            document, reason = authored_document(api, name, base_ref)
            if document is None and reason is None:
                continue
            subject = f"`{name}`"
            logins = ()
            if document is not None:
                logins, reason = ownership.owner_logins(document, OwnershipApi(api))

        if any(login.lower() == author for login in logins):
            continue
        if logins:
            lines.append(f"- {_mention(logins)} {subject}, {what}.")
        else:
            lines.append(
                f"- Nobody is told about {subject}, because no owner could be named: {reason}."
            )

    if not lines:
        return []
    return ["Owners of what this pull request changes:\n" + "\n".join(lines)]


def _named(path, reason):
    """The reason with the document it belongs to, unless it already names it first."""
    return reason if reason.startswith(path) else f"{path}: {reason}"


def _sentence(text):
    """The text ending as a sentence, and a list of reasons left as it is."""
    return text if "\n" in text or text.endswith(".") else f"{text}."


def ownership_for(api, pull, path, head_sha):
    """Verify the pull request author against the document it touches.

    Whether the listing exists is read from the base branch, not from the
    reported file status, which is computed against the merge base. Reading the
    branch tip and not the commit the pull request was cut from keeps a stale
    pull request from verifying against a previous owner.
    """
    if check_scope.kind_of(path) == check_scope.PACK_KIND:
        return pack_ownership.verify(api, pull, path, head_sha)

    submitted, problem = authored_document(api, path, head_sha)
    if submitted is None:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            problem or f"{path} is not there at {head_sha[:7]}",
        )

    base_ref = (pull.get("base") or {}).get("ref") or ""
    if not base_ref:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            "the pull request names no base branch, so the listing it edits "
            "could not be read",
        )

    base, problem = authored_document(api, path, base_ref)
    if base is None and problem is not None:
        return ownership.Result(
            ownership.COULD_NOT_EVALUATE,
            f"the listing on {base_ref} could not be read: {problem}",
        )

    return ownership.verify_change(
        base,
        submitted,
        (pull.get("user") or {}).get("login") or "",
        (pull.get("user") or {}).get("id"),
        OwnershipApi(api),
    )


def read_verdict(path):
    """The verdict, or None when the run left none."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except FileNotFoundError:
        return None, "the validation run left no verdict"
    except (OSError, json.JSONDecodeError) as error:
        return None, f"the verdict could not be read: {error}"


def _agrees(verdict, number, sha):
    """The verdict comes from code a pull request can change, so a mismatch is
    not acted on. The head commit is optional only for the unprivileged
    fallback, which cannot know it and never passes.
    """
    if verdict.get("pull_request") != number:
        return False, f"the verdict names pull request {verdict.get('pull_request')}"
    stated = verdict.get("head_sha")
    if stated is not None and stated != sha:
        return False, "the verdict names a different head commit"
    if stated is None and verdict.get("verdict") == PASS:
        return False, "the verdict passes but names no head commit"
    return True, ""


def parse_arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--head-sha", required=True, help="from the workflow_run event")
    parser.add_argument("--event", required=True, help="from the workflow_run event")
    parser.add_argument("--head-repository", required=True, help="from the workflow_run event")
    parser.add_argument("--head-branch", required=True, help="from the workflow_run event")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    arguments = parse_arguments(argv)

    api = Api(
        arguments.repository,
        os.environ.get("APP_TOKEN") or os.environ.get("GITHUB_TOKEN"),
        public_token=os.environ.get("GITHUB_TOKEN"),
        dry_run=arguments.dry_run,
    )

    try:
        return act(api, arguments)
    except Exception as error:
        print(f"acting on the verdict failed: {error!r}", file=sys.stderr)
        try:
            post_status(
                api,
                arguments.head_sha,
                Decision("error", "the ownership workflow failed"),
                arguments.run_url,
            )
        except Exception as second:
            print(f"and the status could not be posted: {second!r}", file=sys.stderr)
        return 1


def act(api, arguments):
    verdict, verdict_error = read_verdict(arguments.verdict)

    pull = pull_request_for(
        api,
        arguments.event,
        arguments.head_repository,
        arguments.head_branch,
        arguments.head_sha,
    )
    if pull is None:
        print(
            f"no open pull request for a {arguments.event} run on "
            f"{arguments.head_repository}:{arguments.head_branch} at {arguments.head_sha}",
            file=sys.stderr,
        )
        return 0
    number = pull["number"]

    if verdict is None:
        verdict = {
            "verdict": COULD_NOT_EVALUATE,
            "checks": [{"name": "validate", "outcome": COULD_NOT_EVALUATE,
                        "messages": [verdict_error]}],
        }
    else:
        agrees, reason = _agrees(verdict, number, arguments.head_sha)
        if not agrees:
            print(f"{reason}, so it is not acted on", file=sys.stderr)
            return 1

    # Re-derived from the API: the verdict cannot be trusted to decide a merge.
    changes = changed_paths(api, number)
    candidate, documents, reason = check_scope.evaluate(changes)

    result = ownership.Result(ownership.UNVERIFIED, "not checked")
    # A pack version is immutable, so its ownership check runs even when a
    # steward decides the change anyway: it is what rejects an edit of one.
    packs = [path for path in documents if check_scope.kind_of(path) == check_scope.PACK_KIND]
    checked = documents if candidate else packs
    if checked and verdict.get("verdict") == PASS:
        result = ownership_for_all(api, pull, checked, arguments.head_sha)

    advice = [
        *owner_advice(pull, pack_ownership.missing_records(api, pull, changes)),
        *owner_notes(api, pull, changes, arguments.head_sha),
    ]
    decision = decide(
        {**verdict, "scope_reason": reason}, candidate, result, arguments.run_url, advice
    )

    if decision.auto_merge:
        # Auto-merge cannot be armed once GitHub calls the pull request mergeable.
        pending = Decision("pending", "holding the check while auto-merge is armed")
        post_status(api, arguments.head_sha, pending, arguments.run_url)

        if not arm_auto_merge(api, pull["node_id"]):
            decision = Decision(
                decision.status,
                "validated, and auto-merge could not be armed",
                needs_steward=True,
                comment=_comment(
                    "Validated and ownership verified.",
                    verdict,
                    ["Auto-merge could not be armed, so a steward has to merge this one.", *advice],
                    arguments.run_url,
                ),
            )

    post_status(api, arguments.head_sha, decision, arguments.run_url)
    upsert_comment(api, number, decision.comment)
    sync_document_labels(api, number, check_scope.kinds(changes))

    if decision.needs_steward:
        add_steward_label(api, number)
        request_stewards(api, number)
    elif decision.auto_merge:
        remove_steward_label(api, number)
        withdraw_stewards(api, number)

    print(f"#{number}: {decision.status}, {decision.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
