#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve the images a description shows, per RFC 0058.

A client shows only a `ksa-image:<id>` reference to a record of the same
document, so a reference to an id with no record rejects. A record that nothing
references, and any other image in the description, only warns, because no
client shows either of them.

The description is parsed as CommonMark, so an image inside a code block is
not an image, and a reference-style image counts as one.
"""

import re

from markdown_it import MarkdownIt

import images

SCHEME = "ksa-image:"
HTML_IMAGE = re.compile(r"<\s*(?:img|image|picture|svg)\b", re.IGNORECASE)

_parser = None


def parser():
    """CommonMark that keeps every destination as written, so each image can be named."""
    global _parser
    if _parser is None:
        _parser = MarkdownIt("commonmark")
        _parser.validateLink = lambda url: True
        _parser.normalizeLink = lambda url: url
    return _parser


def scan(text):
    """The destination of every Markdown image in `text`, and the number of raw HTML images."""
    destinations = []
    html = 0
    pending = list(reversed(parser().parse(text)))
    while pending:
        token = pending.pop()
        if token.type == "image":
            destinations.append(token.attrGet("src") or "")
        elif token.type in ("html_inline", "html_block"):
            html += len(HTML_IMAGE.findall(token.content))
        if token.children:
            pending.extend(reversed(token.children))
    return destinations, html


def check_document(where, document, errors, notes):
    description = document.get("description")
    destinations, html = scan(description) if isinstance(description, str) else ([], 0)

    ids = {
        record.get("id")
        for _, role, record in images.records(document)
        if role == images.DESCRIPTION
    }
    referenced = set()
    for destination in destinations:
        if destination.startswith(SCHEME):
            identifier = destination[len(SCHEME):]
            referenced.add(identifier)
            if identifier not in ids:
                errors.append(
                    f"{where}: description: '{destination}' names no record in [[images.description]]"
                )
        else:
            notes.append(
                f"{where}: description: the image '{destination}' is not a {SCHEME} reference, "
                "so no client shows it"
            )
    if html:
        notes.append(f"{where}: description: {html} image(s) in raw HTML, which no client shows")

    for place, role, record in images.records(document):
        identifier = record.get("id")
        if role == images.DESCRIPTION and isinstance(identifier, str) and identifier not in referenced:
            notes.append(
                f"{where}: {place}: nothing in the description references '{identifier}', "
                "so no client shows it"
            )
