import { semverCompare, threadOf } from "./rules.js";

export const SNAPSHOT_URL = "https://ksamodding.github.io/content-index-releases/v1/index.json";

function forumsOf(authored) {
  return authored && authored.links && typeof authored.links === "object" ? authored.links.forums : undefined;
}

export function newestStable(releases) {
  const stable = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && release.release_status === "stable" && !release.yanked && typeof release.version === "string");
  stable.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return stable.length ? stable[0].version : null;
}

// The time the watcher found the download gone from its host (RFC 0078), or null.
function goneSince(release) {
  const since = release.download ? release.download.unavailable_since : undefined;
  return typeof since === "string" && since ? since : null;
}

function releaseFacts(release) {
  return {
    version: release.version,
    status: typeof release.release_status === "string" ? release.release_status : "",
    gameMin: typeof release.game_min === "string" ? release.game_min : "",
    gameMinRevision: Number.isInteger(release.game_min_revision) ? release.game_min_revision : null,
  };
}

// The releases a pack can pin, which are stamped, not yanked and still
// downloadable, newest first.
export function pinnableReleases(releases) {
  const kept = (Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string" && !goneSince(release))
    .map(releaseFacts);
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return kept;
}

// The release_status of every stamped release, yanked ones included, because a
// pin can stay on a release that was yanked after the pack was published.
export function releaseStatuses(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && typeof release.version === "string")
    .map((release) => [release.version, typeof release.release_status === "string" ? release.release_status : ""]));
}

// Every stamped release by its version, yanked ones included, with what the
// member rules of tools/check_index.py read from its release file.
function stampedReleases(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && typeof release.version === "string")
    .map((release) => [release.version, {
      yanked: release.yanked === true,
      dependencies: Array.isArray(release.dependencies) ? release.dependencies : [],
    }]));
}

// The releases that the picker leaves out only because their download is gone,
// each with the time it went away. A yanked release is not in this map, because
// its pin gets the yank note. The mark does not change what a release needs, so
// the game_min proposal still counts a pin of a gone release.
function goneReleases(releases) {
  return new Map((Array.isArray(releases) ? releases : [])
    .filter((release) => release && !release.yanked && typeof release.version === "string" && goneSince(release))
    .map((release) => [release.version, { ...releaseFacts(release), since: goneSince(release) }]));
}

// The facts of a pack's forum member list, found the way Borea finds them. A pin
// can name a mod or a mod-loader, and a release that was yanked after the pack
// was published still has its line.
function forumFacts(listing, authored) {
  const forums = forumsOf(authored);
  return {
    id: listing.id,
    name: typeof authored.name === "string" ? authored.name : "",
    authors: Array.isArray(authored.authors) ? authored.authors.filter((author) => typeof author === "string") : [],
    license: typeof authored.license === "string" ? authored.license : "",
    forums: typeof forums === "string" ? forums : "",
    downloads: new Map((Array.isArray(listing.releases) ? listing.releases : [])
      .filter((release) => release && typeof release.version === "string")
      .map((release) => [release.version, release.download && typeof release.download.url === "string" ? release.download.url : ""])),
  };
}

// Every version of a pack, retracted ones included, highest first.
function packVersions(versions) {
  const kept = versions
    .filter((entry) => entry && entry.authored && typeof entry.authored.version === "string")
    .map((entry) => ({
      version: entry.authored.version,
      releasedAt: typeof entry.authored.released_at === "string" ? entry.authored.released_at : "",
      retracted: entry.index_status && entry.index_status.state === "retracted" ? entry.index_status : null,
    }));
  kept.sort((a, b) => -(semverCompare(a.version, b.version) ?? 0));
  return kept;
}

export function indexFacts(snapshot, threadPattern) {
  const holders = new Map();
  const threads = [];
  const loaders = [];
  const mods = [];
  const members = [];
  const forum = new Map();
  const packs = new Map();
  const listed = new Map();
  for (const listing of Array.isArray(snapshot.listings) ? snapshot.listings : []) {
    if (!listing || typeof listing.id !== "string") continue;
    const folded = listing.id.toLowerCase();
    const authored = listing.authored;
    const type = authored && typeof authored.type === "string" ? authored.type : null;
    const where = `listings/${listing.id}.toml`;
    if (!holders.has(folded)) holders.set(folded, { id: listing.id, type, where });
    const thread = threadOf(threadPattern, forumsOf(authored));
    if (thread !== null) threads.push({ holder: folded, where, thread });
    if (type === "mod-loader") loaders.push({ id: listing.id, newest: newestStable(listing.releases) });
    if (type === "mod") mods.push(listing.id);
    const state = listing.index_status && typeof listing.index_status.state === "string" ? listing.index_status.state : null;
    const delisted = state === "delisted";
    if (!listed.has(folded)) listed.set(folded, { id: listing.id, type, state, stamped: stampedReleases(listing.releases) });
    if (type === "mod" && !delisted) {
      const name = typeof authored.name === "string" ? authored.name : "";
      members.push({ id: listing.id, name, releases: pinnableReleases(listing.releases), statuses: releaseStatuses(listing.releases), gone: goneReleases(listing.releases) });
    }
    if ((type === "mod" || type === "mod-loader") && !delisted && !forum.has(folded)) forum.set(folded, forumFacts(listing, authored));
  }
  for (const pack of Array.isArray(snapshot.packs) ? snapshot.packs : []) {
    if (!pack || typeof pack.id !== "string") continue;
    const folded = pack.id.toLowerCase();
    const versions = Array.isArray(pack.versions) ? pack.versions : [];
    const wheres = versions.map((entry) => {
      const version = entry && entry.authored ? entry.authored.version : undefined;
      return [entry, `packs/${pack.id}/${version}.toml`];
    });
    if (!holders.has(folded)) {
      holders.set(folded, { id: pack.id, type: "modpack", where: wheres.length ? wheres[0][1] : `packs/${pack.id}/` });
    }
    for (const [entry, where] of wheres) {
      const thread = threadOf(threadPattern, forumsOf(entry && entry.authored));
      if (thread !== null) threads.push({ holder: folded, where, thread });
    }
    if (!packs.has(folded)) packs.set(folded, { id: pack.id, status: pack.index_status || null, versions: packVersions(versions) });
  }
  const gameVersions = snapshot.game_versions && Array.isArray(snapshot.game_versions.versions)
    ? snapshot.game_versions.versions.filter((version) => typeof version === "string")
    : [];
  loaders.sort((a, b) => a.id.localeCompare(b.id));
  mods.sort((a, b) => a.localeCompare(b));
  members.sort((a, b) => a.id.localeCompare(b.id));
  return { holders, threads, threadPattern, loaders, mods, members, listed, forum, packs, gameVersions };
}

export function gameVersionChoices(gameVersions) {
  const months = [];
  for (const version of gameVersions) {
    const match = /^(\d{4})\.(\d{1,2})\./.exec(version);
    const month = match ? `${match[1]}.${Number(match[2])}` : null;
    if (month && !months.includes(month)) months.push(month);
  }
  return [...gameVersions].reverse().concat(months.reverse());
}
