# Contributing

This repository holds listing documents, not discussion.

If you want to argue about the format or the index itself, open a thread in [content-manager-design](https://github.com/KSAModding/content-manager-design/discussions).

## Listing your content

1. Write your authored document following [RFC 0031](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0031-content-metadata-format.md).
   The worked examples in [`examples/`](https://github.com/KSAModding/content-manager-design/tree/main/examples) are real listings you can copy from.
2. Put it at `listings/<id>.toml`, where `<id>` is the folder name your content installs as.
   A mod pack goes to `packs/<id>/<version>.toml`.
3. Check it before you open anything, which saves you a round trip through CI:

   ```sh
   pip install -r tools/requirements.txt
   python3 tools/check_layout.py
   python3 tools/check_schema.py
   python3 tools/check_index.py
   python3 tools/check_license.py
   ```

   These need nothing but the repository. The remaining check downloads your latest release and stamps it, which needs the network and a checkout of [content-index-releases](https://github.com/KSAModding/content-index-releases) next to this one:

   ```sh
   python3 tools/check_release.py listings/<id>.toml
   ```

4. Open a pull request that adds exactly one file.
   One document merges itself. A pull request carrying two, or carrying anything besides a document, is valid but waits for a steward.

Checks then validate the document, inspect your latest release archive, and verify that you control the release host the listing points at.

When everything is green and ownership verified, the pull request merges itself.
When ownership cannot be verified automatically, a steward looks instead.

## Proving you control the release host

Each proof is something only somebody with access to the release repository can put there, which is what says the author agrees to their content being indexed.

Any one of the three is enough, and the first that applies is used:

1. The repository in `[releases]` is owned by your own account, and is not a fork.
2. The repository carries the topic `ksa-index-<your-github-username>`, lowercased, per [RFC 0038](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0038-repository-topic-ownership-proof.md).
   So `Maximilian-Nesslauer` sets `ksa-index-maximilian-nesslauer`.
   One topic covers every listing that points at that repository, and it is the easy path for an organization-owned repository.
3. The repository contains `.github/ksa-content-index.toml` naming the listing id and your username.

A SpaceDock release host has no comparable proof today, so those listings wait for a steward.

## Changing a listing that already exists

An edit is checked against the release host your listing names right now, on `main`, and not against the one your pull request writes into it.
Otherwise anybody could point somebody else's listing at their own repository and then prove control of that.

If you point your listing at a different release host, you must prove control of both hosts: the one it comes from and the one it goes to.

Renaming or transferring your repository on GitHub is not such a move.
The old address then answers as the new one, and only somebody who controls a repository can rename or transfer it.
The check reads that redirect, so catching your listing up with its own repository stays self-service.

Handing a listing to somebody:

- **You transfer the repository itself.** The redirect above carries your consent, and the release host moved with it, so the new owner updates the listing without a steward.
- **You point the listing at a separate repository.** Nobody controls both hosts, so a steward applies it, unless you first put the incoming account's proof on your own repository, for example their `ksa-index-<username>` topic.

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
