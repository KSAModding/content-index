# Contributing

This repository holds listing documents, not discussion.

If you want to argue about the format or the index itself, open a thread in [content-manager-design](https://github.com/KSAModding/content-manager-design/discussions).

## Listing your content

1. Write your authored document following [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md).
   The worked examples in [`examples/`](https://github.com/KSAModding/content-manager-design/tree/main/examples) are real listings you can copy from.
2. Put it at `listings/<id>.toml`, where `<id>` is the folder name your content installs as.
   A mod pack goes to `packs/<id>/<version>.toml`.
3. Open a pull request that adds exactly one file.

Checks then validate the document, inspect your latest release archive, and verify that you control the release host the listing points at.

When everything is green and ownership verified, the pull request merges itself.
When ownership cannot be verified automatically, a steward looks instead.

## Proving you control the release host

Any one of three proofs is enough, and the first that applies is used:

1. The repository in `[releases]` is owned by your own account, and is not a fork.
2. The repository carries the topic `ksa-index-<your-login>`, lowercased, per [RFC 0038](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0038-repository-topic-ownership-proof.md).
   One topic covers every listing that points at that repository, and it is the easy path for an organization-owned repository.
3. The repository contains `.github/ksa-content-index.toml` naming the listing id and your login.

A SpaceDock release host has no comparable proof today, so those listings wait for a steward.

## After you are listed

You touch your authored document again only when the facts change: a new dependency bound, a new link, or the day you stop maintaining it.
Releases are picked up on their own.

Correcting metadata is a change here, not a new release of your content.

## Takedowns and disputes

Use the issue forms.
A steward decides, and the required forums link is the tiebreaker for who claimed an id first.

## Licensing your contribution

By opening a pull request you dedicate the metadata in it to the public domain under [CC0 1.0](LICENSE), and contribute any code or configuration under [MIT](LICENSE-MIT).

Your `abstract` and `description` are your own prose, and the index copies them into every stamped release file and into the snapshot that clients, mirrors, and websites fetch.

It applies only to the metadata you write here.
The content itself keeps whatever license you declare in the `license` field.
