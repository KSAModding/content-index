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

# The links and numbers in the texts. A test compares them with the checks,
# which explain.py does not import, because decide.py runs it with no
# packages installed.
PAGE = "https://ksamodding.github.io/content-index/"
GUIDE = "https://github.com/KSAModding/content-index/blob/main/CONTRIBUTING.md"
MOD_RELEASES = "https://forums.ahwoo.com/forums/kitten-space-agency/mod-releases/"
SPDX = "https://spdx.org/licenses/"
RELEASE_FOLDERS = "https://github.com/KSAModding/content-index-releases/tree/main/releases"

RECORD = f"[the listing page]({PAGE}) or `tools/image_record.py`"
AGAIN = " Then make its record again with " + RECORD + "."

# The groups whose pattern allows only characters that are safe in a link or a
# code span, so a template gets them as they are.
PLAIN = ("repository", "image")

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
    # A host name that is not found is often a typo in the url.
    (
        re.compile(
            r"^\S+: (?P<place>images\.[^:\s]+): \S+ (?:does not resolve: |resolves to no address)"
        ),
        "The host name in the url of {place} is not found. Check the spelling of the address, "
        "and fix the url when it is wrong. If it is right, the host can be down for a short "
        "time.",
        False,
    ),
    # Lines about the run itself, not about the listing. A release host that
    # answers HTTP 4xx can mean a mod that is not published, so it gets no text.
    (
        re.compile(
            r"^\S+: (?:(?:github|spacedock):\S+|the latest release .+?) could not be read: "
            r"(?!.*HTTP 4\d\d$)"
            r"|^\S+: the stamper behaved unexpectedly: "
            r"|^the stamper (?:is not at |at .+ does not import)"
            r"|^the game release list at .+ is not readable"
            r"|^\S+: images\.[^:\s]+: (?:"
            r"\S+ did not answer: |\S+ answered HTTP (?:5\d\d|408|425|429)(?:$|\.)"
            r"|the image check behaved unexpectedly: )"
            r"|^the pins could not be checked: "
            r"|^a check raised "
            r"|^\S+: which release this edit reaches could not be read: "
        ),
        "This is a problem on the host or in the bot, not in your listing, so nothing has to "
        "change for it. The next run checks it again.",
        True,
    ),
    (
        re.compile(r"^not inspected: the document has to pass layout and schema first"),
        "This is not a pass. The images and the release are checked only after the errors "
        "under What has to change are fixed, so these checks can still find something after "
        "your push.",
        False,
    ),
    # The release on GitHub or SpaceDock.
    (
        re.compile(
            r"^\S+: (?:github|spacedock):\S+ offers \d+ release\(s\) and none of them carries a "
            r"version the index can read"
        ),
        "The index takes the version of a release from its tag on GitHub or from its version "
        "on SpaceDock, and no release there has a version it can read. Publish a release whose "
        "tag is the version, such as `1.2.3` or `v1.2.3`, with the mod as a zip. Names such as "
        "`release-1` or `Beta` are not versions.",
        True,
    ),
    (
        re.compile(RELEASE + r"the archive's (?P<path>\S+) is not valid TOML, "),
        "This error is in {path} inside the zip of release {tag}, not in the listing. Fix it at "
        "the line and column the message names, or save the file as UTF-8 when the message "
        "names a byte, and make a new zip. " + REPLACE,
        True,
    ),
    (
        re.compile(RELEASE + r"the archive is not a readable zip"),
        "The file of release {tag} is not a zip that the index can open, for example a .rar "
        "or .7z file with its name changed to .zip, or an upload that stopped early. Pack "
        "the mod folder as a zip again. " + REPLACE,
        True,
    ),
    (
        re.compile(
            r"^\S+: (?:install\.(?:target|path): this key is not allowed here|the latest release "
            r".+? cannot be stamped: a mod cannot author an install target or path)"
        ),
        "A mod always goes into the mods folder of the game, in a folder named after its id, "
        "so its listing cannot choose where it goes. Remove target and path from `[install]`, "
        "and remove `[install]` completely when nothing is left in it.",
        False,
    ),
    (
        re.compile(RELEASE + r"the authored install root '(?P<root>[^']*)' is not in the archive"),
        "install.root in the listing names the folder {root}, and the zip of release {tag} has "
        "no such folder. Most mods need no install.root: remove it, and the index uses the one "
        "folder at the top of the zip that is named after the id. Otherwise, write the path of "
        "the mod folder exactly as it is in the zip.",
        False,
    ),
    (
        re.compile(
            RELEASE + r"(?P<which>game_min|game_max) '(?P<bound>[^']*)' names a month with "
            r"no build in the game release list"
        ),
        "{which} in `[compatibility]` is the month {bound}, and no game version came out in "
        "that month. Write a month that has a game version, or the full game version as the "
        "game shows it, such as `2026.10.10.5554`.",
        False,
    ),
    (
        re.compile(r"^\S+: the authority host has no repository '(?P<repo>[^']*)'"),
        "The index cannot read the GitHub repository {repo}. Check releases.github in the "
        "listing: it is the owner and the name from the address `github.com/<owner>/<name>`, "
        "spelled the same way. If the name is right, make the repository public, then close "
        "and reopen this pull request.",
        False,
    ),
    (
        re.compile(r"SpaceDock has no mod (?P<mod>\d+)"),
        "SpaceDock has no mod with the number {mod}. releases.spacedock is the number in the "
        "address of your mod page, such as 1234 in `spacedock.info/mod/1234/My-Mod`. Check that "
        "number in the listing.",
        False,
    ),
    (
        re.compile(r"^\S+: (?:github|spacedock):\S+ has no release yet$"),
        "The listing can still merge. Players can install the mod only after it has a "
        "published release with the mod as a zip, and a tag alone or a draft release does not "
        "count. The index finds that release on its own.",
        False,
    ),
    (
        re.compile(r"^\S+: the listing names no release host, so releases enter by pull request"),
        "Without a `[releases]` section, the index does not find new releases of the mod on its "
        "own, and each release needs its own pull request to content-index-releases. To let "
        "the index find them, add `[releases]` with `github = \"owner/repository\"` or "
        "`spacedock = <number of the mod on SpaceDock>`.",
        False,
    ),
    # The images of a listing.
    (
        re.compile(
            r"^\S+: (?P<place>images\.[^:\s]+): "
            r"https://\S*(?:X-Amz-|[?&](?:Expires|Signature)=)\S* answered HTTP 4\d\d"
        ),
        "This is a short-lived download link, such as the link of a forum attachment, and it "
        "stops working after a few minutes. Put the image into the GitHub repository of the mod "
        "and use its raw.githubusercontent.com address, with a commit in the address and not a "
        "branch such as main." + AGAIN,
        False,
    ),
    (
        re.compile(
            r"^\S+: (?P<place>images\.[^:\s]+): \S+ answered HTTP 4(?:04|10), so the image is not "
            r"there"
        ),
        "Nothing is at the url of {place}: the file was moved, renamed or deleted, or the "
        "address has a typo. Open the address in a private browser window to test it, then fix "
        "the url in {place}, and make the record again if the file changed.",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?P<place>images\.[^:\s]+): \S+ answered HTTP (?P<status>4(?!08|25|29)\d\d)"
            r"(?:$|\.)"
        ),
        "The host of the image for {place} refused the download (HTTP {status}). Some hosts "
        "block programs that are not a browser, or need a login. Put the image where anyone "
        "can download it, such as the GitHub repository of the mod, and use its "
        "raw.githubusercontent.com address.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<place>images\.[^:\s]+): the bytes are not PNG, JPEG or WebP"),
        "The url of {place} gives something that is not a PNG, JPEG or WebP image. Often it is "
        "a web page that shows the image, such as a `github.com/<owner>/<name>/blob/...` "
        "address: use the raw.githubusercontent.com address of the file instead, which the Raw "
        "button on GitHub opens. Save a GIF or SVG image as PNG, JPEG or WebP first.",
        False,
    ),
    (
        re.compile(
            r"^\S+: images\.icon(?:\.(?:width|height): \d+ is (?:less|greater) than the "
            r"(?:minimum|maximum) of \d+|: (?:.*; )?\d+ by \d+ pixels is outside the limits)"
        ),
        "An icon needs a shorter side of 256 to 1024 pixels, and a longer side of at most twice "
        "the shorter side. A square of 512 by 512 pixels is best, because clients show only the "
        "square in the center. Resize the icon, upload it again, and make its record again "
        "with " + RECORD + ".",
        False,
    ),
    (
        re.compile(
            r"^\S+: images\.[^:\s]+?(?:\.size: \d+ is greater than the maximum of \d+|: \S+ is \d+ "
            r"bytes, above the cap of \d+|: \S+ is larger than the cap of \d+ bytes)"
        ),
        "The image file is too large: an icon can have at most 256 KiB (262144 bytes), and a "
        "description image at most 1 MiB (1048576 bytes). Make the image smaller in pixels, or "
        "save it as JPEG or WebP, upload it again, and make its record again with "
        + RECORD + ".",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?P<place>images\.[^:\s]+): (?!.*(?:is animated|per side))(?:.*; )?"
            r"(?:width|height|size|sha256) is \S+ and the bytes show "
        ),
        "The image at the url of {place} is not the file that its record describes: the file "
        "changed after the record was made, or a value was typed by hand. Make the record "
        "again with " + RECORD + " and replace the old one. When the image is on GitHub, use "
        "an address with a commit in it and not a branch such as main, so the file cannot "
        "change later.",
        False,
    ),
    (
        re.compile(
            r"^\S+: images\.icon: the icon is \d+ by \d+ pixels, so clients show the square from"
        ),
        "Nothing has to change for this. Clients show only the square in the center of the "
        "icon. If that cuts off something important, use a square icon, best 512 by 512 pixels.",
        False,
    ),
    (
        re.compile(
            r"^\S+: images\.description\[\d+\]: nothing in the description references "
            r"'(?P<image>[A-Za-z0-9_-]+)'"
        ),
        "Clients show a description image only where the description names it. Write "
        "`![short text](ksa-image:{image})` in description at the place where the image goes.",
        False,
    ),
    (
        re.compile(
            r"^\S+: description: 'ksa-image:(?P<image>[A-Za-z0-9_-]+)' names no record in "
            r"\[\[images\.description\]\]"
        ),
        "The description shows `ksa-image:{image}`, and no `[[images.description]]` record "
        "has `id = \"{image}\"`. Add that record with " + RECORD + ", or fix the spelling of "
        "the id in the description.",
        False,
    ),
    # The listing file, from the TOML through the layout to the schema.
    (
        re.compile(
            r"^.+?\.toml: not valid TOML, (?:Cannot overwrite a value|Cannot declare .* twice)"
        ),
        "The file sets a key or a section twice, which TOML does not allow. Look at the line "
        "the message names, and keep one of the two. Only sections in double brackets, such as "
        "`[[dependencies]]`, can repeat.",
        False,
    ),
    (
        re.compile(r"^.+?\.toml: not valid TOML, "),
        "The file is not valid TOML, so the other checks cannot read it. Look at the line and "
        "column in the message: text needs straight double quotes, such as "
        "`name = \"My Mod\"`, and every quote and bracket must be closed. "
        f"[The listing page]({PAGE}) writes a valid file for you.",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?:links: 'forums' is a required property|the document: 'links' is a required "
            r"property|links\.forums: .* is not an https link to a thread on forums\.ahwoo\.com)"
        ),
        "Every listing needs a link to a thread about the mod on the KSA forums. Open a thread "
        f"in [Mod Releases]({MOD_RELEASES}), then write its address under `[links]`, such "
        "as `forums = \"https://forums.ahwoo.com/threads/my-mod.783/\"`. A link to your profile "
        "or to a forum section does not count.",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?:the document: 'compatibility'|compatibility: 'game_min') is a required "
            r"property"
        ),
        "Every listing names the oldest game version that the mod works with. Add a "
        "`[compatibility]` section with game_min, such as `game_min = \"2026.10.10.5554\"` "
        "(the version as the game shows it) or `game_min = \"2026.10\"` (a month).",
        False,
    ),
    (
        re.compile(
            r"^\S+: the document: '(?P<key>spec_version|id|type|name|authors|abstract|license|"
            r"version|released_at)' is a required property"
        ),
        "The file has no {key}, and it needs one. Write it near the top of the file, before the "
        "first line in square brackets such as `[links]`, because TOML puts every key below "
        f"such a line into that section. [The listing page]({PAGE}) writes every needed key "
        "for you.",
        False,
    ),
    (
        re.compile(
            r"^listings/(?P<stem>[^/]+)\.toml: declares id '(?P<id>[^']*)', so the file name must "
            r"be '(?P<expected>[^']*)'"
        ),
        "The id and the file name must be the same, letter for letter, and the id is also the "
        "name of the mod folder in the zip. Check which one is right, then rename the file to "
        "{expected}, or change id to {stem}.",
        False,
    ),
    (
        re.compile(r"^packs/[^/]+/[^/]+\.toml: declares version '[^']*', the file name says"),
        "The file name and the version inside must be the same. To publish a new version of a "
        "pack, do not change the old file: add a new file `packs/<id>/<new version>.toml` next "
        "to it, with that version inside.",
        False,
    ),
    (
        re.compile(r"an accepted pack version is immutable"),
        "A pack version that is in the index never changes, so this pull request cannot edit, "
        "rename or delete it. Undo the change to that file, and add the new version as a new "
        "file `packs/<id>/<new version>.toml`. Push to this pull request, you do not need a "
        "new one.",
        False,
    ),
    (
        re.compile(
            r"^\S+: compatibility\.(?P<which>game_min|game_max): '(?P<value>[^']*)' (?:does not "
            r"match|is not )"
        ),
        "A leading v, a version with three numbers, or the version of the mod does not work in "
        "{which}.",
        False,
    ),
    (
        re.compile(
            r"^\S+: releases\.github: 'https?://(?:www\.)?github\.com/(?P<wanted>[A-Za-z0-9._-]+/"
            r"[A-Za-z0-9._-]+?)(?:\.git)?/?' (?:does not match|is not )"
        ),
        "releases.github takes only the owner and the name of the repository, not the whole "
        "address. Change it to {wanted}, without https://github.com/ in front.",
        False,
    ),
    (
        re.compile(r"^\S+: releases\.github: '[^']*' (?:does not match|is not )"),
        "releases.github is the owner and the name of the GitHub repository with / between "
        "them, as in the address `github.com/<owner>/<name>`, such as `me/MyMod`. Nothing else "
        "goes there: no https://, no branch and no spaces.",
        False,
    ),
    (
        re.compile(
            r"^\S+: links\.[^:\s]+: (?:(?:'[^']*'|\"[^\"]*\") (?:does not match|is not )"
            r"|.* is not of type 'string')"
        ),
        "Each key under `[links]` is a full web address that starts with https://, such as "
        "`https://github.com/me/MyMod`, with no spaces. A key that is not a link, such as "
        "abstract, does not belong there: move it above the `[links]` line.",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?:id|superseded_by|loader\.id|dependencies\[\d+\](?:\.any_of\[\d+\])?\.id|"
            r"mods\[\d+\]\.id): '[^']*' (?:does not match|is not )"
        ),
        "The id of a mod is also the name of its folder in the zip, letter for letter, so it "
        "has no spaces, such as `MyMod` or `My.Mod`.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<field>\S+): \{.*\} is not of type 'array'"),
        "{field} is a list of entries, but the file gives it a single entry. Start each entry "
        "with a line in double brackets, such as `[[dependencies]]` or `[[images.description]]`, "
        "not single ones. An entry in curly braces on one line needs square brackets around it, such as "
        "`mods = [{{ id = \"Lib\", version = \"1.0.0\" }}]`.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<field>\S+): (?!\{).* is not of type 'array'"),
        "{field} is a list in square brackets, even with one entry, such as "
        "`authors = [\"Me\"]`.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<field>\S+): .* is not of type 'integer'"),
        "{field} is a whole number without quotes, such as `spacedock = 1234`.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<field>\S+): .* is not of type 'string'"),
        "{field} is text in double quotes, such as `min = \"1.0\"` or `name = \"My Mod\"`.",
        False,
    ),
    (
        re.compile(r"^\S+: (?P<field>version|released_at|changelog): this key is not allowed here"),
        "A listing of a mod has no {field}, because every release takes its version, date and "
        "changes from the release on GitHub or SpaceDock. Remove {field} from the listing.",
        False,
    ),
    (
        re.compile(
            r"^\S+: the document: Additional properties are not allowed "
            r"\((?P<keys>.+) (?:was|were) unexpected\)"
        ),
        "The format has no key {keys} at the top of the file. Check the spelling in "
        f"[the guide]({GUIDE}). A link such as a homepage goes under `[links]` instead, such "
        "as `homepage = \"https://example.com\"`.",
        False,
    ),
    (
        re.compile(
            r"^\S+: releases: (?:.* is not valid under any of the given schemas"
            r"|'(?:authority|github|spacedock)' is a required property)"
        ),
        "`[releases]` names where the releases of the mod are: `github = \"owner/repository\"`, "
        "`spacedock = <number of the mod on SpaceDock>`, or both. With both, add "
        "`authority = \"github\"` or `authority = \"spacedock\"` to say which one counts, and "
        "authority must name a host that is there. Remove `[releases]` when the mod has no "
        "release host.",
        False,
    ),
    (
        re.compile(r"^\S+: dependencies\[\d+\]: 'kind' is a required property"),
        "Each `[[dependencies]]` entry needs a kind: `required`, `optional`, `recommends`, "
        "`suggests` or `conflict`. For a mod that must be there, write `kind = \"required\"`.",
        False,
    ),
    (
        re.compile(
            r"^\S+: images\.(?:icon|description\[\d+\]): '(?:url|sha256|width|height|size)' is a "
            r"required property"
        ),
        "An image record needs url, sha256, width, height and size, and you do not have to "
        "find them yourself: " + RECORD + " measures the image and writes the whole record "
        "for you to copy.",
        False,
    ),
    (
        re.compile(
            r"^\S+: (?:images\.[^:\s]+\.)?license: '.*' (?:is not an SPDX license expression|does "
            r"not parse as an SPDX license expression|names .*, which is not on the SPDX license "
            r"list|has two license identifiers with no operator)"
        ),
        f"Write each license as its short id from [the SPDX list]({SPDX}), with its version, "
        "such as `MIT`, `Apache-2.0`, `GPL-3.0-only` or `CC-BY-SA-4.0`. Join two licenses with "
        "AND when both apply, or with OR when the user can choose, never with a comma. For "
        "terms that are not on the list, such as All rights reserved, write LicenseRef- and a "
        "name, such as `LicenseRef-AllRightsReserved`.",
        False,
    ),
    # The listing against the rest of the index.
    (
        re.compile(
            r"^\S+: the id '(?P<id>[^']*)' is already held by (?P<other>\S+), and ids compare "
            r"case-insensitively"
        ),
        "This file and {other} have the same id, because ids that differ only in capital "
        "letters count as the same. If both are your mod, keep the file that is already in the "
        "index and change it instead of adding a new one. If not, give the new one another id. "
        "Then rename its file, or the folder of a pack, to match, and for a mod also the folder "
        "in the zip.",
        False,
    ),
    (
        re.compile(
            r"^\S+: dependencies\[\d+\](?:\.any_of\[\d+\])?: '(?P<loader>[^']*)' is listed as a "
            r"mod-loader, and a dependency has to be a mod"
        ),
        "{loader} is a mod loader, and the loader of a mod goes into `[loader]`, not into "
        "`[[dependencies]]`. Remove this entry, and add a `[loader]` section with id set to the "
        "id of that loader, spelled exactly as the name of its file in listings, such as "
        "`StarMap`, and min set to the oldest version of it that works.",
        False,
    ),
    (
        re.compile(
            r"^\S+: mods\[\d+\]: '(?P<id>[^']*)' is not a listed mod, and a pack pins only listed "
            r"mods"
        ),
        "A pack can hold only mods that have a listing in the index, under the same id. Check "
        "the spelling of {id}, or wait until its listing is in the index.",
        False,
    ),
    (
        re.compile(r"^\S+: mods\[\d+\]: '(?P<id>[^']*)' has no stamped release (?P<version>\S+)"),
        "The index has no release {version} of {id}. Write a version that is in the index, "
        "with all three numbers, such as `1.2.0` for a release tagged v1.2. The versions are "
        f"the file names in the folder of the mod in [the release files]({RELEASE_FOLDERS}).",
        False,
    ),
    (
        re.compile(r"^\S+: links\.forums: thread \d+ is also the forums thread of "),
        "Nothing has to change for this. Mods of one family can share a forum thread, but a "
        "thread of its own for each mod is better: when two people want the same id, the thread "
        "shows who listed the mod first.",
        False,
    ),
    (
        re.compile(r"^\S+: abstract: \d+ characters is longer than \d+"),
        "Nothing has to change for the merge. The abstract is the short text in lists and "
        "search results, so keep it to one or two sentences of at most 280 characters, and put "
        "the rest into description.",
        False,
    ),
    (
        re.compile(
            r"^\S+: the change to .+? reaches `(?P<version>[^`]+)`, the newest release, with the "
            r"next watcher tick after the merge"
        ),
        "Nothing has to change for this. In short: about ten minutes after the merge, the index "
        "copies this change into release {version}, and older releases keep their old values.",
        False,
    ),
    # The lines of the reason why ownership is not verified.
    (
        re.compile(r"SpaceDock mod (?P<mod>\d+) has no source code link"),
        "Edit SpaceDock mod {mod} and set its source code link to the GitHub repository of the "
        "mod, such as `https://github.com/<owner>/<name>`. Then put the proof on that "
        "repository, as the paragraph above says.",
        True,
    ),
    (
        re.compile(
            r"the source code link of SpaceDock mod (?P<mod>\d+) does not name a GitHub repository"
        ),
        "The source code link of SpaceDock mod {mod} must be the address of a GitHub "
        "repository, such as `https://github.com/<owner>/<name>`, not a profile, a file or "
        "another site. Change it on SpaceDock, then put the proof on that repository.",
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
    for key in PLAIN:
        if found.get(key) is not None:
            values[key] = found[key]
    return values


def _code(value):
    """The value as inline code that no character of it can break out of."""
    return "`" + re.sub(r"[`\r\n]", "", value) + "`"
