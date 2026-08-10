# packs

One authored TOML document per mod pack version, at `packs/<id>/<version>.toml`.

A pack has no release host and no generated half, so every version is authored by hand and is immutable once published.
A new version is a new file; an existing one is never edited or deleted.

The first pull request that creates `packs/<id>/` claims the id.
