# content-index

The authored half of the Kitten Space Agency content index.

One TOML document per listing, written by the person who publishes the content.

The stamped release files live in the other half, [content-index-releases](https://github.com/KSAModding/content-index-releases).

The index is defined by [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md) (the metadata format) and [RFC 0033](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0033-content-index.md) (the index itself), in [content-manager-design](https://github.com/KSAModding/content-manager-design).
Design discussion belongs there, not here.

## Clients do not read this repository

A client fetches one snapshot artifact, which merges both halves of the index plus the game release list into a single document:

```text
https://ksamodding.github.io/content-index-releases/v1/index.json
```

## Layout

| Path | Contents |
|---|---|
| `listings/<id>.toml` | One authored document per mod or mod loader. |
| `packs/<id>/<version>.toml` | One authored document per mod pack version. |
| `index-status.toml` | The index's own voice about a listing. Stewards only. |
| `schemas/` | What a document may contain, as JSON Schema. See its [README](schemas/README.md). |
| `tools/` | The checks that run on every pull request. |

## Getting listed

Write your authored document per RFC 0031 and open a pull request that adds exactly one file.

Checks validate it, a further check verifies that you control the release host the listing points at, and when everything is green the pull request merges itself.

See [CONTRIBUTING.md](CONTRIBUTING.md).

A new release of an already listed mod needs nothing from you at all: a watcher picks it up and stamps it.

## Two different things are called a license here

The license of this repository, below, covers the metadata documents.

The `license` field inside a listing is something else entirely: it is the license of the content that listing describes, chosen by its author.
Nothing here changes it.

## License

Metadata is dedicated to the public domain under [CC0 1.0](LICENSE).
That means `listings/`, `packs/`, `index-status.toml`, and the published snapshot.

A mirror, a client, or a website can therefore copy and re-serve the whole index with no conditions attached, which is the point.

Code and configuration is licensed under [MIT](LICENSE-MIT).
That means `.github/` and any tooling.
