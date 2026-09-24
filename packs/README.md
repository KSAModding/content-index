# packs

One authored TOML document per mod pack version, at `packs/<id>/<version>.toml`.

A pack has no release host and no generated half, so every version is authored by hand and is immutable once published.
A new version is a new file; an existing one is never edited or deleted.

The first pull request that creates `packs/<id>/` also adds `packs/<id>/owner.json` with the GitHub account that opened it:

```json
{
  "github_login": "your-login",
  "github_id": 123456
}
```

The account id is the numeric `id` that `https://api.github.com/users/<login>` shows.
The first claim merges itself when the id is free and the owner record names the account that opened the pull request.
The owner record becomes authority only once it is on the base branch, and a pull request that changes or deletes it waits for a steward.
Later pack versions merge themselves only when that same GitHub account, by its numeric account id, opens the pull request.

Every entry in `[[mods]]` names a listed mod, in its canonical spelling and not delisted, at a release the index has stamped and that is not yanked.
The pinned set must also be complete: every `required` dependency of a pinned release names another pinned mod whose pinned version is inside the dependency's bounds, and for an `any_of` entry one of its members is enough.
No pinned release has a `conflict` entry that matches another pinned mod, and `optional`, `recommends` and `suggests` dependencies are not required.
`[[vehicles]]` and `[[saves]]` stay empty until those content types exist.
[CONTRIBUTING.md](../CONTRIBUTING.md#claiming-and-updating-a-pack) and [RFC 0080](https://github.com/KSAModding/content-manager-design/blob/main/rfcs/0080-pack-claims-and-members.md) have the details.
