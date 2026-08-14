#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate a pull request and leave a verdict for the ownership workflow.
"""

import argparse
import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_index
import check_layout
import check_license
import check_release
import check_schema
import check_scope
import check_status

ROOT = Path(__file__).resolve().parent.parent

PASS = "pass"
REJECT = "reject"
COULD_NOT_EVALUATE = "could-not-evaluate"

SEVERITY = (REJECT, COULD_NOT_EVALUATE, PASS)

VERDICT_SCHEMA_VERSION = 1

GITHUB_API = "https://api.github.com"
USER_AGENT = "KSAModding-content-index-validation"


class Check:

    def __init__(self, name, outcome, messages=()):
        self.name = name
        self.outcome = outcome
        self.messages = list(messages)

    def as_dict(self):
        return {"name": self.name, "outcome": self.outcome, "messages": self.messages}


def worst(outcomes):
    for outcome in SEVERITY:
        if outcome in outcomes:
            return outcome
    return PASS


def run_layout():
    errors = check_layout.check(ROOT / "listings", ROOT / "packs")
    return Check("layout", REJECT if errors else PASS, errors)


def run_schema():
    errors = []
    validator = check_schema.validator()
    for path in check_schema.documents():
        check_schema.check_document(path, validator, errors)
    return Check("schema", REJECT if errors else PASS, errors)


def run_index(entries, skipped=()):
    errors = check_index.check(entries)
    messages = list(errors)
    if skipped:
        messages.append(f"not read, they do not parse: {', '.join(skipped)}")
    return Check("index", REJECT if errors else PASS, messages)


def run_license(entries):
    errors = []
    for entry in entries:
        check_license.check_document(entry.where, entry.document, errors)
    return Check("license", REJECT if errors else PASS, errors)


def run_status(entries, skipped=()):
    """A state the snapshot builder cannot place fails the build, so catch it here."""
    errors, notes = check_status.check(entries)
    messages = list(errors) + list(notes)
    if errors and skipped:
        messages.append(
            f"a document that does not parse is not counted as a listing: {', '.join(skipped)}"
        )
    return Check("index status", REJECT if errors else PASS, messages)


def run_release(documents, releases=None, token=None):
    if not documents:
        return Check("release", PASS, ["the change touches no document, so no archive was inspected"])

    try:
        results = check_release.inspect_paths(
            [ROOT / path for path in documents], releases=releases, token=token
        )
    except check_release.Unavailable as error:
        return Check("release", COULD_NOT_EVALUATE, [str(error)])

    messages = []
    outcomes = []
    for path, outcome in sorted(results.items()):
        where = Path(path).relative_to(ROOT).as_posix()
        outcomes.append(outcome.outcome)
        messages.extend(f"{where}: {message}" for message in outcome.messages)
    return Check("release", worst(outcomes), messages)


def run_checks(changes, skip_release=False, releases=None, token=None):
    """Every check, ordered so a later one can lean on an earlier one."""
    _, documents, _ = check_scope.evaluate(changes)

    gate = [run_layout(), run_schema()]
    entries, skipped = check_index.load_documents()
    checks = gate + [
        run_index(entries, skipped),
        run_license(entries),
        run_status(entries, skipped),
    ]

    if skip_release:
        return checks

    if any(check.outcome == REJECT for check in gate):
        checks.append(
            Check(
                "release",
                PASS,
                ["not inspected: the document has to pass layout and schema first"],
            )
        )
        return checks

    checks.append(run_release(documents, releases, token))
    return checks


def changed_paths(repository, number, token):
    """What a pull request does to each path it touches.
    """
    changes = []
    url = f"{GITHUB_API}/repos/{repository}/pulls/{number}/files?per_page=100"
    while url:
        payload, link = _api(url, token)
        if not isinstance(payload, list):
            raise ValueError(f"{url}: the answer is not a list of files")
        for entry in payload:
            if not isinstance(entry, dict) or "filename" not in entry:
                raise ValueError(f"{url}: an entry carries no filename")
            changes.append(
                check_scope.Change(entry["filename"], entry.get("status") or "modified")
            )
        url = _next_page(link)
    return changes


def head_sha(repository, number, token):
    """The head commit of a pull request, which is what a commit status names."""
    payload, _ = _api(f"{GITHUB_API}/repos/{repository}/pulls/{number}", token)
    if not isinstance(payload, dict):
        raise ValueError("the pull request answer is not an object")
    return (payload.get("head") or {}).get("sha")


def _api(url, token):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=30) as answer:
        return json.loads(answer.read()), answer.headers.get("Link", "")


def _next_page(link):
    for part in (link or "").split(","):
        section = part.split(";")
        if len(section) > 1 and 'rel="next"' in section[1]:
            return section[0].strip().strip("<>")
    return None


def summarise(verdict):
    """The run as a few lines of Markdown, for the job summary."""
    lines = [
        f"## Validation: {verdict['verdict']}",
        "",
        f"Auto-merge candidate: {'yes' if verdict['auto_merge_candidate'] else 'no'}",
    ]
    if verdict.get("scope_reason"):
        lines.append(f"Reason: {verdict['scope_reason']}")
    lines.append("")
    for check in verdict["checks"]:
        lines.append(f"### {check['name']}: {check['outcome']}")
        lines.extend(f"- {message}" for message in check["messages"] or ["nothing to report"])
        lines.append("")
    return "\n".join(lines)


def _verdict(checks, candidate=False, documents=(), reason="", number=None, sha=None):
    return {
        "schema_version": VERDICT_SCHEMA_VERSION,
        "verdict": worst([check.outcome for check in checks]),
        "auto_merge_candidate": candidate,
        "pull_request": number,
        "head_sha": sha,
        "documents": list(documents),
        "scope_reason": reason,
        "checks": [check.as_dict() for check in checks],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pull-request", type=int, help="the pull request to validate")
    parser.add_argument(
        "--repository", default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/repo, defaults to GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--changed", nargs="*", default=None,
        help="the changed paths, instead of asking the API. For a local run",
    )
    parser.add_argument("--releases", help="a checkout of KSAModding/content-index-releases")
    parser.add_argument("--output", type=Path, help="where to write the verdict as JSON")
    parser.add_argument(
        "--skip-release", action="store_true",
        help="leave the archive inspection out, for a run with no network",
    )
    arguments = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN")
    sha = None
    changes = None if arguments.changed is None else check_scope.changes(arguments.changed)

    if changes is None:
        if not (arguments.pull_request and arguments.repository):
            parser.error("either --changed, or --pull-request together with --repository")
        try:
            changes = changed_paths(arguments.repository, arguments.pull_request, token)
            sha = head_sha(arguments.repository, arguments.pull_request, token)
        except (OSError, ValueError, TypeError, KeyError) as error:
            # Without the file list, scope and the inspection have nothing to
            # work from.
            verdict = _verdict(
                [Check("changed files", COULD_NOT_EVALUATE, [str(error)])],
                reason=f"the changed files could not be read: {error}",
                number=arguments.pull_request,
            )
            _emit(verdict, arguments.output)
            return 0

    candidate, documents, reason = check_scope.evaluate(changes)

    try:
        checks = run_checks(
            changes,
            skip_release=arguments.skip_release,
            releases=arguments.releases,
            token=token,
        )
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        checks = [Check("validation", COULD_NOT_EVALUATE, [f"a check raised {error!r}"])]
        candidate = False

    verdict = _verdict(checks, candidate, documents, reason, arguments.pull_request, sha)

    _emit(verdict, arguments.output)
    return 1 if verdict["verdict"] == REJECT else 0


def _emit(verdict, output):
    print(summarise(verdict))
    if output:
        output.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(summarise(verdict) + "\n")


if __name__ == "__main__":
    sys.exit(main())
