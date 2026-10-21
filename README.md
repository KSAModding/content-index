# content-index

The authored half of the Kitten Space Agency content index.

One TOML document per listing, written by the person who publishes the content.

The stamped release files live in the other half, [content-index-releases](https://github.com/KSAModding/content-index-releases).

The index is defined by [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md) (the metadata format) and [RFC 0033](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0033-content-index.md) (the index itself), in [content-manager-design](https://github.com/KSAModding/content-manager-design).
Design discussion belongs there, not here.

## Clients do not read this repository

A client fetches the snapshot, which merges both halves of the index plus the game release list.
It is the main document below plus the files that [Fetching it](https://github.com/KSAModding/content-manager-design/blob/main/spec/snapshot.md#fetching-it) in the snapshot specification names:

```text
https://ksamodding.github.io/content-index-releases/v1/index.json
```

## Layout

| Path | Contents |
|---|---|
| `listings/<id>.toml` | One authored document per mod or mod loader. |
| `vehicles/<id>.toml` | One authored document per vehicle, per [RFC 0085](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0085-vehicles-and-saves.md). |
| `saves/<id>.toml` | One authored document per save, per RFC 0085. The schema refuses it until [#210](https://github.com/KSAModding/content-index/issues/210) lifts the rollout gate. |
| `packs/<id>/<version>.toml` | One authored document per mod pack version. |
| `packs/<id>/owner.json` | The GitHub account that owns a pack id, recorded by its first claim. |
| `index-status.toml` | The index's own voice about a listing. Stewards only. |
| `tags.toml` | The curated tag vocabulary that clients use for filters. Stewards only. |
| `hosts.toml` | The share hosts the index trusts to say who owns an upload, per [RFC 0094](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0094-share-host.md). Stewards only. |
| `POLICY.md` | How a takedown or an id dispute is filed, and what a steward does with it. |
| `schemas/` | What a document may contain, as JSON Schema. See its [README](schemas/README.md). |
| `tools/` | The checks that run on every pull request. |
| `schemas/vectors.json` | Test documents with the result the checks give, which `tools/test_vectors.py` and the tests of the listing page both run, so the page and the checks keep one rule set. |
| `schemas/pack-vectors.json` | Pack versions with a small index and the result of the pack member rules, which the checks and the listing page both run, and which Borea is to run too ([Borea#567](https://github.com/KSAModding/Borea/issues/567)). See the [schemas README](schemas/README.md#pack-member-vectors). |
| `schemas/save-names.json` | Names of a vehicle or a save with the verdict of the name rule of RFC 0085, which the stamper of content-index-releases, the listing page and Borea all run. See the [schemas README](schemas/README.md#save-and-vehicle-names). |
| `schemas/attestation-vectors.json` | Changes with their canonical form and its SHA-256, which the ownership check and every share host of [RFC 0094](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0094-share-host.md) run. See the [schemas README](schemas/README.md#attestation-vectors). |
| `site/` | The [listing page](https://ksamodding.github.io/content-index/), which writes a listing or a pack version, or changes a listing, and checks it in the browser before the pull request. It also says whether a pack id is free and writes the owner record of a first pack claim. It uses the schema, `tags.toml` and `hosts.toml` of the commit it was deployed from. |

## Getting listed

Write your authored document per RFC 0031, or let the [listing page](https://ksamodding.github.io/content-index/) write it, and open a pull request that adds it. One pull request can carry several documents.
A mod, a mod loader, a pack and a vehicle can be listed, and a vehicle also follows RFC 0085, see [Listing a vehicle](CONTRIBUTING.md#listing-a-vehicle).

Checks validate it, a further check verifies that you control the release host the listing points at, and when everything is green the pull request merges itself.

See [CONTRIBUTING.md](CONTRIBUTING.md).

Security problems in this repository, its tools, or its workflows use [SECURITY.md](SECURITY.md).
Problems with a listing or archive use the [takedown and dispute policy](POLICY.md).

A new release of an already listed mod needs nothing from you at all: a watcher picks it up and stamps it.

## Two different things are called a license here

The license of this repository, below, covers the metadata documents.

The `license` field inside a listing is something else entirely: it is the license of the content that listing describes, chosen by its author.
Nothing here changes it.

## License

Metadata is dedicated to the public domain under [CC0 1.0](LICENSE).
That means `listings/`, `vehicles/`, `saves/`, `packs/`, `index-status.toml`, `tags.toml`, `hosts.toml`, and the published snapshot.

A mirror, a client, or a website can therefore copy and re-serve the whole index with no conditions attached, which is the point.

Code and configuration is licensed under [MIT](LICENSE-MIT).
That means `.github/` and any tooling.
