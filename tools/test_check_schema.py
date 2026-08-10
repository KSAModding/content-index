#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests for the authored document schema and the checks around it.

The schema is the only thing standing between a pull request and an automatic
merge, so it is tested from both sides: every document under tools/tests/valid/
has to pass, and every rejected case below has to fail for the stated reason.

The valid documents are real listings. A change that makes one of them fail is a
change that would delist working content.

A rejected case names the location and the words of the error it expects, not
just a word that appears somewhere in it. A fragment of "id" alone is satisfied
by any message containing "valid", which pins nothing.
"""

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import check_schema

VALID = Path(__file__).parent / "tests" / "valid"

MOD_KEYS = """\
spec_version = 1
id = "TestMod"
type = "mod"
name = "Test Mod"
authors = ["Nobody"]
abstract = "A mod that exists only in this test file."
license = "MIT"
"""

MOD_TABLES = """
[compatibility]
game_min = "2026.8.3.5117"

[links]
forums = "https://forums.ahwoo.com/threads/test-mod.1/"
"""

PACK_KEYS = """\
spec_version = 1
id = "TestPack"
type = "modpack"
name = "Test Pack"
authors = ["Nobody"]
abstract = "A pack that exists only in this test file."
license = "CC0-1.0"
version = "1.0.0"
released_at = "2026-08-05T12:00:00Z"
"""

PACK_TABLES = """
[compatibility]
game_min = "2026.8.3.5117"

[links]
forums = "https://forums.ahwoo.com/threads/test-pack.1/"

