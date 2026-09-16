#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure an image and print its record for an authored document, per RFC 0058.

The image is a local file or an https URL. A URL is fetched by the same rules
as the checks, and a local file needs --url, the address where it will be
hosted. When the image breaks a limit of its role, or a value breaks the schema
or the SPDX list, the problems go to stderr and no record is printed.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_license
import check_schema
import images

KEYS = ("id", "url", "sha256", "width", "height", "size", "license", "attribution", "source")


def measure(image, role, fetch=images.fetch):
    """The bytes of a local file or an https URL, at most the cap of `role`. Raises Invalid, Unavailable or OSError."""
    cap = images.LIMITS[role].cap
    if "://" in image:
        return fetch(image, cap)
    with open(image, "rb") as handle:
        data = handle.read(cap + 1)
    if len(data) > cap:
        raise images.Invalid(f"{image} is larger than the cap of {cap} bytes")
    return data


def record(data, values):
    """The record of `data`, from its measured facts and the `values` the author gave. Raises Invalid."""
    facts = images.inspect(data)
    merged = {
        **values,
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": facts.width,
        "height": facts.height,
        "size": len(data),
    }
    return {key: merged[key] for key in KEYS if merged.get(key) is not None}


def validator(role):
    """A validator for one record of `role`, with the limits the document schema gives that role."""
    schema = check_schema.validator().schema
    roles = schema["properties"]["images"]["properties"]
    subschema = roles[images.ICON] if role == images.ICON else roles[images.DESCRIPTION]["items"]
    return Draft202012Validator({**subschema, "$defs": schema["$defs"]})


def problems(role, entry):
    """What in `entry` the schema, the fetch rules for its url or the SPDX list refuse."""
    place = f"images.{role}"
    found = []
    check_schema.check_schema(place, entry, validator(role), found)
    check_schema.check_license(place, entry.get("license"), found)
    if found:
        return found
    try:
        images.target(entry["url"])
    except images.Invalid as error:
        found.append(f"{place}: url: {error}")
    found.extend(f"{place}: license: {message}" for message in check_license.errors_for(entry.get("license")))
    return found


def quoted(text):
    """`text` as a TOML basic string, with every character outside printable ASCII escaped."""
    characters = []
    for character in text:
        code = ord(character)
        if character in '"\\':
            characters.append("\\" + character)
        elif 0x20 <= code < 0x7F:
            characters.append(character)
        elif code <= 0xFFFF:
            characters.append(f"\\u{code:04X}")
        else:
            characters.append(f"\\U{code:08X}")
    return '"' + "".join(characters) + '"'


def render(role, entry):
    header = f"[images.{images.ICON}]" if role == images.ICON else f"[[images.{images.DESCRIPTION}]]"
    lines = [header]
    for key, value in entry.items():
        lines.append(f"{key} = {value if isinstance(value, int) else quoted(value)}")
    return "\n".join(lines) + "\n"


def _refuse(found):
    print("\n".join(found), file=sys.stderr)
    return 1


def main(argv=None, fetch=images.fetch):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", help="a local image file, or the https URL of an image that is already hosted")
    roles = parser.add_mutually_exclusive_group(required=True)
    roles.add_argument("--icon", action="store_true", help="write the record of the listing icon")
    roles.add_argument("--description", metavar="ID", help="write the record of a description image with this id")
    parser.add_argument("--url", help="the https URL where the local file will be hosted")
    parser.add_argument("--license", help="the SPDX license expression of the image, when it is not the document's license")
    parser.add_argument("--attribution", help="the credit text a client shows with the image")
    parser.add_argument("--source", help="the https URL of the original work")
    arguments = parser.parse_args(argv)

    hosted = "://" in arguments.image
    if hosted and arguments.url is not None:
        parser.error("--url is only for a local file, because a hosted image keeps its own URL")
    if not hosted and arguments.url is None:
        parser.error("a local file needs --url, the https URL where it will be hosted")

    role = images.ICON if arguments.icon else images.DESCRIPTION
    try:
        data = measure(arguments.image, role, fetch)
    except images.Invalid as error:
        return _refuse([str(error)])
    except (images.Unavailable, OSError) as error:
        print(f"could not measure {arguments.image}: {error}", file=sys.stderr)
        return 2

    values = {
        "id": arguments.description,
        "url": arguments.url or arguments.image,
        "license": arguments.license,
        "attribution": arguments.attribution,
        "source": arguments.source,
    }
    try:
        entry = record(data, values)
    except images.Invalid as error:
        return _refuse([f"{arguments.image}: {error}"])

    found = [f"{arguments.image}: {problem}" for problem in images.compare(entry, role, data)]
    found = found or problems(role, entry)
    if found:
        return _refuse(found)

    sys.stdout.write(render(role, entry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
