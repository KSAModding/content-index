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

The account id is the numeric id from the GitHub account API.
A steward checks and accepts the first claim because a pack has no release host that can prove ownership.
The owner record is steward-owned and does not become authority until it is on the base branch.
Later pack versions merge themselves only when that same GitHub account opens the pull request.
