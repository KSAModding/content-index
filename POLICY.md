# Takedown and dispute policy

This is the document about how a takedown or an id dispute is filed, what a steward does with it, and what the index can and cannot do about it.

The index holds metadata and nothing else.
The files a listing points at live on the author's own release host, and the index never hosts them.
So the index can stop offering content and say why, but it cannot remove a byte from a host or from anyone's machine.

## Who acts

The stewards, listed in the [charter](https://github.com/KSAModding/content-manager-design/blob/main/CHARTER.md#who-decides) of the design repository.
They are volunteers.

One steward is enough for every action in this document.
Everything else in this repository goes through a pull request like anyone else's.

A steward who is a party to a takedown or a dispute leaves it to another steward.

## What the index can say about a listing

The index speaks through `index-status.toml`, one entry per affected id, and the shape of an entry is in the header of that file.
The author's own `status` field is a different thing since it is the author's voice about their content, and the index never writes it.

| State | What a client does | When a steward sets it |
|---|---|---|
| `delisted` | The listing and its releases leave the snapshot. A tombstone with the id and the state stays, so a client can tell "removed" from "never listed". Installs stop being offered. | A takedown that holds, an id given to somebody else, or a listing whose ownership stays dead. |
| `disputed` | The listing stays in the snapshot whole, and the client shows a warning. | An id dispute or contested ownership, while it is being resolved. |
| `retracted` | Scoped to one pack version, which the client treats like a yanked release. | A pack version that must not be installed any more. It needs a `version`. |

Every entry can carry `since` and a one-sentence `reason`.
Clients show the reason to users.

## Filing a takedown

Use the [takedown form](https://github.com/KSAModding/content-index/issues/new?template=takedown.yml).
Say which listing, what is wrong with it, and how a steward can see that for themselves: links, the license text, the forums thread, the release.
If you are the rights holder, say so, and say what you hold the rights to.

What a steward does:

1. Reads it, and asks the listing's author to answer on the issue when the case is not clear from the report alone.
2. Sets `disputed` when the answer will take time and users should know in the meantime.
3. Sets `delisted` with a reason when the takedown holds, or closes the issue with a reason when it does not.

Grounds that hold: the content breaks the law or the license of what it contains, the archive carries something harmful, the release host has already taken the files down, or the required forums thread is gone (see below).

If you are the author and want your own listing gone, read [CONTRIBUTING.md](CONTRIBUTING.md) first.
A `deprecated` status or a yanked release keeps the id, the successor pointer and every stamped release for the people who installed it.
A delisting takes all of that away and leaves a tombstone.
A steward delists an author's own listing on the author's request all the same, once the author has read that.

For a legal takedown of the files themselves, the release host's own process is the lever, because the index never held the files.
The index then delists the listing on the rights holder's request, or once the host has removed the files.
Scrubbing this repository's history is a separate and heavier operation, done only when it is legally required.

## Filing an id dispute

The id is the folder name the game installs a mod as, so two mods cannot share one, and the index gives an id to the first pull request that claims it and verifies.

Use the [id dispute form](https://github.com/KSAModding/content-index/issues/new?template=id-dispute.yml) when a listed id is one you believe is yours, or when the ownership of a listing is contested, for example after a handover.

Who was first is decided by the forums thread.
Every listing carries a required `links.forums`, tied to an Ahwoo forums account, and the thread that first announced the content under that folder name is the tiebreaker.

What a steward does:

1. Sets `disputed` on the listing as soon as the dispute is filed, so clients warn while it is open.
2. Asks both parties to answer on the issue, each with their forums thread.
3. Decides, and writes the decision on the issue.

When the id goes to the other party, the previous holder's listing is `delisted` and its releases go with it, and the content that lost the id can list again under a new id.
To a client the reassigned id is new content, because the folder name is the identity the game sees, and a user who installed the old content keeps it until they replace it.
When the dispute fails, the `disputed` entry is removed again and the listing stands as it was.

## Listings automation cannot judge

A pull request that validates but cannot prove that its author controls the release host gets the `needs-steward` label and a review request to the stewards team, with a comment that says why.

A steward merges such a pull request by hand after checking what the automation could not.

## Response expectations and escalation

The stewards are volunteers with no rota, so this document promises no response time.

After a week with no answer, mention `@KSAModding/content-manager-stewards` on the issue.
If that stays silent too, ask in the content-manager channel of the [KSA Modding Society Discord](https://discord.gg/KthZSZHSZ).

If you disagree with a decision, say so on the issue.
Any steward can reopen a takedown or a dispute on new evidence.
The process itself, including who the stewards are, is changed in the [design repository](https://github.com/KSAModding/content-manager-design), not here.

## The forums link

`links.forums` is required on every listing, and it does three jobs here.

- It ties the listing to an Ahwoo forums account, which is a person a steward can reach outside GitHub.
- It is the tiebreaker in an id dispute, as above.
- It is a tripwire: a thread the forum moderators took down, or an author who was banned there, is grounds to review the listing.

Nothing reads the thread automatically today.
If you see a listing whose thread is gone, report it with the takedown form.

## What a delisting does, and how fast

A change to `index-status.toml` on `main` triggers a snapshot build in the generated repository directly, and the hourly build is the backstop when that trigger is lost.

The honest latency of a delisting is that build, plus the cache floor of the snapshot address, a few minutes that nothing can purge, plus the poll interval of the user's client.
Minutes, not instant, and longer when the client polls rarely.

Outside the index's reach:

- Mirrors. Anyone can clone both repositories, and a mirror serves what it cloned.
- Anyone who reads `listings/` or the release files directly instead of the snapshot.
- Copies already installed, downloaded or cached. A delisting stops offering, it does not undo.
- The files themselves, which live on the release host.
