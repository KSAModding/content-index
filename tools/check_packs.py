#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check pack owner records and the immutability of accepted versions."""

import sys
from pathlib import Path

import check_scope
import pack_ownership

ROOT = Path(__file__).resolve().parent.parent
PACKS = ROOT / "packs"


def _pack_path(path):
    return check_scope.kind_of(path) == check_scope.PACK_KIND


def check(changes=(), packs=PACKS):
    errors = []

    for change in changes:
        paths = [change.path]
        if change.previous_path:
            paths.append(change.previous_path)
        if any(_pack_path(path) for path in paths) and change.status != "added":
            path = next(path for path in paths if _pack_path(path))
            errors.append(
                f"{path}: an accepted pack version is immutable; publish a new version in a new file"
            )

    for folder in sorted(path for path in packs.iterdir() if path.is_dir()):
        versions = sorted(folder.glob("*.toml"))
        owner = folder / pack_ownership.OWNER_FILE
        where = owner.relative_to(packs.parent).as_posix()
        if not versions:
            if owner.exists():
                errors.append(f"{where}: the owner record has no pack version")
            continue
        if not owner.is_file():
            errors.append(f"{where}: every pack must record its owner")
            continue
        _, problem = pack_ownership.parse_record(owner.read_text(encoding="utf-8"), where)
        if problem:
            errors.append(problem)

    return errors


def main():
    errors = check()
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        print(f"Pack check failed with {len(errors)} error(s).", file=sys.stderr)
        return 1
    print("Pack owner records are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
