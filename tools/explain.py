#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepared explanations for the known messages of the checks.

Each rule matches the text of one message and fills its values into a fixed
explanation, so the verdict comment can say how to fix what it reports. A
message that no rule knows gets no explanation.
"""

import re
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_tags
import ownership


class Explanation(NamedTuple):
    text: str
    # The fix is on the release host or its repository and not in the pull
    # request, so a push changes nothing.
    outside_pull_request: bool


# The prefix check_release puts in front of a message about the latest release.
RELEASE = r"^listings/(?P<id>[^/]+)\.toml: the latest release (?P<tag>.+?) cannot be stamped: "

REPLACE = "Then upload the zip to release {tag} in place of the old one."

# The stamper falls back to the only top-level folder when no folder holds
# mod.toml, so the named folder can be an asset folder or a wrapper. The text
# must not tell the author only to rename it.
LAYOUT = (
    "The index installs a mod from one top-level folder named {expected}, with mod.toml and "
    "every other file of the mod directly in it, and nothing else at the top of the zip. "
)

RULES = [
    (
        re.compile(
            RELEASE + r"the archive's top-level directory is '(?P<folder>[^']*)' and the id is "
            r"'(?P<expected>[^']*)'"
        ),
        "The folder in the zip of release {tag} is {folder}, and the id is {expected}. "
        "Only the casing differs, but the game sees the folder name as the identity of the mod, "
        "so it has to match exactly. Rename the folder in the zip to {expected}, with mod.toml "
        "directly in it. " + REPLACE,
        True,
    ),
    (
        re.compile(
            RELEASE + r"the archive's top-level directory is '(?P<folder>[^']*)', which does not "
            r"match the id '(?P<expected>[^']*)'"
        ),
        LAYOUT + "The zip of release {tag} has the folder {folder} at the top instead. When "
        "mod.toml is directly in {folder}, renaming that folder to {expected} is enough. "
        "Otherwise, put mod.toml and the other files of the mod into a new folder {expected}, "
        "and make it the only folder at the top of the zip. " + REPLACE,
        True,
    ),
    (
        re.compile(
            RELEASE + r"the install root is neither derivable from the archive nor authored: .*"
            r"named '(?P<expected>[^']*)'"
        ),
        LAYOUT + "The zip of release {tag} has no such folder: either the files of the mod are "
        "at the top of the zip, or there is more than one folder there. Put mod.toml and the "
        "other files of the mod into one folder {expected}, and make it the only folder at the "
        "top of the zip. " + REPLACE,
        True,
    ),
    (
        re.compile(RELEASE + r"the release carries no archive to download"),
        "Release {tag} has no zip that the index can download. The source code archives that "
        "GitHub adds to every release do not count. Upload the mod as a zip to release {tag}. "
        "When the release has more than one zip, the index takes the one named {assets}.",
        True,
    ),
    (
        re.compile(
            RELEASE + r"the release carries \d+ archives and none of them is named after the "
            r"listing \((?P<names>[^)]*)\)"
        ),
        "Release {tag} has more than one zip ({names}), and the index does not guess which one "
        "holds the mod. Name that zip {assets}, or remove the other zips from the release.",
        True,
    ),
    (
        re.compile(r"^\S+: tags: '(?P<tag>[^']*)' is not a curated tag"),
        "The tag {tag} can stay, but clients only offer the tags of "
        f"[the curated list]({check_tags.SPEC_URL}) as filters. Where a curated tag fits the "
        "mod, add it to the tags.",
        False,
    ),
    (
        re.compile(r"^\S+: tags: the document has no curated tag"),
        f"Add at least one tag from [the curated list]({check_tags.SPEC_URL}), so a client "
        "that filters by tag can show the mod.",
        False,
    ),
    (
        re.compile(
            r"(?P<login>[A-Za-z0-9-]+) did not prove control of (?:the fork )?"
            r"(?P<repository>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)(?::|$)"
        ),
        "Add the topic {topic} to {repository}. Open "
        "[{repository}](https://github.com/{repository}), choose the gear next to About, and type "
        "the topic under Topics. A topic changes no code and no release.",
        True,
    ),
]


def explain(message):
    """The explanation of one message, or None when no rule knows it."""
    for pattern, template, outside_pull_request in RULES:
        match = pattern.search(message)
        if match:
            return Explanation(template.format(**_values(match)), outside_pull_request)
    return None


def _values(match):
    values = {key: _code(value) for key, value in match.groupdict().items() if value is not None}
    found = match.groupdict()
    if found.get("id") is not None and found.get("tag") is not None:
        # The names the release host looks for, with the tag without a leading v.
        identifier, version = found["id"], found["tag"].lstrip("vV")
        values["assets"] = (
            f"{_code(identifier + '.zip')}, {_code(f'{identifier}-{version}.zip')} "
            f"or {_code(f'{identifier}_{version}.zip')}"
        )
    login = found.get("login")
    if login is not None:
        values["topic"] = _code(ownership.TOPIC.format(login=login.lower()))
    # The links need the plain name, which the pattern limits to safe characters.
    if found.get("repository") is not None:
        values["repository"] = match.group("repository")
    return values


def _code(value):
    """The value as inline code that no character of it can break out of."""
    return "`" + re.sub(r"[`\r\n]", "", value) + "`"
