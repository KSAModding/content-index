# Schemas

`authored.schema.json` is the machine-readable form of the authored document defined by [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md) and extended by [RFC 0035](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0035-content-install-descriptor.md), [RFC 0049](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0049-instance-handover.md), [RFC 0058](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0058-listing-images-and-dates.md) and [RFC 0067](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0067-per-platform-launch.md), and amended by [RFC 0065](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0065-icon-center-crop.md), [RFC 0072](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0072-version-forms.md) and [RFC 0079](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0079-author-freedom.md).

It is JSON Schema 2020-12, and it covers the five types the format defines today: `mod`, `mod-loader`, `modpack`, and `vehicle` and `save` from [RFC 0085](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0085-vehicles-and-saves.md), which [the rollout gate](#the-rollout-gate) still refuses.

`index-status.schema.json` covers `index-status.toml`, the index's own voice about a listing, per [RFC 0033](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0033-content-index.md).
A state the snapshot builder cannot place fails the build, so a delisting written with a typo never reaches a client.
`tools/check_status.py` runs the schema and resolves every id against the index.

The RFCs stay the authority.

## Running it

```sh
pip install -r tools/requirements.txt
python3 tools/check_schema.py
python3 tools/test_check_schema.py
```

Every script resolves its paths from its own location, so the working directory does not matter.

`check_schema.py` validates every document under `listings/` and `packs/`, at the depth the layout puts them at.
`test_check_schema.py` validates the schema itself, from both sides: real listings have to pass, and every rule has a case that has to fail for the stated reason.

The other checks around it have their own tests, run together:

```sh
python3 -m unittest discover -s tools -t tools --buffer
```

## Writing an image record

`tools/image_record.py` measures an image and prints its `[images.icon]` or `[[images.description]]` record, so nobody writes `sha256`, `width`, `height` and `size` by hand:

```sh
python3 tools/image_record.py icon.png --icon --url https://example.invalid/my-mod/icon.png --license CC-BY-4.0 --attribution "Artwork by Example Artist"
python3 tools/image_record.py https://example.invalid/my-mod/settings-window.png --description settings-window
```

A URL is fetched by the rules of `tools/images.py`, and a local file needs `--url`, the address where it will be hosted.
The tool validates the record against this schema and the SPDX list.
When the image breaks a limit or a value is refused, it names the problem on stderr and prints no record.

## Validate the parsed document

A listing is TOML and the schema is JSON, so a consumer parses first and validates the result.

One conversion is not automatic. TOML has a native datetime, so `released_at` can be written either quoted or bare, and both are correct TOML:

```toml
released_at = "2026-08-05T12:00:00Z"
released_at = 2026-08-05T12:00:00Z
```

The schema expects a string. `check_schema.normalise` turns a native date or time into its RFC 3339 string first, so the index accepts both spellings, and **any other tool that validates against this schema has to do the same** or it will reject documents this repository accepts.

The two spellings are equivalent with one exception: TOML also allows a space in place of the `T`, and only the bare form survives it. Bare, the parser produces a datetime and `normalise` writes the `T` back; quoted, the space stays in the string and the schema rejects it.

## Launch per platform

A `mod-loader` listing that starts differently on one platform adds an entry for it in `[provides.platform]`, per RFC 0067:

```toml
[provides]
launch = "StarMap.exe"

[provides.platform.linux]
runtime = "dotnet"
launch = "StarMap.dll"
```

The platform names are `windows`, `linux` and `macos`.
Each entry needs `launch`, a path relative to the loader's install location, and can add `runtime = "dotnet"`, which starts `dotnet` with `launch` as its first argument.
A platform without an entry starts `[provides].launch`, so the table is valid only next to it.

## Version bounds

A `min` or `max` on `[loader]`, on a dependency entry, or on an `any_of` alternative is a version with one, two or three numbers, per RFC 0072.
A missing number reads as `0`, so `0.5` is `0.5.0` and `1` is `1.0.0`.
The SemVer 2.0.0 pre-release and build parts are allowed, as in `1.2-rc.1`.
Four numbers, a leading zero, and a leading `v` are refused.

The pack `version` and the `version` of a pin keep all three numbers, because they name a release as the index stores it.

## Older releases

`[releases]` can carry `since`, a version in the same forms as a bound, per [RFC 0079](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0079-author-freedom.md):

```toml
[releases]
github = "owner/repository"
since = "1.2"
```

The watcher in content-index-releases then also stamps every release of the authority host whose version is at least `since` and that has no release file yet.
Without `since`, it stamps the newest release of a new listing and every release after it.
`since` names no host, so it does not count toward the hosts that make `authority` required, `[releases]` with only `since` is refused, and `tools/ownership.py` reads the authority without it.
A change of `since` alone is not a change of release host.

An older release is stamped with the listing facts that stand when it is stamped, so a bound written for the newest release lands on it too.
The owner corrects the facts of an old release with an amendment in content-index-releases, which may make the release stricter or wider.
A lower `since` stamps more releases, and a higher one removes none.

## Releases that are not mod releases

`[releases]` can carry `tag_prefix`, per [RFC 0096](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0096-tag-prefix.md):

```toml
[releases]
github = "owner/repository"
tag_prefix = "mymod-"
```

The watcher then takes only the GitHub releases whose tag starts with `tag_prefix`, compared case-sensitively, and reads the version from the rest of the tag, so one leading `v` is allowed there.
It filters `github` as the authority and as a mirror, and SpaceDock ignores it.
The schema takes a non-empty ASCII string without whitespace and requires `github` next to it.
`tag_prefix` names no host, so `tools/ownership.py` reads the authority without it, and a change of `tag_prefix` alone is not a change of release host.
The release check of a listing refuses a `tag_prefix` that no release of a repository with releases starts with.

## What the schema does not cover

Some rules cannot be expressed in JSON Schema at all. `check_schema.py` applies these after the schema passes:

- a `max` below its `min`, on `[loader]`, on a dependency entry, and on an `any_of` alternative, compared after a short bound is filled with `0`,
- a `game_max` older than its `game_min`, where both name a revision or both name a month. RFC 0017 makes a month bound the first and last revision of that calendar month, and revisions ascend across the shipped history, so calendar order is revision order. A month against a revision stays uncomparable here: resolving it needs the game release list, which lives in the generated repository,
- a `released_at` that matches the shape but names no real moment, such as `2026-13-45T12:00:00Z`,
- unbalanced parentheses in a `license` expression,
- a link key that differs from another only in case, which TOML permits and the format does not,
- a listing that depends on itself, supersedes itself, is its own loader, names the same dependency twice, pins itself, or pins one id in two of `[[mods]]`, `[[vehicles]]` and `[[saves]]`. The pinned sections share one set because RFC 0031 makes the id namespace global across content types.

Some rules need more than the document, and belong to the checks around it:

| Rule | Where it belongs |
|---|---|
| Every SPDX identifier exists in the SPDX list | `tools/check_license.py`. The list is versioned data and must not be frozen into a schema, so it arrives as a pinned dependency instead. The dependency also reads a few short names of its own, such as `GPL`, which are not SPDX identifiers, and the check refuses them. An identifier that is not on the list gets the identifiers that start like it named in the message, exception identifiers after WITH and license identifiers in every other place. |
| Two identifiers in a `license` expression have an operator between them | `tools/check_license.py`, which names the missing `AND` or `OR`. The schema pattern refuses the shape as well. |
| The id does not collide with another listing, case-insensitively | `tools/check_index.py` |
| A changed document names a forums thread that no other listing or pack names, compared by thread id | `tools/check_index.py` warns only. The id comes from the `links.forums` pattern, so every URL form of one thread compares equal. |
| A changed document has an `abstract` of at most 280 characters | `tools/check_index.py` warns only. RFC 0031 calls the abstract one or two sentences, and a longer one breaks list views. |
| A changed document has a `game_max` that is not the newest build of the game release list | `tools/check_index.py` warns only, against `game-versions.json` of the generated repository, and the listing page gives the same note against the snapshot. A client blocks the content above `game_max` ([RFC 0091](https://github.com/KSAModding/content-manager-design/pull/91)), and a bound at the newest build usually means "tested with". A month is not compared. The vectors of this rule carry the release list as `game_versions`. |
| The document sits at the path its id and type say | `tools/check_layout.py` |
| `[loader].id` references content of type `mod-loader`, a dependency id references a `mod`, and a pack member is not itself a pack | `tools/check_index.py` |
| Each pin of a changed pack version names a listed `mod` that is not delisted, at a stamped release that is not yanked, and `[[vehicles]]` and `[[saves]]` stay empty | `tools/check_index.py`, against the release files of the generated repository, per [RFC 0080](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0080-pack-claims-and-members.md) |
| The pins of a changed pack version are a complete set: every `required` dependency of a pinned release names another pinned mod inside its bounds, one member of an `any_of` is enough, and no `conflict` entry matches another pinned mod | `tools/check_index.py`, from the dependencies in the stamped release files, so a derived entry counts like an authored one |
| A pin of a changed pack version names a `disputed` mod | `tools/check_index.py` warns only, because RFC 0080 lets a disputed member pass and a client warns about it |
| A named `any_of` member carried `Optional = true` in the archive's own `mod.toml` | the stamper ([content-index-releases#13](https://github.com/KSAModding/content-index-releases/issues/13)), which is the only place the archive is read |
| `[provides].launch` and the `launch` of each `[provides.platform]` entry name a file the release actually contains | the stamper |
| `install.root` is derivable, and the archive downloads and hashes | `tools/check_release.py`, which reaches the answer by running the stamper against the real archive rather than by repeating its rules |
| The change is narrow enough to merge itself | `tools/check_scope.py` |
| A changed document has a curated tag, and each free-form tag is in the curated list | `tools/check_tags.py` warns only. `mod`, `mod-loader` and `modpack` share the `mod` list in `tags.toml`. The tags of a `vehicle` or a `save` are free-form by RFC 0085 and get no note. |
| The shorter side of an icon is at most 1024 pixels and its longer side at most twice the shorter side, a description image `id` is used once, and each `ksa-image:` reference in the description names a record | `tools/check_images.py` |
| A changed document has an icon that is not square | `tools/check_images.py` warns only, and names the center square that clients show. |
| Each image of a changed document downloads safely and matches its record | `tools/check_images.py` with the document path, by the fetch rules of RFC 0058 |
| An image record's `license` names identifiers on the SPDX list | `tools/check_license.py` |
| An id in `index-status.toml` names a listing or a pack that exists, and a retracted version exists on that pack | `tools/check_status.py` |
| The author controls the release host, or owns the pack id | the ownership workflow ([#4](https://github.com/KSAModding/content-index/issues/4)); pack ownership is read from `packs/<id>/owner.json` on the base branch by numeric account id, or from the pull request for a first claim, which adds the owner record together with the first version of an id that no listing or pack on the base branch holds in any case |

## Pack member vectors

`pack-vectors.json` holds small cases of the pack member rules of RFC 0080, with the result that `check_index.check_members` and `check_index.member_notes` give.
`tools/test_check_index.py` writes each mini snapshot into a temporary index and release folder and runs the checks, and `site/test/pack-vectors.test.js` runs the same cases through the listing page.
Borea is to hold a copy of the file and run it in its own tests ([Borea#567](https://github.com/KSAModding/Borea/issues/567)), so once that lands, a change here needs the same change there.

The file is an object with one key, `vectors`, a list of cases.
Each case has these keys:

| Key | What it holds |
|---|---|
| `name` | What the case shows. Unique in the file. |
| `snapshot` | The mini snapshot the case runs against, see below. |
| `pack` | The text of the pack version document, in TOML. |
| `accepted` | `true` when the member rules give no error. |
| `errors` | Every error, in order, as `<section>[<n>]: <message>`. The checks put the path of the pack file in front, and a vector leaves it out. |
| `notes` | Every warning, in the same form. A note does not refuse the pack. |
| `adds` | Optional. The pins that "Add the missing dependencies" of the listing page appends, each as `id` and `version`, in order. Absent means none. With them appended, the pack has no error. |

The mini snapshot has these keys:

| Key | What it holds |
|---|---|
| `listings` | Each listing as `id`, `type` and `releases`. `releases` holds the stamped release files of the listing, with only the fields the rules read: `version`, `release_status`, and where the case needs them `yanked`, `dependencies` and `download`. A bound of a dependency is full SemVer, as the stamper writes it, so a runner can read the releases as release files without a stamping step. A case can also carry other fields of a release file, such as `yanked_reason` or the `source` of a dependency, which the rules do not read. |
| `delisted` | Optional. The ids that `index-status.toml` delists. In a real snapshot such a listing is a tombstone. |
| `disputed` | Optional. The ids that `index-status.toml` marks disputed. In a real snapshot such a listing ships whole, with `index_status.state` set to `disputed`. |

## Vehicles and saves

A `vehicle` lives at `vehicles/<id>.toml` and a `save` at `saves/<id>.toml`, per [RFC 0085](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0085-vehicles-and-saves.md), and their ids are in the one global namespace of RFC 0031.
The document has the shared core of a mod, with these differences:

- `[links]` and `links.forums` are optional, because vehicles and saves carry no code and the forum may have no place for them. A mod, a loader and a pack keep both required ([RFC 0079](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0079-author-freedom.md)), and so does a document without `type`.
- `[compatibility]` and `game_min` are optional, because the watcher takes `game_min` from `version` in the `meta.toml` of the archive when none is authored.
- `[loader]`, `[provides]`, and the pack keys `version`, `released_at`, `changelog`, `[[mods]]`, `[[vehicles]]` and `[[saves]]` are refused.
- `[install]` takes only `root`, `steps` and `uninstall`. The game decides the place, and `name` in the `meta.toml` of the archive names the folder, which the stamper writes into the release file as `install.folder`, so the document cannot author one.
- `[releases]`, `[[dependencies]]` with every kind and `any_of`, `[images]`, `tags`, `status` and `superseded_by` are as for a mod. A dependency `id` that is listed must be a `mod`.

The checks of the archive, such as the name rule below, the root folder and the game file, are the stamper's, and `tools/check_release.py` runs them.

## The rollout gate

RFC 0085 lets the index accept a `vehicle` only once a release host for it exists, and the listing checks, the watcher, the snapshot builder and a released Borea support the type, and later the same for a `save`.
No file here can see whether those are ready, so the schema holds the gate itself: `properties.type.not` lists the types the index does not accept yet, and a document of such a type is refused with its title, "a type that the index does not accept yet, because no release host for it exists (RFC 0085 Rollout)".
`tools/check_schema.py`, the listing page and Borea's `ListingValidator` all run this schema, so the gate refuses everywhere with the same words, and `tools/decide.py` never arms auto-merge for such a document.

A steward lifts the gate by pull request ([#210](https://github.com/KSAModding/content-index/issues/210)): first `vehicle`, then `save`, each by removing it from the `enum` of the `not`, and the whole `not` once its `enum` is empty.
No check reads `hosts.toml` of the generated repository for it.
A vector of `vectors.json` for a gated type carries `"gated": "vehicle"` or `"gated": "save"`. While the schema holds that type, both runners expect the gate line, and they also run each such vector against a copy of the schema without the gate and expect its `accepted`, `noted` and `says`, so a lift changes the schema alone.

## Save and vehicle names

The game takes the identity of a vehicle or a save from `name` in the `meta.toml` of its folder (`UncompressedVehicleSave.FromDirectory`, `UncompressedSave.FromDirectory`), and it keeps a name only when `SaveName.Sanitize` gives it back unchanged (`SaveName.IsSanitized`).
[RFC 0085](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0085-vehicles-and-saves.md) writes that rule out:

- 1 to 64 UTF-16 code units.
- Each code unit is in the Unicode categories Lu, Ll, Lt, Lm, Lo or Nd (`char.IsLetterOrDigit`), or is a space, `-` or `_`. So a letter outside the Basic Multilingual Plane fails.
- No space at the start or the end, and no two spaces together.
- Not `CON`, `PRN`, `AUX`, `NUL`, `COM1` to `COM9` or `LPT1` to `LPT9`, compared without case.

`save-names.json` holds the cases a checker gets wrong most easily, such as U+00B2, which Python's `str.isalnum` accepts and `char.IsLetterOrDigit` does not, and a name whose length in characters and in UTF-16 code units differs.
The file is an object with one key, `vectors`, a list of cases with the keys `name` (what the case shows, unique in the file), `value` (the name), `accepted` (`true` when the game keeps the name as it is) and `why`.
Every character outside ASCII is a JSON `\u` escape, so the file stays ASCII.
A case uses only characters that Unicode 15.0 or older assigns, so Python, .NET and a browser agree on their category; `tools/test_save_name_vectors.py` fails on a runner whose table is older or does not know a character.

Every copy of the rule runs this file:

- the Python copy is `stamp_release.valid_save_name` of content-index-releases ([content-index-releases#102](https://github.com/KSAModding/content-index-releases/issues/102)), which the checks here load through `check_release.load_stamper`, so this repository keeps no copy of its own,
- the listing page has `site/js/savename.js`, which `site/test/save-names.test.js` runs,
- Borea has `GameSaveName` ([Borea#790](https://github.com/KSAModding/Borea/issues/790)),
- a share host ([RFC 0094](https://github.com/KSAModding/content-manager-design/pull/94)) checks the name of an upload with it too.

A change here needs the same change in each copy.

## Where the schema is stricter than the RFC text

Each of these has a hook in an RFC's reasoning rather than in its field table.
They are collected here so any one of them can be argued down on its own.

| Rule | Why |
|---|---|
| Unknown keys are rejected, everywhere | The index is the authority for what a document may say. `abstrct = "..."` accepted silently is a listing that ships with no abstract, and RFC 0031's "clients ignore fields they do not know" is a rule for clients reading published data, not for the gate that publishes it. |
| `links.forums` must be an `https` link to a thread on `forums.ahwoo.com` | The field exists to tie a listing to an Ahwoo account, to be the tiebreaker in an id dispute, and to be the takedown tripwire. A link anywhere else satisfies the letter and defeats all three, and so do the forum root and a category page, which are on the host and name no content. RFC 0031's field table already calls the field the forums thread, so what the schema adds is a machine rule for that description and the one domain the RFC's examples use. Every form the forum serves a thread under passes, which is `/threads/<slug>.<id>/`, the same thread under its node path, and the `index.php` form. |
| A link value must be an `http` or `https` URL | RFC 0031 says "plain links, shown as such". A client renders these, so a value that is not a URL is not a link. |
| `superseded_by` requires `status = "deprecated"` | RFC 0031 calls it "only meaningful together with" a deprecation. Alone it is a successor no client will ever show, which is more likely a forgotten `status` line than an intention. |
| A `mod` may not set `install.target` or `install.path` | RFC 0035: "a mod's install location is not the author's to choose in the first place", because the folder name is the identity `Mod.MakeUsing` assigns, and "stating it as a default rather than an authorable field keeps it that way". The stamper refuses both keys on a mod, so the schema refuses even `target = "mods"`, which only repeats the default. |
| A `modpack` may not carry `[releases]`, `[loader]` or `[[dependencies]]` | RFC 0031 lists these under what a pack does not have, and RFC 0035 already makes `[install]` on a pack invalid. A section that does nothing is a section its author believed in. |
| A `vehicle` or a `save` is refused until the rollout gate lifts its type | RFC 0085 makes a release host and support in the watcher, the snapshot builder and the clients the condition, and says nothing about how the index enforces it. The gate in the schema is that enforcement, see [The rollout gate](#the-rollout-gate). |
| A `mod-loader` carrying `[install]` must state `target` | RFC 0035's Relationship section claims every RFC 0031 file stays valid, but its own table requires `target` on a type with no default, and `mod-loader` has none. The normative table wins. |
| Authored version bounds reject a leading `v` | Only a release tag gets its `v` stripped, and that happens at stamp time. An authored bound is not a tag. |
| Game bounds reject a suffix or a `+hash`, take a four-digit year, and take a month of 1 to 12 | RFC 0017 puts builds carrying a suffix outside the compatibility model, and a bound has to resolve to a revision. |
| An `any_of` entry may not carry `min` or `max` of its own | RFC 0031 puts the bounds on each alternative. An outer pair would have no defined meaning against a set. |
| A path may not run through a reserved Windows device name | Not in any RFC. A segment naming `NUL` or `CON` swallows every write on Windows, so a manager writing `[provides.configure]` there reports success and configures nothing, which is the failure that section exists to prevent. |
| A `[provides.instance]` key may not carry a Unicode control character, U+0000 to U+001F or U+007F to U+009F | RFC 0049 forbids only whitespace. A manager hands the value to a process start as an argument or a variable name, where a control character that is not whitespace, such as a NUL, cuts the value short or makes the start fail. The paths and keys elsewhere in the schema exclude the control characters below U+0020 for the same reason. |
| `[releases]` must name at least one host | A section carrying only `authority` or `since` names an authority or a first release for nothing. Implied by RFC 0031 rather than stated. |
| `tags` are lowercase, and a word or words joined by `-` | RFC 0031 says "free-form lowercase tags". The casing is the RFC's; the separator is this schema's, so a filter list cannot end up holding both `user-interface` and `user_interface`. |
| `[[mods]]` and `authors` need at least one entry, and `name`, `abstract` and `changelog` may not be empty | A required field present but empty is the same absence with none of the reporting. |

## Two regex conventions

**Patterns end in `(?![\s\S])`, not `$`.**
In several regex flavours, Python's included, `$` also matches before a trailing newline, so `^...$` would accept an id of `"MyMod\n"` and put that newline into a folder name. `(?![\s\S])` is a true end of input in both Python and ECMAScript.

**A forbidden key is `{"not": {}}`, not `false`.**
Both reject the key. On a boolean subschema the validator loses the key name from the error path, so the report points at the whole document instead of at the key. `check_schema.explain` turns the resulting message back into English, and does the same for a `not` carrying a pattern, using the `title` on that subschema so the author reads "is a reserved name" rather than the pattern itself. A `pattern` may carry a `title` for the same reason, and `links.forums` does. A pattern title names what the value should be rather than what it is, so the message negates it, and the author reads the shape that is wanted rather than the regex that refused it.

## Editor support

Point an editor at the schema from a JSON copy of a document:

```json
{ "$schema": "https://raw.githubusercontent.com/KSAModding/content-index/main/schemas/authored.schema.json" }
```

A TOML-aware validator may or may not work: every pattern here uses lookahead, and a validator built on a regex engine without lookaround, which several Rust ones are, will reject or ignore them.
Try it before relying on it, and remember the datetime note above either way.

## A new spec version

`spec_version` is pinned to `1` here.
When RFC-driven changes bump it, the next schema is a new file next to this one, and both stay, because documents at the old version stay valid.