[[mods]]
id = "AdvancedFlightComputer"
version = "0.7.0"
"""

MOD = MOD_KEYS + MOD_TABLES
PACK = PACK_KEYS + PACK_TABLES

PACK_MEMBER = '[[mods]]\nid = "AdvancedFlightComputer"\nversion = "0.7.0"\n'

LOADER = ('type = "mod"', 'type = "mod-loader"')
GAME_MIN = 'game_min = "2026.8.3.5117"'
FORUMS = 'forums = "https://forums.ahwoo.com/threads/test-mod.1/"'

# A loader that installs somewhere, so the provides cases have a valid base.
STANDALONE = '\n[install]\ntarget = "standalone"\n\n[provides]\nlaunch = "x.exe"\n'


def mod(*, replace=None, keys="", append=""):
    """The base mod document, edited.

    'keys' joins the top-level keys, 'append' adds a section at the end, and
    'replace' swaps a fragment anywhere. The split matters because a bare key
    appended after the last table would land inside that table.
    """
    return edit(MOD_KEYS + keys + MOD_TABLES, replace, append)


def pack(*, replace=None, keys="", append=""):
    """The base pack document, edited the same way."""
    return edit(PACK_KEYS + keys + PACK_TABLES, replace, append)


def loader(*, keys="", append=""):
    """The base document as a mod-loader."""
    return mod(replace=LOADER, keys=keys, append=append)


def edit(text, replace, append):
    if replace is not None:
        old, new = replace
        assert old in text, f"'{old}' is not in the base document"
        text = text.replace(old, new)
    return text + append


# Each case is (name, document, a fragment the reported error has to contain).
REJECTED = [
    # The shared authored core
    ("unknown top-level key", mod(keys='abstrct = "typo"\n'), "the document: Additional properties are not allowed ('abstrct'"),
    ("unknown spec version", mod(replace=("spec_version = 1", "spec_version = 2")), "spec_version: 1 was expected"),
    ("unknown content type", mod(replace=('type = "mod"', 'type = "vehicle"')), "type: 'vehicle' is not one of"),
    ("empty name", mod(replace=('name = "Test Mod"', 'name = ""')), "name: '' should be non-empty"),
    ("empty abstract", mod(replace=('abstract = "A mod that exists only in this test file."', 'abstract = ""')), "abstract: '' should be non-empty"),
    ("no authors", mod(replace=('authors = ["Nobody"]', "authors = []")), "authors: [] should be non-empty"),
    ("unknown status", mod(keys='status = "abandoned"\n'), "status: 'abandoned' is not one of"),
    ("uppercase tag", mod(keys='tags = ["Parts"]\n'), "tags[0]: 'Parts' does not match"),
    ("successor without a deprecation", mod(keys='superseded_by = "TestModNG"\n'), "the document: 'status' is a required property"),
    (
        "a listing superseding itself",
        mod(keys='status = "deprecated"\nsuperseded_by = "testmod"\n'),
        "superseded_by: a listing cannot supersede itself",
    ),

    # Ids
    ("reserved id Core", mod(replace=('id = "TestMod"', 'id = "Core"')), "id: 'Core' is a reserved name"),
    ("reserved id CON", mod(replace=('id = "TestMod"', 'id = "con"')), "id: 'con' is a reserved name"),
    ("reserved id PRN", mod(replace=('id = "TestMod"', 'id = "PRN"')), "id: 'PRN' is a reserved name"),
    ("reserved id AUX", mod(replace=('id = "TestMod"', 'id = "Aux"')), "id: 'Aux' is a reserved name"),
    ("reserved id NUL", mod(replace=('id = "TestMod"', 'id = "NUL"')), "id: 'NUL' is a reserved name"),
    ("reserved id LPT9", mod(replace=('id = "TestMod"', 'id = "lpt9"')), "id: 'lpt9' is a reserved name"),
    ("reserved id with an extension", mod(replace=('id = "TestMod"', 'id = "com1.tools"')), "id: 'com1.tools' is a reserved name"),
    ("id with a trailing dot", mod(replace=('id = "TestMod"', 'id = "TestMod."')), "id: 'TestMod.' does not match"),
    ("id with a leading dot", mod(replace=('id = "TestMod"', 'id = ".TestMod"')), "id: '.TestMod' does not match"),
    ("id with a space", mod(replace=('id = "TestMod"', 'id = "Test Mod"')), "id: 'Test Mod' does not match"),
    ("id with a trailing newline", mod(replace=('id = "TestMod"', 'id = "TestMod\\n"')), "id: 'TestMod\\n' does not match"),
    ("id longer than the path budget", mod(replace=('id = "TestMod"', f'id = "{"M" * 65}"')), "id: 'MMM"),

    # Links
    ("missing forums link", mod(replace=(FORUMS, 'repository = "https://github.com/a/b"')), "links: 'forums' is a required property"),
    ("forums link on another host", mod(replace=(FORUMS, 'forums = "https://example.com/t/1"')), "links.forums: 'https://example.com/t/1' does not match"),
    ("a link that is not a URL", mod(replace=(FORUMS, FORUMS + '\nrepository = "github.com/a/b"')), "links.repository: 'github.com/a/b' does not match"),
    (
        "link key differing only in case",
        mod(replace=(FORUMS, FORUMS + '\nForums = "https://forums.ahwoo.com/threads/test-mod.2/"')),
        "links: 'Forums' and 'forums' are the same key",
    ),

    # Compatibility
    ("missing game_min", mod(replace=(GAME_MIN, 'game_max = "2026.8.5.5168"')), "compatibility: 'game_min' is a required property"),
    ("unknown compatibility key", mod(replace=(GAME_MIN, GAME_MIN + '\ngame_exact = "2026.8.3.5117"')), "compatibility: Additional properties are not allowed ('game_exact'"),
    ("game bound with a build suffix", mod(replace=("5117", "5117-LOCAL")), "compatibility.game_min: '2026.8.3.5117-LOCAL' does not match"),
    ("game bound as a year.month.build prefix", mod(replace=("2026.8.3.5117", "2026.8.3")), "compatibility.game_min: '2026.8.3' does not match"),
    ("game bound with a month above twelve", mod(replace=("2026.8.3.5117", "2026.13")), "compatibility.game_min: '2026.13' does not match"),
    ("game_max older than game_min", mod(replace=(GAME_MIN, GAME_MIN + '\ngame_max = "2026.7.5.4892"')), "is older than game_min"),
    ("game_max in a month before game_min", mod(replace=(GAME_MIN, 'game_min = "2026.9"\ngame_max = "2026.7"')), "is older than game_min"),
    ("unknown platform", mod(replace=(GAME_MIN, GAME_MIN + '\nos = ["haiku"]')), "compatibility.os[0]: 'haiku' is not one of"),
    ("the same platform twice", mod(replace=(GAME_MIN, GAME_MIN + '\nos = ["linux", "linux"]')), "compatibility.os: ['linux', 'linux'] has non-unique elements"),

    # Releases
    ("releases naming two hosts without an authority", mod(append='\n[releases]\ngithub = "a/b"\nspacedock = 4253\n'), "releases: 'authority' is a required property"),
    ("authority naming a host that is not there", mod(append='\n[releases]\ngithub = "a/b"\nauthority = "spacedock"\n'), "releases: 'spacedock' is a required property"),
    ("releases with no host at all", mod(append='\n[releases]\nauthority = "github"\n'), "releases: {'authority': 'github'} is not valid under any"),
    ("unknown release host", mod(append='\n[releases]\ncurseforge = 12\n'), "releases: Additional properties are not allowed ('curseforge'"),
    ("unknown authority", mod(append='\n[releases]\ngithub = "a/b"\nauthority = "forums"\n'), "releases.authority: 'forums' is not one of"),
    ("spacedock id as a string", mod(append='\n[releases]\nspacedock = "4253"\n'), "releases.spacedock: '4253' is not of type 'integer'"),
    ("spacedock id of zero", mod(append="\n[releases]\nspacedock = 0\n"), "releases.spacedock: 0 is less than the minimum"),
    ("github host that is not owner/repo", mod(append='\n[releases]\ngithub = "StarMapLoader"\n'), "releases.github: 'StarMapLoader' does not match"),

    # Loader
    ("loader max below min", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.6"\nmax = "0.4.5"\n'), "loader: max '0.4.5' is below min '0.4.6'"),
    ("loader version with a leading v", mod(append='\n[loader]\nid = "StarMap"\nmin = "v0.4.5"\n'), "loader.min: 'v0.4.5' does not match"),
    ("a bound pair that does not parse at all", mod(append='\n[loader]\nid = "StarMap"\nmin = "v0.4.6"\nmax = "0.4"\n'), "loader.min: 'v0.4.6' does not match"),
    ("loader without a min bound", mod(append='\n[loader]\nid = "StarMap"\n'), "loader: 'min' is a required property"),
    ("unknown loader key", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5"\nexact = "0.4.5"\n'), "loader: Additional properties are not allowed ('exact'"),
    ("a listing as its own loader", mod(append='\n[loader]\nid = "TestMod"\nmin = "1.0.0"\n'), "loader: a listing cannot be its own loader"),
    ("a release below a pre-release of it", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.0"\nmax = "0.5.0-rc.1"\n'), "loader: max '0.5.0-rc.1' is below min '0.5.0'"),
    ("a numeric pre-release ranked above an alphanumeric one", mod(append='\n[loader]\nid = "StarMap"\nmin = "1.0.0-alpha"\nmax = "1.0.0-1"\n'), "loader: max '1.0.0-1' is below min '1.0.0-alpha'"),

    # Dependencies
    ("dependency naming both id and any_of", mod(append='\n[[dependencies]]\nid = "A"\nkind = "required"\nany_of = [{ id = "B" }]\n'), "dependencies[0]: {"),
    ("dependency naming neither id nor any_of", mod(append='\n[[dependencies]]\nkind = "required"\n'), "dependencies[0]: {"),
    ("unknown dependency key", mod(append='\n[[dependencies]]\nid = "A"\nkind = "required"\nexact = "1.0.0"\n'), "dependencies[0]: Additional properties are not allowed ('exact'"),
    ("unknown dependency kind", mod(append='\n[[dependencies]]\nid = "A"\nkind = "provides"\n'), "dependencies[0].kind: 'provides' is not one of"),
    ("dependency without a kind", mod(append='\n[[dependencies]]\nid = "A"\n'), "dependencies[0]: 'kind' is a required property"),
    ("any_of with a kind that offers no choice", mod(append='\n[[dependencies]]\nkind = "conflict"\nany_of = [{ id = "A" }, { id = "B" }]\n'), "dependencies[0].kind: 'conflict' is not one of"),
    ("any_of carrying entry-level bounds", mod(append='\n[[dependencies]]\nkind = "required"\nmin = "1.0.0"\nany_of = [{ id = "A" }]\n'), "dependencies[0].min: this key is not allowed here"),
    ("an empty any_of", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = []\n'), "dependencies[0].any_of: [] should be non-empty"),
    ("an any_of alternative without an id", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = [{ min = "1.0.0" }]\n'), "dependencies[0].any_of[0]: 'id' is a required property"),
    ("an unknown key in an any_of alternative", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = [{ id = "A", kind = "required" }]\n'), "dependencies[0].any_of[0]: Additional properties are not allowed ('kind'"),
    ("any_of alternative with a max below its min", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = [{ id = "A", min = "2.0.0", max = "1.0.0" }]\n'), "dependencies[0].any_of[0]: max '1.0.0' is below min '2.0.0'"),
    ("any_of naming the same alternative twice", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = [{ id = "A" }, { id = "a" }]\n'), "dependencies[0]: names 'a' more than once"),
    ("self-dependency", mod(append='\n[[dependencies]]\nid = "TestMod"\nkind = "required"\n'), "dependencies[0]: a listing cannot depend on itself"),
    ("the same dependency twice", mod(append='\n[[dependencies]]\nid = "A"\nkind = "required"\n\n[[dependencies]]\nid = "a"\nkind = "conflict"\n'), "dependencies[1]: 'a' already has a dependency entry"),

    # Install
    ("unknown install key", mod(append='\n[install]\nsubfolder = "x"\n'), "install: Additional properties are not allowed ('subfolder'"),
    ("install root escaping the archive", mod(append='\n[install]\nroot = "../elsewhere"\n'), "install.root: '../elsewhere' is a path that leaves its anchor"),
    ("install root as an absolute path", mod(append='\n[install]\nroot = "/etc/passwd"\n'), "install.root: '/etc/passwd' does not match"),
    ("install root as a Windows path", mod(append='\n[install]\nroot = "C:/Windows"\n'), "install.root: 'C:/Windows' does not match"),
    ("install root with a backslash separator", mod(append='\n[install]\nroot = "build\\\\TestMod"\n'), "install.root: 'build\\\\TestMod' does not match"),
    ("install root under a home shortcut", mod(append='\n[install]\nroot = "~/mods"\n'), "install.root: '~/mods' does not match"),
    ("install root hiding a parent segment", mod(append='\n[install]\nroot = "build/../../etc"\n'), "install.root: 'build/../../etc' is a path that leaves its anchor"),
    ("install root through a device name", mod(append='\n[install]\nroot = "build/NUL/x"\n'), "install.root: 'build/NUL/x' is a path through a reserved Windows device name"),
    ("a step that is not prose", mod(append="\n[install]\nsteps = [3]\n"), "install.steps[0]: 3 is not of type 'string'"),
    ("an install section that is not a table", mod(keys='install = "later"\n'), "install: 'later' is not of type 'object'"),
    ("a mod choosing where it installs", mod(append='\n[install]\ntarget = "game-root"\n'), "install.target: 'mods' was expected"),
    ("a mod nesting itself below the anchor", mod(append='\n[install]\ntarget = "mods"\npath = "extras"\n'), "install.path: this key is not allowed here"),
    ("unknown anchor", loader(append='\n[install]\ntarget = "somewhere"\n'), "install.target: 'somewhere' is not one of"),
    ("a loader install without a target", loader(append='\n[install]\nroot = "StarMap"\n'), "install: 'target' is a required property"),
    ("standalone without a launch target", loader(append='\n[install]\ntarget = "standalone"\n'), "the document: 'provides' is a required property"),
    ("manages claiming the game's own manifest", loader(append='\n[install]\ntarget = "user-data"\nmanages = ["Manifest.toml"]\n'), "install.manages[0]: 'Manifest.toml' is the game's own manifest"),
    ("manages claiming the manifest with a trailing space", loader(append='\n[install]\ntarget = "user-data"\nmanages = ["manifest.toml "]\n'), "install.manages[0]: 'manifest.toml ' is the game's own manifest"),
    ("manages claiming the manifest with a trailing dot", loader(append='\n[install]\ntarget = "user-data"\nmanages = ["MANIFEST.TOML."]\n'), "install.manages[0]: 'MANIFEST.TOML.' is the game's own manifest"),

    # Provides
    ("provides on a mod", mod(append='\n[provides]\nlaunch = "TestMod.exe"\n'), "provides: this key is not allowed here"),
    ("unknown provides key", loader(append=STANDALONE + 'content-root = "mods"\n'), "provides: Additional properties are not allowed ('content-root'"),
    ("unknown content dir", loader(append=STANDALONE + 'content-dir = "anywhere"\n'), "provides.content-dir: 'anywhere' is not one of"),
    ("a content path with no content dir", loader(append=STANDALONE + 'content-path = "extras"\n'), "provides: 'content-dir' is a dependency of 'content-path'"),
    ("a launch target through a device name", loader(append='\n[install]\ntarget = "standalone"\n\n[provides]\nlaunch = "NUL"\n'), "provides.launch: 'NUL' is a path through a reserved Windows device name"),
    ("an unknown key inside configure", loader(append=STANDALONE + '\n[provides.configure]\nfile = "c.json"\nformat = "json"\nmods-path = "ModsLocation"\n'), "provides.configure: Additional properties are not allowed ('mods-path'"),
    ("configure without a format", loader(append=STANDALONE + '\n[provides.configure]\nfile = "c.json"\n'), "provides.configure: 'format' is a required property"),
    ("configure without a file", loader(append=STANDALONE + '\n[provides.configure]\nformat = "json"\n'), "provides.configure: 'file' is a required property"),
    ("an unwritable configure format", loader(append=STANDALONE + '\n[provides.configure]\nfile = "c.ini"\nformat = "ini"\n'), "provides.configure.format: 'ini' is not one of"),
    ("a configure key that cannot be addressed", loader(append=STANDALONE + '\n[provides.configure]\nfile = "c.json"\nformat = "json"\ngame-path = ""\n'), "provides.configure.game-path: '' does not match"),

    # License
    ("unbalanced parentheses in the license", mod(replace=('license = "MIT"', 'license = "(MIT OR Apache-2.0"')), "license: '(MIT OR Apache-2.0' has unbalanced parentheses"),
    ("a license closing a parenthesis it never opened", mod(replace=('license = "MIT"', 'license = "MIT)"')), "license: 'MIT)' has unbalanced parentheses"),
    ("a license closing before opening", mod(replace=('license = "MIT"', 'license = ")("')), "license: ')(' has unbalanced parentheses"),
    ("a license operator with no right side", mod(replace=('license = "MIT"', 'license = "MIT OR"')), "license: 'MIT OR' does not match"),

    # Type boundaries
    ("a mod carrying a pack version", mod(keys='version = "1.0.0"\n'), "version: this key is not allowed here"),
    ("a mod carrying a release timestamp", mod(keys='released_at = "2026-08-05T12:00:00Z"\n'), "released_at: this key is not allowed here"),
    ("a mod carrying a changelog", mod(keys='changelog = "see the releases page"\n'), "changelog: this key is not allowed here"),
    ("a mod pinning members", mod(append='\n[[mods]]\nid = "A"\nversion = "1.0.0"\n'), "mods: this key is not allowed here"),
    ("a mod pinning vehicles", mod(append='\n[[vehicles]]\nid = "A"\nversion = "1.0.0"\n'), "vehicles: this key is not allowed here"),
    ("a mod pinning saves", mod(append='\n[[saves]]\nid = "A"\nversion = "1.0.0"\n'), "saves: this key is not allowed here"),
    ("mod-loader declaring a loader", loader(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5"\n'), "loader: this key is not allowed here"),
    ("mod-loader carrying a pack version", loader(keys='version = "1.0.0"\n'), "version: this key is not allowed here"),
    ("mod-loader pinning members", loader(append='\n[[mods]]\nid = "A"\nversion = "1.0.0"\n'), "mods: this key is not allowed here"),

    # Packs
    ("a pack with a release host", pack(append='\n[releases]\ngithub = "a/b"\n'), "releases: this key is not allowed here"),
    ("a pack installing something", pack(append='\n[install]\nroot = "extras"\n'), "install: this key is not allowed here"),
    ("a pack declaring a loader", pack(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5"\n'), "loader: this key is not allowed here"),
    ("a pack declaring dependencies", pack(append='\n[[dependencies]]\nid = "A"\nkind = "required"\n'), "dependencies: this key is not allowed here"),
    ("a pack providing something", pack(append='\n[provides]\nlaunch = "x.exe"\n'), "provides: this key is not allowed here"),
    ("a pack with no members", pack(replace=(PACK_MEMBER, "")), "'mods' is a required property"),
    ("a pack with an empty member list", pack(replace=(PACK_MEMBER, ""), keys="mods = []\n"), "mods: [] should be non-empty"),
    ("a pack member without a pinned version", pack(replace=('version = "0.7.0"', 'min = "0.7.0"')), "mods[0]: Additional properties are not allowed ('min'"),
    ("a pack member pinned to a range", pack(replace=('version = "0.7.0"', 'version = "0.7"')), "mods[0].version: '0.7' does not match"),
    ("an unknown key on a pack member", pack(replace=('version = "0.7.0"', 'version = "0.7.0"\nkind = "required"')), "mods[0]: Additional properties are not allowed ('kind'"),
    ("a pack pinning the same mod twice", pack(append='\n[[mods]]\nid = "advancedflightcomputer"\nversion = "0.8.0"\n'), "mods[1]: 'advancedflightcomputer' is pinned by mods[0]"),
    ("a pack pinning one id in two sections", pack(append='\n[[vehicles]]\nid = "AdvancedFlightComputer"\nversion = "0.8.0"\n'), "vehicles[0]: 'AdvancedFlightComputer' is pinned by mods[0]"),
    ("a pack pinning itself", pack(append='\n[[mods]]\nid = "TestPack"\nversion = "1.0.0"\n'), "mods[1]: a pack cannot pin itself"),
    ("a pack without a released_at", pack(replace=('released_at = "2026-08-05T12:00:00Z"\n', "")), "'released_at' is a required property"),
    ("a pack timestamp without a zone", pack(replace=("T12:00:00Z", "T12:00:00")), "released_at: '2026-08-05T12:00:00' does not match"),
    ("a pack timestamp on no calendar", pack(replace=("2026-08-05T12:00:00Z", "2026-13-45T12:00:00Z")), "released_at: '2026-13-45T12:00:00Z' is not a real date"),
]

# Small positive variations that would be wasteful as their own file.
ACCEPTED = [
    ("a mod with no releases section", MOD),
    ("a deprecated mod with a successor", mod(keys='status = "deprecated"\nsuperseded_by = "TestModNG"\n')),
    ("a month as the lower bound", mod(replace=(GAME_MIN, 'game_min = "2026.7"'))),
    ("two month bounds in order", mod(replace=(GAME_MIN, 'game_min = "2026.7"\ngame_max = "2026.8"'))),
    ("a month bound against a revision bound", mod(replace=(GAME_MIN, 'game_min = "2026.9"\ngame_max = "2026.7.5.4892"'))),
    ("an empty steps list", mod(append="\n[install]\nsteps = []\n")),
    ("a pre-release loader bound", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.0-rc.1"\n')),
    ("a pre-release ordered below its release", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.0-rc.1"\nmax = "0.5.0"\n')),
    ("a numeric pre-release below an alphanumeric one", mod(append='\n[loader]\nid = "StarMap"\nmin = "1.0.0-1"\nmax = "1.0.0-alpha"\n')),
    ("build metadata on a bound", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5+build.7"\nmax = "0.4.5"\n')),
    ("a compound license expression", mod(replace=('license = "MIT"', 'license = "(MIT OR Apache-2.0) AND CC0-1.0"'))),
    ("a license exception", mod(replace=('license = "MIT"', 'license = "GPL-2.0-or-later WITH Bison-exception-2.2"'))),
    ("a custom license reference", mod(replace=('license = "MIT"', 'license = "LicenseRef-Kitten-1.0"'))),
    ("a dotted id", mod(replace=('id = "TestMod"', 'id = "Kitten.Tools"'))),
    ("an id that starts like a reserved name", mod(replace=('id = "TestMod"', 'id = "CONtrol"'))),
    ("an id at the length limit", mod(replace=('id = "TestMod"', f'id = "{"M" * 64}"'))),
    ("a path segment that starts like a device", mod(append='\n[install]\nroot = "console/TestMod"\n')),
    ("a dependency on a mod named like a reserved stem", mod(append='\n[[dependencies]]\nid = "Nullify"\nkind = "optional"\n')),
    ("a link key the format does not name", mod(replace=(FORUMS, FORUMS + '\ndiscord = "https://discord.gg/abc"'))),
    ("a native TOML timestamp in a pack", pack(replace=('released_at = "2026-08-05T12:00:00Z"', "released_at = 2026-08-05T12:00:00Z"))),
]


def failures_for(text, checker):
    """Run the whole check over one in-memory document."""
    errors = []
    document = check_schema.normalise(tomllib.loads(text))
    check_schema.check_parsed("<case>", document, checker, errors)
    return errors


def main():
    checker = check_schema.validator()
    failures = []
    checked = 0

    for path in sorted(VALID.glob("*.toml")):
        checked += 1
        errors = failures_for(path.read_text(encoding="utf-8"), checker)
        if errors:
            failures.append(f"{path.name} should be valid, but: " + "; ".join(errors))

    for name, text in ACCEPTED:
        checked += 1
        errors = failures_for(text, checker)
        if errors:
            failures.append(f"'{name}' should be accepted, but: " + "; ".join(errors))

    seen = set()
    for name, text, fragment in REJECTED:
        checked += 1
        assert name not in seen, f"two cases are both called '{name}'"
        seen.add(name)
        errors = failures_for(text, checker)
        if not errors:
            failures.append(f"'{name}' should be rejected, but nothing complained")
        elif not any(fragment in error for error in errors):
            failures.append(f"'{name}' should be rejected for '{fragment}', but said: " + "; ".join(errors))

    if failures:
        print("\n".join(failures))
        print(f"\n{len(failures)} of {checked} case(s) failed")
        return 1

    print(f"checked {checked} case(s), all behave as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
