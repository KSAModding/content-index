# Schemas

`authored.schema.json` is the machine-readable form of the authored document defined by [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md) and extended by [RFC 0035](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0035-content-install-descriptor.md).

It is JSON Schema 2020-12, and it covers all three types the format defines today: `mod`, `mod-loader` and `modpack`.

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
python3 -m unittest discover -s tools -t tools
```

## Validate the parsed document

A listing is TOML and the schema is JSON, so a consumer parses first and validates the result.

One conversion is not automatic. TOML has a native datetime, so `released_at` can be written either quoted or bare, and both are correct TOML:

```toml
released_at = "2026-08-05T12:00:00Z"
released_at = 2026-08-05T12:00:00Z
```

The schema expects a string. `check_schema.normalise` turns a native date or time into its RFC 3339 string first, so the index accepts both spellings, and **any other tool that validates against this schema has to do the same** or it will reject documents this repository accepts.

The two spellings are equivalent with one exception: TOML also allows a space in place of the `T`, and only the bare form survives it. Bare, the parser produces a datetime and `normalise` writes the `T` back; quoted, the space stays in the string and the schema rejects it.

## What the schema does not cover

Some rules cannot be expressed in JSON Schema at all. `check_schema.py` applies these after the schema passes:

- a `max` below its `min`, on `[loader]`, on a dependency entry, and on an `any_of` alternative,
- a `game_max` older than its `game_min`, where both name a revision or both name a month. RFC 0017 makes a month bound the first and last revision of that calendar month, and revisions ascend across the shipped history, so calendar order is revision order. A month against a revision stays uncomparable here: resolving it needs the game release list, which lives in the generated repository,
- a `released_at` that matches the shape but names no real moment, such as `2026-13-45T12:00:00Z`,
- unbalanced parentheses in a `license` expression,
- a link key that differs from another only in case, which TOML permits and the format does not,
- a listing that depends on itself, supersedes itself, is its own loader, names the same dependency twice, pins itself, or pins one id in two of `[[mods]]`, `[[vehicles]]` and `[[saves]]`. The pinned sections share one set because RFC 0031 makes the id namespace global across content types.

Some rules need more than the document, and belong to the checks around it:

| Rule | Where it belongs |
|---|---|
| Every SPDX identifier exists in the SPDX list | `tools/check_license.py`. The list is versioned data and must not be frozen into a schema, so it arrives as a pinned dependency instead. |
| The id does not collide with another listing, case-insensitively | `tools/check_index.py` |
| The document sits at the path its id and type say | `tools/check_layout.py` |
| `[loader].id` references content of type `mod-loader`, a dependency id references a `mod`, and a pack member is not itself a pack | `tools/check_index.py` |
| A named `any_of` member carried `Optional = true` in the archive's own `mod.toml` | the stamper ([content-index-releases#13](https://github.com/KSAModding/content-index-releases/issues/13)), which is the only place the archive is read |
| `[provides].launch` names a file the release actually contains | the stamper |
| `install.root` is derivable, and the archive downloads and hashes | `tools/check_release.py`, which reaches the answer by running the stamper against the real archive rather than by repeating its rules |
| The change is narrow enough to merge itself | `tools/check_scope.py` |
| The author controls the release host | the ownership workflow ([#4](https://github.com/KSAModding/content-index/issues/4)) |

## Where the schema is stricter than the RFC text

Each of these has a hook in an RFC's reasoning rather than in its field table.
They are collected here so any one of them can be argued down on its own.

| Rule | Why |
|---|---|
| Unknown keys are rejected, everywhere | The index is the authority for what a document may say. `abstrct = "..."` accepted silently is a listing that ships with no abstract, and RFC 0031's "clients ignore fields they do not know" is a rule for clients reading published data, not for the gate that publishes it. |
| `links.forums` must be on `forums.ahwoo.com` | The field exists to tie a listing to an Ahwoo account, to be the tiebreaker in an id dispute, and to be the takedown tripwire. A link anywhere else satisfies the letter and defeats all three. |
| A link value must be an `http` or `https` URL | RFC 0031 says "plain links, shown as such". A client renders these, so a value that is not a URL is not a link. |
| `superseded_by` requires `status = "deprecated"` | RFC 0031 calls it "only meaningful together with" a deprecation. Alone it is a successor no client will ever show, which is more likely a forgotten `status` line than an intention. |
| A `mod` may not set `install.path`, and may only set `install.target = "mods"` | RFC 0035: "a mod's install location is not the author's to choose in the first place", because the folder name is the identity `Mod.MakeUsing` assigns. |
| A `modpack` may not carry `[releases]`, `[loader]` or `[[dependencies]]` | RFC 0031 lists these under what a pack does not have, and RFC 0035 already makes `[install]` on a pack invalid. A section that does nothing is a section its author believed in. |
| A `mod-loader` carrying `[install]` must state `target` | RFC 0035's Relationship section claims every RFC 0031 file stays valid, but its own table requires `target` on a type with no default, and `mod-loader` has none. The normative table wins. |
| Authored SemVer bounds reject a leading `v` | Only a release tag gets its `v` stripped, and that happens at stamp time. An authored bound is not a tag. |
| Game bounds reject a suffix or a `+hash`, take a four-digit year, and take a month of 1 to 12 | RFC 0017 puts builds carrying a suffix outside the compatibility model, and a bound has to resolve to a revision. |
| An `any_of` entry may not carry `min` or `max` of its own | RFC 0031 puts the bounds on each alternative. An outer pair would have no defined meaning against a set. |
| A path may not run through a reserved Windows device name | Not in either RFC. A segment naming `NUL` or `CON` swallows every write on Windows, so a manager writing `[provides.configure]` there reports success and configures nothing, which is the failure that section exists to prevent. |
| `[releases]` must name at least one host | A section carrying only `authority` names an authority for nothing. Implied by RFC 0031 rather than stated. |
| `tags` are lowercase, and a word or words joined by `-` | RFC 0031 says "free-form lowercase tags". The casing is the RFC's; the separator is this schema's, so a filter list cannot end up holding both `user-interface` and `user_interface`. |
| `[[mods]]` and `authors` need at least one entry, and `name`, `abstract` and `changelog` may not be empty | A required field present but empty is the same absence with none of the reporting. |

## Two regex conventions

**Patterns end in `(?![\s\S])`, not `$`.**
In several regex flavours, Python's included, `$` also matches before a trailing newline, so `^...$` would accept an id of `"MyMod\n"` and put that newline into a folder name. `(?![\s\S])` is a true end of input in both Python and ECMAScript.

**A forbidden key is `{"not": {}}`, not `false`.**
Both reject the key. On a boolean subschema the validator loses the key name from the error path, so the report points at the whole document instead of at the key. `check_schema.explain` turns the resulting message back into English, and does the same for a `not` carrying a pattern, using the `title` on that subschema so the author reads "is a reserved name" rather than the pattern itself.

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
