# Contributing

This repository holds listing documents, not discussion.

If you want to argue about the format or the index itself, open a thread in [content-manager-design](https://github.com/KSAModding/content-manager-design/discussions).

## Listing your content

The [listing page](https://ksamodding.github.io/content-index/) writes or changes your listing section by section, starting from your GitHub repository, and checks it with the rules below before you open the pull request.

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
   python3 tools/check_status.py
   python3 tools/check_images.py
   ```

   These need nothing but the repository. The remaining checks need the network. The first fetches your images and compares them with their records. The second downloads your latest release and stamps it, which also needs a checkout of [content-index-releases](https://github.com/KSAModding/content-index-releases) next to this one:

   ```sh
   python3 tools/check_images.py listings/<id>.toml
   python3 tools/check_release.py listings/<id>.toml
   ```

   A release archive can be at most 4 GiB, and the release check and the watcher reject a larger one.

4. Open a pull request that adds your document, or several of them.
   Up to 15 documents merge themselves, as long as ownership verifies for every one of them: control of the release host for a listing, the account in `packs/<id>/owner.json` for a pack.
   A pull request that carries anything besides documents and the owner record of a new pack, or more than 15 documents, is valid but waits for a steward.

## The license field

`license` is an SPDX license expression.
For one license, write its identifier from the [SPDX license list](https://spdx.org/licenses/), such as `MIT` or `CC-BY-SA-4.0`.
The identifier is the short form with hyphens, so `CC BY-SA 4.0` is not valid.

When parts of your content have different licenses, join them with `AND`.
For example, code under GPL-2.0 and data files under CC BY-SA 4.0:

```toml
license = "GPL-2.0-only AND CC-BY-SA-4.0"
```

When the user may choose one of several licenses, join them with `OR`, such as `MIT OR Apache-2.0`.
A comma does not join licenses, and two identifiers written next to each other do not either, so `MIT Apache-2.0` is refused.

A license that is not on the SPDX list can be named as `LicenseRef-` followed by a name of your choice, such as `LicenseRef-MyModLicense`.
An image can have its own `license` in its record when its terms differ from those of the content, see [Images](#images).

## Images

A listing can have one icon and the images its description shows, per [RFC 0058](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0058-listing-images-and-dates.md) and [RFC 0065](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0065-icon-center-crop.md).
Each image stays on your own host.
Its record gives the HTTPS `url`, and the `sha256`, `width`, `height` and `size` of the file.
The checks fetch each image of the document you change and compare it with its record.

In the description, write `![alt text](ksa-image:<id>)` to show the description image with that `id`.
A client shows no other image in a description.

A square icon of 512 by 512 pixels or more is the best choice, because you decide exactly what shows.
An icon that is not square is also valid when its shorter side is 256 to 1024 pixels and its longer side is at most twice its shorter side.
Clients then show only the square in its center, and the checks give a note that names this square.

When you replace an image with new bytes, change its record in the same pull request.

`tools/image_record.py` measures the file and prints the record for you to copy into your document.
Give it the local file and the address where you will host it, or the address of an image you already host:

```sh
python3 tools/image_record.py icon.png --icon --url https://example.invalid/my-mod/icon.png
python3 tools/image_record.py https://example.invalid/my-mod/settings-window.png --description settings-window
```

Add `--license`, `--attribution` and `--source` when the image needs them.
When the image breaks a limit, the tool names the limit and prints no record.

By adding an image record, you state that you have the right to publish the image and to let clients fetch, display and cache it under the record's `license`, or under the document's `license` when the record names none.
When the image is third-party work, or its license requires credit, a license notice or a link to the original, put that into the record's `attribution` and `source`.

## Launching a mod loader

A `mod-loader` listing names the file a player starts in `[provides].launch`.
When your loader starts differently on one platform, add an entry for that platform, per [RFC 0067](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0067-per-platform-launch.md):

```toml
[provides]
launch = "StarMap.exe"

[provides.platform.linux]
runtime = "dotnet"
launch = "StarMap.dll"
```

On Linux, a manager then starts `dotnet` with `StarMap.dll`, and on every other platform it starts `StarMap.exe`.
The platform names are `windows`, `linux` and `macos`.
Leave out `runtime` when your loader has its own executable on that platform.
Every `launch` must be in your release archive, or the release is rejected.

## Claiming and updating a pack

A pack id is first come, first served, as a listing id is, per [RFC 0080](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0080-pack-claims-and-members.md).
To claim one, open one pull request that adds the first pack version and `packs/<id>/owner.json` with your GitHub login and numeric account id, see [packs/README.md](packs/README.md) for an example.
When the id is free and the checks pass, the pull request merges itself and the id is yours.
An owner record that names another account than the one that opened the pull request is rejected.

When somebody else says a pack id is theirs, they use the [id dispute form](https://github.com/KSAModding/content-index/issues/new?template=id-dispute.yml), as for a mod.
The forums thread that announced the pack first is the tiebreaker, see [POLICY.md](POLICY.md#filing-an-id-dispute).

The owner record is read only from the base branch, by its numeric account id.
A pull request can add an owner record only together with the first version of its pack.
A pull request that changes or deletes an owner record never merges itself, and a steward merges it, for example for a handover.

Open the pull requests for later versions from the same account, and they merge themselves.
An accepted pack version is immutable and cannot be edited, renamed, or deleted.
Publish a corrected version in a new file.
A steward retracts a broken version through its version-scoped entry in `index-status.toml`.

Every entry in `[[mods]]` names a listed mod, in its canonical spelling and not delisted, at a release the index has stamped and that is not yanked.
The pinned set must also be complete:

- Every `required` dependency of a pinned release names another pinned mod whose pinned version is inside the dependency's bounds. For an `any_of` entry, one of its members is enough.
- No pinned release has a `conflict` entry that matches another pinned mod.
- `optional`, `recommends` and `suggests` dependencies are not required. Pin one when you want it in the pack.

The checks read the dependencies from the stamped release files, so a dependency the stamper derived counts like one the mod author wrote.
A mod's loader is not a dependency, and a pack does not pin it.
The checks refuse every other entry and name it, and they name each missing or conflicting mod together with the pinned release that needs it.
They also refuse `[[vehicles]]` and `[[saves]]` until those content types exist.
A pinned mod that is `disputed` passes, and a client warns about it.

When a pinned mod has newer releases, test them and publish a new pack version.
When a mod author asks to leave your pack, publish a version without that mod, see [POLICY.md](POLICY.md#leaving-a-pack).

Checks then validate the document, inspect your latest release archive, and verify that you control the release host the listing points at.
The pull request is then labelled `listing` or `pack`, which says which kind of document it changes, and one that changes both carries both labels.

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

A SpaceDock release host is verified through the mod's source code link.
Set that link on the mod's SpaceDock page to your GitHub repository, and prove control of the repository with one of the three proofs above.

So the mod's authors decide which repository stands for the mod, and whoever controls that repository can list it.
The linked repository must not be a fork.
When you rename or transfer it, update the link on SpaceDock, because the redirect rule below covers only a repository the listing itself names.
A SpaceDock mod with no source code link, or with a link that does not name a GitHub repository, still waits for a steward.

## Changing a listing that already exists

An edit is checked against the release host your listing names right now, on `main`, and not against the one your pull request writes into it.
Otherwise anybody could point somebody else's listing at their own repository and then prove control of that.

If you point your listing at a different release host, you must prove control of both hosts: the one it comes from and the one it goes to.

Renaming or transferring the repository your listing names on GitHub is not such a move.
The old address then answers as the new one, and only somebody who controls a repository can rename or transfer it.
The check reads that redirect, so catching your listing up with its own repository stays self-service.

Handing a listing to somebody:

- **You transfer the repository itself.** The redirect above carries your consent, and the release host moved with it, so the new owner updates the listing without a steward.
- **You point the listing at a separate repository.** Nobody controls both hosts, so a steward applies it, unless you first put the incoming account's proof on your own repository, for example their `ksa-index-<username>` topic.

## After you are listed

You touch your authored document again only when the facts change: a new dependency bound, a new link, or the day you stop maintaining it.
Releases are picked up on their own.

Correcting metadata is a change here, not a new release of your content.

## no rename possible

The id is the folder name the game installs your content as, so a new id is new content and renaming the file is not an operation here.

Move to a new id in three steps:

1. List the new id, the ordinary way.
2. On the old listing set `status = "deprecated"` and `superseded_by = "<the new id>"`, and leave it listed. Clients then warn and point at the successor.
3. Remove the old listing's `[releases]` section, or the watcher opens an error issue on every release you publish: your archives now carry the new id as their folder.

Do not ask for a delisting instead. That leaves a tombstone carrying the id and nothing else, so the successor pointer and every stamped release go with it.

## Takedowns and disputes

Use the issue forms, and read [POLICY.md](POLICY.md) for what a steward does with them.
A steward decides, and the required forums link is the tiebreaker for who claimed an id first.

## Licensing your contribution

By opening a pull request you dedicate the metadata in it to the public domain under [CC0 1.0](LICENSE), and contribute any code or configuration under [MIT](LICENSE-MIT).

Your `abstract` and `description` are your own prose, and the index copies them into every stamped release file and into the snapshot that clients, mirrors, and websites fetch.

It applies only to the metadata you write here.
The content itself keeps whatever license you declare in the `license` field.
