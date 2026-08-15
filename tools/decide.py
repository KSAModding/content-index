#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Act on a validation verdict: the commit status, auto-merge, and the steward queue.

The privileged half of RFC 0033's listing flow.
"""

import argparse
import base64
import json
import os
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_scope
import ownership

GITHUB_API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
USER_AGENT = "KSAModding-content-index-ownership"

# The required check in the branch ruleset. No job may carry this name.
STATUS_CONTEXT = "validate"
STEWARD_LABEL = "needs-steward"
STEWARD_TEAM = "content-manager-stewards"

COMMENT_MARKER = "<!-- content-index:verdict -->"

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
        if check.get("outcome") == PASS:
            continue
        for message in check.get("messages") or []:
            lines.append(f"- `{check.get('name')}`: {message}")
    return lines


def decide(verdict, candidate, ownership_result, run_url=""):
    """The status reports validation alone. Ownership is a separate axis, so a
    listing that validates but cannot prove it is green and waits for a steward.
    """
    outcome = verdict.get("verdict")
    tail = f"\n\n[The validation run]({run_url})" if run_url else ""

    if outcome == REJECT:
        body = "\n".join(["The validation rejected this change.", ""] + _messages(verdict))
        return Decision("failure", "the validation rejected this change", comment=body + tail)

    if outcome != PASS:
        body = "\n".join(
            ["The validation could not reach a verdict, so nothing is decided yet.", ""]
            + _messages(verdict)
            + ["", "The watcher's sweep comes back to this within the hour."]
        )
        return Decision("error", "the validation could not reach a verdict", comment=body + tail)

    if not candidate:
        reason = verdict.get("scope_reason") or "the change is not a single document"
        return Decision(
            "success",
            "validated, and a steward decides",
            needs_steward=True,
            comment=f"Validated. A steward has to merge this one, because {reason}." + tail,
        )

    if ownership_result.state == ownership.VERIFIED:
        return Decision("success", "validated, arming auto-merge", auto_merge=True)

    if ownership_result.state == ownership.COULD_NOT_EVALUATE:
        return Decision(
            "success",
            "validated, ownership could not be checked",
            needs_steward=True,
            comment=(
                "Validated. The ownership check reached no verdict, so this waits for "
                f"a steward: {ownership_result.reason}." + tail
            ),
        )

    return Decision(
        "success",
        "validated, ownership not verified",
        needs_steward=True,
        comment=(
            f"Validated, and ownership is not verified, so a steward decides.\n\n"
            f"{ownership_result.reason}.\n\n"
            f"The proof is something only you can put on the release repository, which "
            f"is what says you agree to it being indexed. Either set the topic "
            f"`{ownership.TOPIC.format(login='<your-github-username>')}` on it, or commit "
            f"`{ownership.MARKER_PATH}` naming your username."
            + tail
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


def add_label(api, number):
    if STEWARD_LABEL in _labels(api, number):
        return
    try:
        api.send("POST", f"/issues/{number}/labels", {"labels": [STEWARD_LABEL]})
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        api.send(
            "POST",
            "/labels",
            {"name": STEWARD_LABEL, "color": "d93f0b", "description": "waiting on a steward"},
        )
        api.send("POST", f"/issues/{number}/labels", {"labels": [STEWARD_LABEL]})


def remove_label(api, number):
    """Only on the way to a merge, so a steward's own labelling survives a reject."""
    if STEWARD_LABEL in _labels(api, number):
        api.send("DELETE", f"/issues/{number}/labels/{STEWARD_LABEL}", None)


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


def pull_request_for(api, sha):
    """The open pull request whose head is `sha`, from the API rather than the verdict."""
    for pull in api.get(f"/commits/{sha}/pulls", per_page=100) or []:
        if pull.get("state") == "open" and (pull.get("head") or {}).get("sha") == sha:
            return pull
    return None


def changed_paths(api, number):
    changes = []
    page = 1
    while True:
        batch = api.get(f"/pulls/{number}/files", per_page=100, page=page) or []
        for entry in batch:
            changes.append(check_scope.Change(entry["filename"], entry.get("status") or "modified"))
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


def ownership_for(api, pull, path, head_sha):
    """Verify the pull request author against the document it touches.

    Whether the listing exists is read from the base branch, not from the
    reported file status, which is computed against the merge base. Reading the
    branch tip and not the commit the pull request was cut from keeps a stale
    pull request from verifying against a previous owner.
    """
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

    pull = pull_request_for(api, arguments.head_sha)
    if pull is None:
        print(
            f"no open pull request in {api.repository} has {arguments.head_sha} as its head",
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
    candidate, documents, reason = check_scope.evaluate(changed_paths(api, number))

    result = ownership.Result(ownership.UNVERIFIED, "not checked")
    if candidate and verdict.get("verdict") == PASS:
        result = ownership_for(api, pull, documents[0], arguments.head_sha)

    decision = decide({**verdict, "scope_reason": reason}, candidate, result, arguments.run_url)

    if decision.auto_merge:
        # Auto-merge cannot be armed once GitHub calls the pull request mergeable.
        pending = Decision("pending", "holding the check while auto-merge is armed")
        post_status(api, arguments.head_sha, pending, arguments.run_url)

        if not arm_auto_merge(api, pull["node_id"]):
            decision = Decision(
                decision.status,
                "validated, and auto-merge could not be armed",
                needs_steward=True,
                comment="Validated and ownership verified, but auto-merge could not be armed, "
                "so a steward has to merge this one.",
            )

    post_status(api, arguments.head_sha, decision, arguments.run_url)
    upsert_comment(api, number, decision.comment)

    if decision.needs_steward:
        add_label(api, number)
        request_stewards(api, number)
    elif decision.auto_merge:
        remove_label(api, number)
        withdraw_stewards(api, number)

    print(f"#{number}: {decision.status}, {decision.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
