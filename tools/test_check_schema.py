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

import copy
import sys
import tomllib
from pathlib import Path

from jsonschema import Draft202012Validator

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

VEHICLE = """\
spec_version = 1
id = "TestRover"
type = "vehicle"
name = "Test Rover"
authors = ["Nobody"]
abstract = "A vehicle that exists only in this test file."
license = "CC-BY-4.0"
"""

GATE = "is a type that the index does not accept yet, because no release host for it exists (RFC 0085 Rollout)"

PACK_MEMBER = '[[mods]]\nid = "AdvancedFlightComputer"\nversion = "0.7.0"\n'

LOADER = ('type = "mod"', 'type = "mod-loader"')
GAME_MIN = 'game_min = "2026.8.3.5117"'
FORUMS = 'forums = "https://forums.ahwoo.com/threads/test-mod.1/"'

# A loader that installs somewhere, so the provides cases have a valid base.
STANDALONE = '\n[install]\ntarget = "standalone"\n\n[provides]\nlaunch = "x.exe"\n'

# The instance table on that loader, so each instance case adds only its keys.
INSTANCE = STANDALONE + "\n[provides.instance]\n"

PLATFORM = STANDALONE + "\n[provides.platform.linux]\n"

ICON_URL = 'url = "https://example.invalid/icon.png"'
ICON_DIGEST = f'sha256 = "{"a" * 64}"'
ICON = f"\n[images.icon]\n{ICON_URL}\n{ICON_DIGEST}\nwidth = 512\nheight = 512\nsize = 48213\n"
SHOT = f'\n[[images.description]]\nid = "shot"\nurl = "https://example.invalid/shot.png"\nsha256 = "{"b" * 64}"\nwidth = 1600\nheight = 900\nsize = 402117\n'


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
    ("unknown content type", mod(replace=('type = "mod"', 'type = "addon"')), "type: 'addon' is not one of"),
    ("empty name", mod(replace=('name = "Test Mod"', 'name = ""')), "name: '' should be non-empty"),
    ("empty abstract", mod(replace=('abstract = "A mod that exists only in this test file."', 'abstract = ""')), "abstract: '' should be non-empty"),
    ("no authors", mod(replace=('authors = ["Nobody"]', "authors = []")), "authors: [] should be non-empty"),
    ("unknown status", mod(keys='status = "abandoned"\n'), "status: 'abandoned' is not one of"),
    ("uppercase tag", mod(keys='tags = ["Parts"]\n'), "tags[0]: 'Parts' is not lowercase letters and digits, with single - between words, such as parts or life-support"),
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
    ("id with a trailing dot", mod(replace=('id = "TestMod"', 'id = "TestMod."')), "id: 'TestMod.' is not 1 to 64 ASCII letters, digits, '.', '_' or '-', starting and ending with a letter or digit"),
    ("id with a leading dot", mod(replace=('id = "TestMod"', 'id = ".TestMod"')), "id: '.TestMod' is not 1 to 64 ASCII letters, digits, '.', '_' or '-', starting and ending with a letter or digit"),
    ("id with a space", mod(replace=('id = "TestMod"', 'id = "Test Mod"')), "id: 'Test Mod' is not 1 to 64 ASCII letters, digits, '.', '_' or '-', starting and ending with a letter or digit"),
    ("id with a trailing newline", mod(replace=('id = "TestMod"', 'id = "TestMod\\n"')), "id: 'TestMod\\n' is not 1 to 64 ASCII letters, digits, '.', '_' or '-', starting and ending with a letter or digit"),
    ("id longer than the path budget", mod(replace=('id = "TestMod"', f'id = "{"M" * 65}"')), "id: 'MMM"),

    # Links
    ("missing forums link", mod(replace=(FORUMS, 'repository = "https://github.com/a/b"')), "links: 'forums' is a required property"),
    ("forums link on another host", mod(replace=(FORUMS, 'forums = "https://example.com/t/1"')), "links.forums: 'https://example.com/t/1' is not an https link to a thread on forums.ahwoo.com"),
    ("forums link over http", mod(replace=(FORUMS, 'forums = "http://forums.ahwoo.com/threads/test-mod.1/"')), "links.forums: 'http://forums.ahwoo.com/threads/test-mod.1/' is not an https link to a thread on forums.ahwoo.com"),
    ("forums link to the forum root", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/"')), "links.forums: 'https://forums.ahwoo.com/' is not an https link to a thread on forums.ahwoo.com"),
    ("forums link to a category", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/forums/kitten-space-agency/mod-releases/"')), "links.forums: 'https://forums.ahwoo.com/forums/kitten-space-agency/mod-releases/' is not an https link to a thread on forums.ahwoo.com"),
    ("forums link to a member profile", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/members/nobody.42/"')), "links.forums: 'https://forums.ahwoo.com/members/nobody.42/' is not an https link to a thread on forums.ahwoo.com"),
    ("forums link with a control character in it", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/threads/my\\u001bmod.783/"')), "links.forums: 'https://forums.ahwoo.com/threads/my\\x1bmod.783/' is not an https link to a thread on forums.ahwoo.com"),
    ("a link that is not a URL", mod(replace=(FORUMS, FORUMS + '\nrepository = "github.com/a/b"')), "links.repository: 'github.com/a/b' is not an http or https URL, such as https://github.com/me/MyMod"),
    (
        "link key differing only in case",
        mod(replace=(FORUMS, FORUMS + '\nForums = "https://forums.ahwoo.com/threads/test-mod.2/"')),
        "links: 'Forums' and 'forums' are the same key",
    ),

    # Compatibility
    ("missing game_min", mod(replace=(GAME_MIN, 'game_max = "2026.8.5.5168"')), "compatibility: 'game_min' is a required property"),
    ("unknown compatibility key", mod(replace=(GAME_MIN, GAME_MIN + '\ngame_exact = "2026.8.3.5117"')), "compatibility: Additional properties are not allowed ('game_exact'"),
    ("game bound with a build suffix", mod(replace=("5117", "5117-LOCAL")), "compatibility.game_min: '2026.8.3.5117-LOCAL' is not a game version as the game shows it, such as 2026.10.10.5554, or a month such as 2026.10"),
    ("game bound as a year.month.build prefix", mod(replace=("2026.8.3.5117", "2026.8.3")), "compatibility.game_min: '2026.8.3' is not a game version as the game shows it, such as 2026.10.10.5554, or a month such as 2026.10"),
    ("game bound with a month above twelve", mod(replace=("2026.8.3.5117", "2026.13")), "compatibility.game_min: '2026.13' is not a game version as the game shows it, such as 2026.10.10.5554, or a month such as 2026.10"),
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
    ("since that is not a version", mod(append='\n[releases]\ngithub = "a/b"\nsince = "latest"\n'), "releases.since: 'latest' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1"),
    ("since with a leading v", mod(append='\n[releases]\ngithub = "a/b"\nsince = "v1.2"\n'), "releases.since: 'v1.2' is not a version"),
    ("since with four numbers", mod(append='\n[releases]\ngithub = "a/b"\nsince = "1.2.3.4"\n'), "releases.since: '1.2.3.4' is not a version"),
    ("since written as a number", mod(append='\n[releases]\ngithub = "a/b"\nsince = 1.2\n'), "releases.since: 1.2 is not of type 'string'"),
    ("since with no host", mod(append='\n[releases]\nsince = "1.2"\n'), "releases: {'since': '1.2'} is not valid under any"),
    ("since as the authority", mod(append='\n[releases]\ngithub = "a/b"\nsince = "1.2"\nauthority = "since"\n'), "releases.authority: 'since' is not one of"),
    ("an empty tag_prefix", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = ""\n'), "releases.tag_prefix: '' is not a non-empty ASCII string without whitespace"),
    ("a tag_prefix with a space", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = "gatos v"\n'), "releases.tag_prefix: 'gatos v' is not a non-empty ASCII string"),
    ("a tag_prefix with a trailing newline", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = "gatos-\\n"\n'), "releases.tag_prefix: 'gatos-\\n' is not a non-empty ASCII string"),
    ("a tag_prefix that is not ASCII", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = "gatos-\\u00e4"\n'), "is not a non-empty ASCII string"),
    ("a tag_prefix written as a number", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = 5\n'), "releases.tag_prefix: 5 is not of type 'string'"),
    ("a tag_prefix next to spacedock only", mod(append='\n[releases]\nspacedock = 4253\ntag_prefix = "gatos-v"\n'), "releases: 'github' is a dependency of 'tag_prefix'"),
    ("a tag_prefix with no host", mod(append='\n[releases]\ntag_prefix = "gatos-v"\n'), "releases: 'github' is a dependency of 'tag_prefix'"),
    (
        "github host that is not owner/repo",
        mod(append='\n[releases]\ngithub = "repository"\n'),
        ("releases.github: 'repository' does not match", "for example, use 'owner/repository'"),
    ),

    # Loader
    ("loader max below min", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.6"\nmax = "0.4.5"\n'), "loader: max '0.4.5' is below min '0.4.6'"),
    ("loader version with a leading v", mod(append='\n[loader]\nid = "StarMap"\nmin = "v0.4.5"\n'), "loader.min: 'v0.4.5' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1"),
    ("a bound pair that does not parse at all", mod(append='\n[loader]\nid = "StarMap"\nmin = "v0.4.6"\nmax = "0.4.6.1"\n'), "loader.min: 'v0.4.6' is not a version"),
    ("loader bound with four numbers", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5.1"\n'), "loader.min: '0.4.5.1' is not a version"),
    ("loader bound with a leading zero", mod(append='\n[loader]\nid = "StarMap"\nmin = "01.2"\n'), "loader.min: '01.2' is not a version"),
    ("a short loader max below its min", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.1"\nmax = "0.5"\n'), "loader: max '0.5' is below min '0.5.1'"),
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
    ("dependency bound with four numbers", mod(append='\n[[dependencies]]\nid = "A"\nkind = "required"\nmax = "1.0.0.0"\n'), "dependencies[0].max: '1.0.0.0' is not a version"),
    ("any_of alternative bound with a leading zero", mod(append='\n[[dependencies]]\nkind = "required"\nany_of = [{ id = "A", min = "1.02" }]\n'), "dependencies[0].any_of[0].min: '1.02' is not a version"),
    ("a short dependency max below its min", mod(append='\n[[dependencies]]\nid = "A"\nkind = "required"\nmin = "2"\nmax = "1.9"\n'), "dependencies[0]: max '1.9' is below min '2'"),
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
    ("install root as an absolute path", mod(append='\n[install]\nroot = "/etc/passwd"\n'), "install.root: '/etc/passwd' is not a relative path with / separators"),
    ("install root as a Windows path", mod(append='\n[install]\nroot = "C:/Windows"\n'), "install.root: 'C:/Windows' is not a relative path with / separators"),
    ("install root with a backslash separator", mod(append='\n[install]\nroot = "build\\\\TestMod"\n'), "install.root: 'build\\\\TestMod' is not a relative path with / separators"),
    ("install root under a home shortcut", mod(append='\n[install]\nroot = "~/mods"\n'), "install.root: '~/mods' is not a relative path with / separators"),
    ("install root hiding a parent segment", mod(append='\n[install]\nroot = "build/../../etc"\n'), "install.root: 'build/../../etc' is a path that leaves its anchor"),
    ("install root through a device name", mod(append='\n[install]\nroot = "build/NUL/x"\n'), "install.root: 'build/NUL/x' is a path through a reserved Windows device name"),
    ("a step that is not prose", mod(append="\n[install]\nsteps = [3]\n"), "install.steps[0]: 3 is not of type 'string'"),
    ("an install section that is not a table", mod(keys='install = "later"\n'), "install: 'later' is not of type 'object'"),
    ("a mod choosing where it installs", mod(append='\n[install]\ntarget = "game-root"\n'), "install.target: this key is not allowed here"),
    ("a mod naming the mods folder as its target", mod(append='\n[install]\ntarget = "mods"\n'), "install.target: this key is not allowed here"),
    ("a mod nesting itself below the anchor", mod(append='\n[install]\npath = "extras"\n'), "install.path: this key is not allowed here"),
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
    ("a configure key that cannot be addressed", loader(append=STANDALONE + '\n[provides.configure]\nfile = "c.json"\nformat = "json"\ngame-path = ""\n'), "provides.configure.game-path: '' is not key names joined by single dots, such as paths.game"),
    ("an instance table naming neither key", loader(append=INSTANCE), "provides.instance: {} should be non-empty"),
    ("an instance flag with whitespace", loader(append=INSTANCE + 'flag = "-Instance Path"\n'), "provides.instance.flag: '-Instance Path' is not a single token without whitespace or control characters"),
    ("an instance flag with a control character", loader(append=INSTANCE + 'flag = "-Instance\\u0001Path"\n'), "provides.instance.flag: '-Instance\\x01Path' is not a single token without whitespace or control characters"),
    ("an instance flag with a DEL character", loader(append=INSTANCE + 'flag = "-Instance\\u007fPath"\n'), "provides.instance.flag: '-Instance\\x7fPath' is not a single token without whitespace or control characters"),
    ("an instance variable with a C1 control character", loader(append=INSTANCE + 'variable = "STARMAP\\u009fPATH"\n'), "provides.instance.variable: 'STARMAP\\x9fPATH' is not a single token without whitespace or control characters"),
    ("an empty instance variable", loader(append=INSTANCE + 'variable = ""\n'), "provides.instance.variable: '' is not a single token without whitespace or control characters"),
    ("an instance variable that is not a string", loader(append=INSTANCE + "variable = 3\n"), "provides.instance.variable: 3 is not of type 'string'"),
    ("an unknown key inside instance", loader(append=INSTANCE + 'flag = "-InstancePath"\npath = "Instances"\n'), "provides.instance: Additional properties are not allowed ('path'"),
    ("an instance table on a mod", mod(append='\n[provides.instance]\nflag = "-InstancePath"\n'), "provides: this key is not allowed here"),
    ("a platform table on a mod", mod(append='\n[provides]\nlaunch = "TestMod.exe"\n\n[provides.platform.linux]\nlaunch = "TestMod.dll"\n'), "provides: this key is not allowed here"),
    ("a platform table on a pack", pack(append='\n[provides]\nlaunch = "x.exe"\n\n[provides.platform.linux]\nlaunch = "x.dll"\n'), "provides: this key is not allowed here"),
    ("a platform table without a launch", loader(append='\n[install]\ntarget = "game-root"\n\n[provides.platform.linux]\nlaunch = "x.dll"\n'), "provides: 'launch' is a dependency of 'platform'"),
    ("a platform table with no entry", loader(append=PLATFORM.replace(".linux]", "]")), "provides.platform: {} should be non-empty"),
    ("a platform entry without a launch", loader(append=PLATFORM + 'runtime = "dotnet"\n'), "provides.platform.linux: 'launch' is a required property"),
    ("an unknown platform", loader(append=PLATFORM.replace("linux", "freebsd") + 'launch = "x"\n'), "provides.platform: 'freebsd' is not one of ['windows', 'linux', 'macos']"),
    ("an unknown runtime", loader(append=PLATFORM + 'runtime = "mono"\nlaunch = "x.dll"\n'), "provides.platform.linux.runtime: 'mono' is not one of ['dotnet']"),
    ("an unknown key inside a platform entry", loader(append=PLATFORM + 'launch = "x.dll"\narguments = "-x"\n'), "provides.platform.linux: Additional properties are not allowed ('arguments'"),
    ("a platform entry that is not a table", loader(append=STANDALONE + '\n[provides.platform]\nlinux = "x.dll"\n'), "provides.platform.linux: 'x.dll' is not of type 'object'"),
    ("a platform launch that leaves the install location", loader(append=PLATFORM + 'launch = "../x.dll"\n'), "provides.platform.linux.launch: '../x.dll' is a path that leaves its anchor"),
    ("a platform launch as an absolute path", loader(append=PLATFORM + 'launch = "/usr/bin/dotnet"\n'), "provides.platform.linux.launch: '/usr/bin/dotnet' is not a relative path with / separators"),
    ("a platform launch through a device name", loader(append=PLATFORM + 'launch = "NUL"\n'), "provides.platform.linux.launch: 'NUL' is a path through a reserved Windows device name"),

    # License
    ("unbalanced parentheses in the license", mod(replace=('license = "MIT"', 'license = "(MIT OR Apache-2.0"')), "license: '(MIT OR Apache-2.0' has unbalanced parentheses"),
    ("a license closing a parenthesis it never opened", mod(replace=('license = "MIT"', 'license = "MIT)"')), "license: 'MIT)' has unbalanced parentheses"),
    ("a license closing before opening", mod(replace=('license = "MIT"', 'license = ")("')), "license: ')(' has unbalanced parentheses"),
    ("a license operator with no right side", mod(replace=('license = "MIT"', 'license = "MIT OR"')), "license: 'MIT OR' is not an SPDX license expression"),
    ("several licenses joined by a comma", mod(replace=('license = "MIT"', 'license = "GPL-2.0, CC BY-SA 4.0"')), "license: 'GPL-2.0, CC BY-SA 4.0' is not an SPDX license expression, such as MIT, or GPL-2.0-only AND CC-BY-SA-4.0 for several licenses"),

    # Images
    ("an unknown role in images", mod(append='\n[images]\nbanner = "x"\n'), "images: Additional properties are not allowed ('banner'"),
    ("more than one icon", mod(append=ICON.replace("[images.icon]", "[[images.icon]]")), "images.icon: [{"),
    ("an icon without a digest", mod(append=ICON.replace(ICON_DIGEST + "\n", "")), "images.icon: 'sha256' is a required property"),
    ("an unknown key on an image record", mod(append=ICON + 'caption = "x"\n'), "images.icon: Additional properties are not allowed ('caption'"),
    ("an icon carrying an id", mod(append=ICON + 'id = "icon"\n'), "images.icon.id: this key is not allowed here"),
    ("an image over http", mod(append=ICON.replace("https://", "http://")), "images.icon.url: 'http://example.invalid/icon.png' is not an https URL"),
    ("an image source over http", mod(append=ICON + 'source = "http://example.invalid/art"\n'), "images.icon.source: 'http://example.invalid/art' is not an https URL"),
    ("an image digest that is too short", mod(append=ICON.replace(ICON_DIGEST, 'sha256 = "abc"')), "images.icon.sha256: 'abc' is not a hex SHA-256 digest of 64 characters"),
    ("an icon below the pixel limit", mod(append=ICON.replace("width = 512", "width = 128")), "images.icon.width: 128 is less than the minimum of 256"),
    ("an icon above the pixel limit", mod(append=ICON.replace("height = 512", "height = 2049")), "images.icon.height: 2049 is greater than the maximum of 2048"),
    ("an icon above the byte cap", mod(append=ICON.replace("size = 48213", "size = 262145")), "images.icon.size: 262145 is greater than the maximum of 262144"),
    ("an image with a size of zero", mod(append=ICON.replace("size = 48213", "size = 0")), "images.icon.size: 0 is less than the minimum of 1"),
    ("an image license that is not an expression", mod(append=ICON + 'license = "MIT OR"\n'), "images.icon.license: 'MIT OR' is not an SPDX license expression"),
    ("an empty attribution", mod(append=ICON + 'attribution = ""\n'), "images.icon.attribution: '' should be non-empty"),
    ("a description image without an id", mod(append=SHOT.replace('id = "shot"\n', "")), "images.description[0]: 'id' is a required property"),
    ("a description image id starting with a dash", mod(append=SHOT.replace('id = "shot"', 'id = "-shot"')), "images.description[0].id: '-shot' is not 1 to 64 ASCII letters"),
    ("a description image id with a space", mod(append=SHOT.replace('id = "shot"', 'id = "the shot"')), "images.description[0].id: 'the shot' is not 1 to 64 ASCII letters"),
    ("a description image id above the length limit", mod(append=SHOT.replace('id = "shot"', f'id = "{"s" * 65}"')), "images.description[0].id: 'sss"),
    ("a description image above the pixel limit", mod(append=SHOT.replace("width = 1600", "width = 4096")), "images.description[0].width: 4096 is greater than the maximum of 2048"),
    ("a description image above the byte cap", mod(append=SHOT.replace("size = 402117", "size = 1048577")), "images.description[0].size: 1048577 is greater than the maximum of 1048576"),
    ("more than sixteen description images", mod(append=SHOT * 17), "images.description: [{"),

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
    ("a pack member pinned to a range", pack(replace=('version = "0.7.0"', 'version = "0.7"')), "mods[0].version: '0.7' is not a version with all three numbers, such as 1.2.0 or 2.0.0-rc.1, and no leading v"),
    ("a pack version with two numbers", pack(replace=('version = "1.0.0"', 'version = "1.0"')), "version: '1.0' is not a version with all three numbers, such as 1.2.0 or 2.0.0-rc.1, and no leading v"),
    ("an unknown key on a pack member", pack(replace=('version = "0.7.0"', 'version = "0.7.0"\nkind = "required"')), "mods[0]: Additional properties are not allowed ('kind'"),
    ("a pack pinning the same mod twice", pack(append='\n[[mods]]\nid = "advancedflightcomputer"\nversion = "0.8.0"\n'), "mods[1]: 'advancedflightcomputer' is pinned by mods[0]"),
    ("a pack pinning one id in two sections", pack(append='\n[[vehicles]]\nid = "AdvancedFlightComputer"\nversion = "0.8.0"\n'), "vehicles[0]: 'AdvancedFlightComputer' is pinned by mods[0]"),
    ("a pack pinning itself", pack(append='\n[[mods]]\nid = "TestPack"\nversion = "1.0.0"\n'), "mods[1]: a pack cannot pin itself"),
    ("a pack without a released_at", pack(replace=('released_at = "2026-08-05T12:00:00Z"\n', "")), "'released_at' is a required property"),
    ("a pack timestamp without a zone", pack(replace=("T12:00:00Z", "T12:00:00")), "released_at: '2026-08-05T12:00:00' is not a UTC date and time such as 2026-08-05T12:00:00Z"),
    ("a pack timestamp on no calendar", pack(replace=("2026-08-05T12:00:00Z", "2026-13-45T12:00:00Z")), "released_at: '2026-13-45T12:00:00Z' is not a real date"),

    # Vehicles and saves (RFC 0085), refused by the rollout gate and by their own rules
    ("a document without a type still needs links", MOD_KEYS.replace('type = "mod"\n', ""), "the document: 'links' is a required property"),
    ("a document without a type still needs compatibility", MOD_KEYS.replace('type = "mod"\n', ""), "the document: 'compatibility' is a required property"),
    ("a mod without links", MOD_KEYS + "\n[compatibility]\n" + GAME_MIN + "\n", "the document: 'links' is a required property"),
    ("a mod without compatibility", MOD_KEYS + "\n[links]\n" + FORUMS + "\n", "the document: 'compatibility' is a required property"),
    ("a mod without game_min", mod(replace=(GAME_MIN, 'game_max = "2026.9"')), "compatibility: 'game_min' is a required property"),
    ("a pack without links", PACK_KEYS + PACK_MEMBER + "\n[compatibility]\n" + GAME_MIN + "\n", "the document: 'links' is a required property"),
    ("a vehicle with a loader", VEHICLE + '\n[loader]\nid = "StarMap"\nmin = "0.4"\n', "loader: this key is not allowed here"),
    ("a vehicle that provides something", VEHICLE + '\n[provides]\nlaunch = "x.exe"\n', "provides: this key is not allowed here"),
    ("a vehicle with a version", VEHICLE + 'version = "1.0.0"\n', "version: this key is not allowed here"),
    ("a vehicle with a release timestamp", VEHICLE + 'released_at = "2026-08-05T12:00:00Z"\n', "released_at: this key is not allowed here"),
    ("a vehicle with a changelog", VEHICLE + 'changelog = "x"\n', "changelog: this key is not allowed here"),
    ("a vehicle pinning mods", VEHICLE + PACK_MEMBER, "mods: this key is not allowed here"),
    ("a vehicle pinning vehicles", VEHICLE + '\n[[vehicles]]\nid = "A"\nversion = "1.0.0"\n', "vehicles: this key is not allowed here"),
    ("a vehicle pinning saves", VEHICLE + '\n[[saves]]\nid = "A"\nversion = "1.0.0"\n', "saves: this key is not allowed here"),
    ("a vehicle with an install target", VEHICLE + '\n[install]\ntarget = "user-data"\n', "install.target: this key is not allowed here"),
    ("a vehicle with an install path", VEHICLE + '\n[install]\npath = "Vehicles"\n', "install.path: this key is not allowed here"),
    ("a vehicle with install manages", VEHICLE + '\n[install]\nmanages = ["vehicle.xml"]\n', "install.manages: this key is not allowed here"),
    ("a vehicle with an install folder", VEHICLE + '\n[install]\nfolder = "Test Rover"\n', "install: Additional properties are not allowed ('folder' was unexpected)"),
    ("a save with a loader", VEHICLE.replace('type = "vehicle"', 'type = "save"') + '\n[loader]\nid = "StarMap"\nmin = "0.4"\n', "loader: this key is not allowed here"),
]

# Vehicles and saves that their own rules accept. While the rollout gate holds
# their type, the gate line is their only error, and without the gate they pass.
GATED_ACCEPTED = [
    ("a minimal vehicle", VEHICLE),
    ("a minimal save", VEHICLE.replace('type = "vehicle"', 'type = "save"')),
    ("a vehicle with a forums link and a dependency", VEHICLE + "\n[links]\n" + FORUMS + '\n\n[[dependencies]]\nid = "TestMod"\nkind = "required"\nmin = "1.4"\n'),
    ("a vehicle with links but no forums thread", VEHICLE + '\n[links]\nrepository = "https://github.com/a/b"\n'),
    ("a vehicle with only game_max", VEHICLE + '\n[compatibility]\ngame_max = "2026.7.5.4892"\n'),
    ("a vehicle with the install keys it may have", VEHICLE + '\n[install]\nroot = "Test Rover"\nsteps = ["Open the vehicle in the editor."]\nuninstall = []\n'),
    ("a vehicle with a host, tags, an icon and every dependency kind", VEHICLE + 'tags = ["rover"]\nstatus = "deprecated"\nsuperseded_by = "TestRover2"\n\n[releases]\ngithub = "a/b"\ntag_prefix = "TestRover-v"\n\n[[dependencies]]\nkind = "recommends"\nany_of = [{ id = "A" }, { id = "B" }]\n' + ICON),
]

# Small positive variations that would be wasteful as their own file.
ACCEPTED = [
    ("a mod with no releases section", MOD),
    ("since in its short form", mod(append='\n[releases]\ngithub = "a/b"\nsince = "1.2"\n')),
    ("since as a pre-release", mod(append='\n[releases]\ngithub = "a/b"\nsince = "0.5.0-rc.1"\n')),
    ("since next to two hosts and an authority", mod(append='\n[releases]\ngithub = "a/b"\nspacedock = 4253\nauthority = "spacedock"\nsince = "1"\n')),
    ("a tag_prefix next to github", mod(append='\n[releases]\ngithub = "a/b"\ntag_prefix = "gatos-v"\nsince = "1.1"\n')),
    ("a tag_prefix for a github mirror", mod(append='\n[releases]\ngithub = "a/b"\nspacedock = 4253\nauthority = "spacedock"\ntag_prefix = "gatos-"\n')),
    ("a deprecated mod with a successor", mod(keys='status = "deprecated"\nsuperseded_by = "TestModNG"\n')),
    ("a month as the lower bound", mod(replace=(GAME_MIN, 'game_min = "2026.7"'))),
    ("two month bounds in order", mod(replace=(GAME_MIN, 'game_min = "2026.7"\ngame_max = "2026.8"'))),
    ("a month bound against a revision bound", mod(replace=(GAME_MIN, 'game_min = "2026.9"\ngame_max = "2026.7.5.4892"'))),
    ("an empty steps list", mod(append="\n[install]\nsteps = []\n")),
    ("an instance table naming both keys", loader(append=INSTANCE + 'flag = "-InstancePath"\nvariable = "STARMAP_INSTANCE_PATH"\n')),
    ("an instance table naming only the flag", loader(append=INSTANCE + 'flag = "-InstancePath"\n')),
    ("an instance table naming only the variable", loader(append=INSTANCE + 'variable = "STARMAP_INSTANCE_PATH"\n')),
    ("a platform entry run by dotnet", loader(append=PLATFORM + 'runtime = "dotnet"\nlaunch = "StarMap.dll"\n')),
    ("a platform entry with its own executable", loader(append=PLATFORM + 'launch = "bin/StarMap"\n')),
    ("an entry for every platform", loader(append=STANDALONE + '\n[provides.platform.windows]\nlaunch = "StarMap.exe"\n\n[provides.platform.linux]\nruntime = "dotnet"\nlaunch = "StarMap.dll"\n\n[provides.platform.macos]\nruntime = "dotnet"\nlaunch = "StarMap.dll"\n')),
    ("a pre-release loader bound", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.0-rc.1"\n')),
    ("a pre-release ordered below its release", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5.0-rc.1"\nmax = "0.5.0"\n')),
    ("a numeric pre-release below an alphanumeric one", mod(append='\n[loader]\nid = "StarMap"\nmin = "1.0.0-1"\nmax = "1.0.0-alpha"\n')),
    ("build metadata on a bound", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4.5+build.7"\nmax = "0.4.5"\n')),
    ("short loader and dependency bounds", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.4"\n\n[[dependencies]]\nid = "A"\nkind = "required"\nmin = "1"\n')),
    ("a short bound equal to its full form", mod(append='\n[loader]\nid = "StarMap"\nmin = "0.5"\nmax = "0.5.0"\n')),
    ("a short pre-release bound below its release", mod(append='\n[loader]\nid = "StarMap"\nmin = "1.2-rc.1"\nmax = "1.2"\n')),
    ("build metadata on a short bound", mod(append='\n[loader]\nid = "StarMap"\nmin = "1.2+build.7"\nmax = "1.2.0"\n')),
    ("short bounds on an any_of alternative", mod(append='\n[[dependencies]]\nkind = "recommends"\nany_of = [{ id = "A", min = "1", max = "1.4" }]\n')),
    ("a compound license expression", mod(replace=('license = "MIT"', 'license = "(MIT OR Apache-2.0) AND CC0-1.0"'))),
    ("several licenses joined with AND", mod(replace=('license = "MIT"', 'license = "GPL-2.0-only AND CC-BY-SA-4.0"'))),
    ("a license exception", mod(replace=('license = "MIT"', 'license = "GPL-2.0-or-later WITH Bison-exception-2.2"'))),
    ("a custom license reference", mod(replace=('license = "MIT"', 'license = "LicenseRef-Kitten-1.0"'))),
    ("a dotted id", mod(replace=('id = "TestMod"', 'id = "Kitten.Tools"'))),
    ("an id that starts like a reserved name", mod(replace=('id = "TestMod"', 'id = "CONtrol"'))),
    ("an id at the length limit", mod(replace=('id = "TestMod"', f'id = "{"M" * 64}"'))),
    ("a path segment that starts like a device", mod(append='\n[install]\nroot = "console/TestMod"\n')),
    ("a dependency on a mod named like a reserved stem", mod(append='\n[[dependencies]]\nid = "Nullify"\nkind = "optional"\n')),
    ("a link key the format does not name", mod(replace=(FORUMS, FORUMS + '\ndiscord = "https://discord.gg/abc"'))),
    ("a forums thread under its node path", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/forums/kitten-space-agency/mod-releases/test-mod.1/"'))),
    ("a forums thread named by its id alone", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/threads/1/"'))),
    ("a forums thread link that opens a page", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/threads/test-mod.1/page-2"'))),
    ("a forums thread link to a post in it", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/threads/test-mod.1/post-42"'))),
    ("a forums thread in the index.php form", mod(replace=(FORUMS, 'forums = "https://forums.ahwoo.com/index.php?threads/test-mod.1/"'))),
    ("a native TOML timestamp in a pack", pack(replace=('released_at = "2026-08-05T12:00:00Z"', "released_at = 2026-08-05T12:00:00Z"))),
    ("a mod with an icon and a description image", mod(append=ICON + SHOT)),
    ("an image under its own license with credit", mod(append=ICON + 'license = "CC-BY-4.0"\nattribution = "Artwork by Example Artist"\nsource = "https://example.invalid/art"\n')),
    ("an image digest in upper case", mod(append=ICON.replace("a" * 64, "A" * 64))),
    ("an icon at both pixel limits", mod(append=ICON.replace("width = 512\nheight = 512", "width = 1024\nheight = 1024").replace("size = 48213", "size = 262144"))),
    ("a wide icon at the pixel limits", mod(append=ICON.replace("width = 512\nheight = 512", "width = 2048\nheight = 1024"))),
    ("a tall icon at the pixel limits", mod(append=ICON.replace("width = 512\nheight = 512", "width = 256\nheight = 2048"))),
    ("sixteen description images", mod(append="".join(SHOT.replace('"shot"', f'"shot-{index}"') for index in range(16)))),
    ("a loader with an icon", loader(append=ICON)),
    ("a pack with an icon", pack(append=ICON)),
]


def failures_for(text, checker):
    """Run the whole check over one in-memory document."""
    errors = []
    document = check_schema.normalise(tomllib.loads(text))
    check_schema.check_parsed("<case>", document, checker, errors)
    return errors


def untitled_patterns(node, where="#"):
    """The places of every pattern that says its rule neither in a title nor by an example.

    The report shows the title of a refused pattern, or its first example, so a
    pattern with neither would put the bare regex in front of the author.
    """
    found = []
    if isinstance(node, dict):
        if "pattern" in node and "title" not in node and "examples" not in node:
            found.append(where)
        for key, value in node.items():
            found.extend(untitled_patterns(value, f"{where}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(untitled_patterns(value, f"{where}/{index}"))
    return found


def main():
    checker = check_schema.validator()
    failures = []
    checked = 0

    checked += 1
    for where in untitled_patterns(checker.schema):
        failures.append(f"the pattern at {where} has no title and no example")

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

    schema = copy.deepcopy(checker.schema)
    gate = schema["properties"]["type"].pop("not", None)
    ungated = Draft202012Validator(schema)
    for name, text in GATED_ACCEPTED:
        checked += 1
        content_type = tomllib.loads(text)["type"]
        errors = failures_for(text, checker)
        if gate and content_type in gate["enum"]:
            if errors != [f"<case>: type: '{content_type}' {GATE}"]:
                failures.append(f"'{name}' should be refused by the gate alone, but: " + "; ".join(errors))
        elif errors:
            failures.append(f"'{name}' should be accepted, but: " + "; ".join(errors))
        errors = failures_for(text, ungated)
        if errors:
            failures.append(f"'{name}' should be accepted without the gate, but: " + "; ".join(errors))

    seen = set()
    for name, text, expected in REJECTED:
        checked += 1
        assert name not in seen, f"two cases are both called '{name}'"
        seen.add(name)
        errors = failures_for(text, checker)
        fragments = (expected,) if isinstance(expected, str) else expected
        if not errors:
            failures.append(f"'{name}' should be rejected, but nothing complained")
        elif not any(all(fragment in error for fragment in fragments) for error in errors):
            failures.append(f"'{name}' should be rejected for {fragments}, but said: " + "; ".join(errors))

    if failures:
        print("\n".join(failures))
        print(f"\n{len(failures)} of {checked} case(s) failed")
        return 1

    print(f"checked {checked} case(s), all behave as specified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
