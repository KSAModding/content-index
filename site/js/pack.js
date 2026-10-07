import { ERROR, NOTE, semverCompare } from "./rules.js";
import { formFromDocument, releaseTime } from "./model.js";

const REVISION_BOUND = /^[0-9]{4}\.[0-9]+\.[0-9]+\.([0-9]+)$/;
const MONTH_BOUND = /^([0-9]{4})\.([0-9]+)$/;
const MONTH = /^([0-9]{4})\.([0-9]+)\./;
const SEMVER = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[^+]+)?(\+.*)?$/;
const STABILITY = ["stable", "testing", "dev"];
const PINNED_SECTIONS = ["mods", "vehicles", "saves"];
const MEMBER_SECTION = "mods";

// The semver pattern of the schema, which tools/check_index.py uses to decide
// that a pin names a release file at all.
export const PIN_VERSION = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*)?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?(?![\s\S])/;

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function fold(id) {
  return typeof id === "string" ? id.toLowerCase() : null;
}

function memberOf(index, id) {
  if (!index || typeof id !== "string" || !id) return null;
  const folded = id.toLowerCase();
  return index.members.find((member) => member.id.toLowerCase() === folded) || null;
}

// The stamped release a pin names, when it is a listed mod that is not delisted.
function stampedOf(index, id, version) {
  const listing = index.listed.get(fold(id));
  if (!listing || listing.type !== "mod" || listing.state === "delisted") return undefined;
  return listing.stamped.get(version);
}

function optionsOf(dependency) {
  return (Array.isArray(dependency.any_of) ? dependency.any_of : [dependency]).filter(isObject);
}

function requiredOf(release) {
  return release && !release.yanked ? release.dependencies.filter((dependency) => isObject(dependency) && dependency.kind === "required") : [];
}

function anyListed(index, options) {
  return options.some((option) => memberOf(index, option.id));
}

// The required dependencies of a release where no choice is a listed mod, so no
// pack can pin that release with a complete set. Each entry holds the ids of the choices.
function unlistedNeeds(index, release) {
  return requiredOf(release)
    .map(optionsOf)
    .filter((options) => options.length && !anyListed(index, options))
    .map((options) => options.map((option) => option.id));
}

// The mark in the words of Borea, such as "cannot be pinned, because it needs
// 'KittenExtensions' and one of 'ShaderExtensions', 'KittenExtensionsContinued'".
function cannotBePinned(needs) {
  const named = needs.map((ids) => {
    const quoted = ids.map((id) => `'${id}'`).join(", ");
    return ids.length === 1 ? quoted : `one of ${quoted}`;
  });
  return `cannot be pinned, because it needs ${named.join(" and ")}`;
}

// A pin the snapshot does not offer stays a choice, so loading a document never drops it.
export function memberChoices(index, current = "") {
  const choices = (index ? index.members : [])
    .filter((member) => member.releases.length)
    .map((member) => [member.id, member.name && member.name !== member.id ? `${member.name} (${member.id})` : member.id]);
  if (current && !choices.some(([id]) => id === current)) choices.push([current, `${current} (not offered by the index)`]);
  return choices;
}

export function versionChoices(index, id, current = "") {
  const member = memberOf(index, id);
  const choices = (member ? member.releases : []).map((release) => {
    const marks = release.status ? [release.status] : [];
    const needs = unlistedNeeds(index, stampedOf(index, member.id, release.version));
    if (needs.length) marks.push(cannotBePinned(needs));
    return [release.version, marks.length ? `${release.version} (${marks.join(", ")})` : release.version];
  });
  if (current && !choices.some(([version]) => version === current)) {
    choices.push([current, member && member.gone.has(current) ? `${current} (no longer downloadable)` : `${current} (not offered by the index)`]);
  }
  return choices;
}

function dateOf(time) {
  const date = /^[0-9]{4}-[0-9]{2}-[0-9]{2}/.exec(time);
  return date ? date[0] : time;
}

// The newest stable release that can be pinned, else the newest release that can
// be pinned, else the newest stable release, else the newest release.
export function defaultVersion(index, id) {
  const member = memberOf(index, id);
  if (!member || !member.releases.length) return "";
  const pinnable = member.releases.filter((release) => !unlistedNeeds(index, stampedOf(index, member.id, release.version)).length);
  const choices = pinnable.length ? pinnable : member.releases;
  const stable = choices.find((release) => release.status === "stable");
  return (stable || choices[0]).version;
}

function named(pin) {
  return `'${pin.id}' ${pin.version}`;
}

function parses(version) {
  return semverCompare(version, version) !== null;
}

// A bound that does not parse is no bound, as in tools/check_index.py.
function pinnedWithin(option, pinned) {
  const pin = pinned.get(fold(option.id));
  if (!pin || !parses(pin.version)) return false;
  const low = parses(option.min) ? semverCompare(option.min, pin.version) : -1;
  const high = parses(option.max) ? semverCompare(pin.version, option.max) : -1;
  return low <= 0 && high <= 0;
}

function bounds(option) {
  const [low, high] = [option.min, option.max];
  if (low && high) return ` ${low} to ${high}`;
  if (low) return ` ${low} or newer`;
  if (high) return ` ${high} or older`;
  return "";
}

function wanted(options) {
  const described = options.map((option) => `'${option.id}'${bounds(option)}`);
  return described.length === 1 ? described[0] : `one of ${described.join(", ")}`;
}

function pinnedInstead(options, pinned) {
  const found = options.map((option) => pinned.get(fold(option.id))).filter(Boolean).map(named);
  if (found.length) return `pins ${found.join(" and ")}`;
  return options.length === 1 ? "does not pin it" : "pins none of them";
}

// Why a pin is refused, or else the stamped release it names, as _member in tools/check_index.py.
function pinProblem(section, pin, index) {
  const { id, version } = pin;
  if (typeof id !== "string" || typeof version !== "string") return [null, null];
  if (section !== MEMBER_SECTION) return [`'${id}' cannot be pinned, because no content type for ${section} is defined yet`, null];
  const target = index.holders.get(id.toLowerCase());
  if (!target) return [`'${id}' is not a listed mod, and a pack pins only listed mods`, null];
  if (target.type === "modpack") return [null, null];
  const listing = index.listed.get(id.toLowerCase());
  if (listing.state === "delisted") return [`'${id}' is delisted, and a pack pins only listed mods`, null];
  if (target.type !== "mod") return [`'${id}' is listed as a ${target.type}, and a pack pins only mods`, null];
  if (!PIN_VERSION.test(version)) return [null, null];
  const release = listing.stamped.get(version);
  if (!release) return [`'${id}' has no stamped release ${version}`, null];
  if (release.yanked) return [`'${id}' ${version} is yanked`, null];
  return [null, release];
}

function incomplete(pin, release, pinned) {
  const problems = [];
  for (const dependency of release.dependencies) {
    if (!isObject(dependency)) continue;
    if (dependency.kind === "required") {
      const options = optionsOf(dependency);
      if (!options.some((option) => pinnedWithin(option, pinned))) {
        problems.push(`${named(pin)} requires ${wanted(options)}, and the pack ${pinnedInstead(options, pinned)}`);
      }
    } else if (dependency.kind === "conflict" && fold(dependency.id) !== pin.id.toLowerCase() && pinnedWithin(dependency, pinned)) {
      problems.push(`${named(pin)} conflicts with ${wanted([dependency])}, and the pack pins ${named(pinned.get(fold(dependency.id)))}`);
    }
  }
  return problems;
}

// Whether a pin fits the other pins, as Fits in Borea: no pack is kept from
// pinning its release, the pins meet its required dependencies, it is inside the
// bounds every other pinned release sets for its mod, and no conflict on either side matches.
export function fits(index, pins, pin) {
  const release = stampedOf(index, pin.id, pin.version);
  if (!release || release.yanked || unlistedNeeds(index, release).length) return false;
  const others = pins.filter((other) => isObject(other) && fold(other.id) !== fold(pin.id));
  const pinned = pinnedMap([pin, ...others]);
  if (incomplete(pin, release, pinned).length) return false;
  for (const other of others) {
    const found = typeof other.version === "string" ? stampedOf(index, other.id, other.version) : undefined;
    if (!found || found.yanked) continue;
    for (const dependency of found.dependencies) {
      if (!isObject(dependency)) continue;
      const options = optionsOf(dependency);
      if (!options.some((option) => fold(option.id) === fold(pin.id))) continue;
      if (dependency.kind === "required" && !options.some((option) => pinnedWithin(option, pinned))) return false;
      if (dependency.kind === "conflict" && fold(dependency.id) !== fold(other.id) && pinnedWithin(dependency, pinned)) return false;
    }
  }
  return true;
}

function pinsOf(document) {
  const found = [];
  for (const section of PINNED_SECTIONS) {
    if (!Array.isArray(document[section])) continue;
    document[section].forEach((pin, number) => {
      if (isObject(pin)) found.push({ section, pin, where: `${section}[${number}]` });
    });
  }
  return found;
}

// The first pin of each id, by casefolded id, as tools/check_index.py keys them.
function pinnedMap(pins) {
  const pinned = new Map();
  for (const pin of pins) {
    if (typeof pin.id === "string" && typeof pin.version === "string" && !pinned.has(pin.id.toLowerCase())) pinned.set(pin.id.toLowerCase(), pin);
  }
  return pinned;
}

// The member rules of RFC 0080, in the words of check_members and member_notes
// in tools/check_index.py. schemas/pack-vectors.json holds the cases both run.
export function memberMessages(document, index) {
  if (!index || document.type !== "modpack") return [];
  const found = [];
  const stamped = [];
  const pins = pinsOf(document);
  for (const { section, pin, where } of pins) {
    const [problem, release] = pinProblem(section, pin, index);
    if (problem) found.push({ level: ERROR, path: where, text: problem });
    else if (release) stamped.push({ pin, release, where });
  }
  const pinned = pinnedMap(pins.filter(({ section }) => section === MEMBER_SECTION).map(({ pin }) => pin));
  for (const { pin, release, where } of stamped) {
    for (const text of incomplete(pin, release, pinned)) found.push({ level: ERROR, path: where, text });
  }
  for (const { section, pin, where } of pins) {
    const listing = section === MEMBER_SECTION ? index.listed.get(fold(pin.id)) : null;
    if (listing && listing.type === "mod" && listing.state === "disputed") {
      found.push({ level: NOTE, path: where, text: `'${pin.id}' is disputed, and a client warns about it` });
    }
  }
  return found;
}

// The pins "Add the missing dependencies" adds: each required dependency that
// no member pins, at the newest stable release inside the bounds of every pinned
// release that requires it. Each added release can require more. What it cannot
// add, such as an any_of, stays a note for the author.
export function missingDependencies(document, index) {
  if (!index || document.type !== "modpack") return { pins: [], notes: [] };
  const authored = (Array.isArray(document.mods) ? document.mods : []).filter(isObject);
  // A pin whose release is not chosen yet still names its mod, so nothing adds a second pin of it.
  const written = new Set(authored.map((pin) => fold(pin.id)));
  let added = [];
  const requirements = () => {
    const found = [];
    for (const pin of [...authored, ...added]) {
      if (typeof pin.id !== "string" || typeof pin.version !== "string") continue;
      for (const dependency of requiredOf(stampedOf(index, pin.id, pin.version))) {
        const options = optionsOf(dependency);
        if (options.length) found.push({ pin, options });
      }
    }
    return found;
  };
  const choose = (member, needs) => member.releases.find((release) => release.status === "stable"
    && needs.every((option) => pinnedWithin(option, new Map([[fold(option.id), { id: member.id, version: release.version }]]))));
  const same = (left, right) => left.length === right.length
    && left.every((pin) => right.some((other) => other.id === pin.id && other.version === pin.version));
  // Each round chooses every added pin again from the needs of all pins, because a
  // release added later can narrow the bounds of a mod added earlier.
  for (let round = 0; round <= index.members.length; round += 1) {
    const needed = new Map();
    for (const { options } of requirements()) {
      const key = options.length === 1 ? fold(options[0].id) : null;
      if (!key || written.has(key) || !memberOf(index, key)) continue;
      if (!needed.has(key)) needed.set(key, []);
      needed.get(key).push(options[0]);
    }
    const next = [];
    for (const [key, needs] of needed) {
      const member = memberOf(index, key);
      const release = choose(member, needs);
      if (release) next.push({ id: member.id, version: release.version });
    }
    if (same(next, added)) break;
    added = next;
  }
  const ids = new Set([...authored, ...added].map((pin) => fold(pin.id)));
  const missing = requirements().filter(({ options }) => !options.some((option) => ids.has(fold(option.id))));
  // The notes are in the words of Borea, without the closing period, as every message of the page.
  const notes = missing.map(({ pin, options }) => {
    const needs = `${named(pin)} requires ${wanted(options)}`;
    if (!anyListed(index, options)) return `${needs}, and no listed mod meets this, so no pack can pin this release`;
    if (options.length > 1) return `${needs}, so pin the one you want`;
    return `${needs}, and no stable release of it is inside the bounds of every member that requires it`;
  });
  return { pins: added, notes };
}

function pinnedReleases(document, index) {
  const found = [];
  (Array.isArray(document.mods) ? document.mods : []).forEach((pin, number) => {
    if (!isObject(pin) || typeof pin.id !== "string") return;
    const member = memberOf(index, pin.id);
    const release = member ? member.releases.find((entry) => entry.version === pin.version) : undefined;
    found.push({ pin, number, member, release });
  });
  return found;
}

// A pin whose download is gone passes the member rules, so it only gets a note.
export function pinNotes(document, index) {
  if (!index || document.type !== "modpack") return [];
  const found = [];
  for (const { pin, number, member } of pinnedReleases(document, index)) {
    if (!member || !member.gone.has(pin.version)) continue;
    found.push({
      level: NOTE,
      path: `mods[${number}]`,
      text: `'${pin.id}' ${pin.version} is no longer downloadable since ${dateOf(member.gone.get(pin.version).since)}, so the page does not offer it; the pin stays as it is`,
    });
  }
  return found;
}

function olderThan(bound, release) {
  const text = typeof bound === "string" ? bound.trim() : "";
  if (!text) return true;
  if (text === release.gameMin) return false;
  const revision = REVISION_BOUND.exec(text);
  if (revision) return Number(revision[1]) < release.gameMinRevision;
  const month = MONTH_BOUND.exec(text);
  const target = MONTH_BOUND.exec(release.gameMin) || MONTH.exec(release.gameMin);
  if (!month || !target) return false;
  const [year, number] = [Number(month[1]), Number(month[2])];
  const [targetYear, targetNumber] = [Number(target[1]), Number(target[2])];
  // A month bound admits the first build of that month, which is older than any later build of it.
  return year < targetYear || (year === targetYear && number <= targetNumber);
}

// A pin of a release whose download is gone still counts, because the pin stays
// and that release still needs its game_min.
function proposedGameMin(document, index) {
  let highest = null;
  for (const { pin, member, release: offered } of pinnedReleases(document, index)) {
    const release = offered || (member ? member.gone.get(pin.version) : undefined);
    if (!release || release.gameMinRevision === null || !release.gameMin) continue;
    if (!highest || release.gameMinRevision > highest.gameMinRevision) highest = release;
  }
  return highest;
}

export function gameMinNotes(document, index) {
  if (!index || document.type !== "modpack") return [];
  const release = proposedGameMin(document, index);
  const compatibility = isObject(document.compatibility) ? document.compatibility : {};
  if (!release || !olderThan(compatibility.game_min, release)) return [];
  return [{
    level: NOTE,
    path: "compatibility.game_min",
    text: `the pinned releases need at least '${release.gameMin}', the highest game_min among them, so that is the proposed oldest game version`,
  }];
}

// The ids that the checks of a loaded document treat as its own. Only a loaded
// pack is a later version of a listed pack.
export function ownIds(base) {
  const own = isObject(base) && typeof base.id === "string" ? base.id : null;
  return { own, pack: own && base.type === "modpack" ? own : null };
}

export function packOf(index, id) {
  return index && typeof id === "string" && id ? index.packs.get(id.toLowerCase()) || null : null;
}

// The next version by SemVer, raised as npm raises a patch. A prerelease becomes
// its own release, and any other version gets the next patch number.
export function raiseVersion(version) {
  const parts = typeof version === "string" ? SEMVER.exec(version) : null;
  if (!parts) return null;
  const [major, minor, patch] = parts.slice(1, 4).map(Number);
  return parts[4] ? `${major}.${minor}.${patch}` : `${major}.${minor}.${patch + 1}`;
}

// The loaded version stays as it is except for the keys that belong to one version.
export function nextPackForm(base, pack, now = new Date()) {
  const form = formFromDocument(base);
  const highest = pack && pack.versions.length ? pack.versions[0].version : base.version;
  form.version = raiseVersion(highest) || "";
  form.releasedAt = releaseTime(now);
  form.changelog = "";
  return form;
}

// The snapshot follows main with a delay, so a version it does not know can
// already be a file there. taken answers whether that file exists.
export async function freeVersion(version, taken, tries = 20) {
  let proposed = version;
  for (let attempt = 0; attempt < tries && proposed; attempt += 1) {
    if (!(await taken(proposed))) return proposed;
    proposed = raiseVersion(proposed);
  }
  return null;
}

function stability(status) {
  const rank = STABILITY.indexOf(status);
  return rank < 0 ? STABILITY.length : rank;
}

// A pin on a yanked release keeps the stability of that release. A pin whose
// release the snapshot does not have at all is held to stable, the strictest level.
export function newerRelease(index, pin) {
  const member = isObject(pin) ? memberOf(index, pin.id) : null;
  if (!member) return null;
  const least = stability(member.statuses.has(pin.version) ? member.statuses.get(pin.version) : "stable");
  return member.releases.find((release) =>
    semverCompare(release.version, pin.version) > 0 && stability(release.status) <= least) || null;
}

// The note stays for every newer release, and fits says whether the other pins
// accept it, so the page offers to move the pin only then.
export function newerNotes(document, index) {
  if (!index || document.type !== "modpack") return [];
  const found = [];
  const pins = Array.isArray(document.mods) ? document.mods : [];
  pins.forEach((pin, number) => {
    const release = newerRelease(index, pin);
    if (!release) return;
    const moved = { id: pin.id, version: release.version };
    found.push({
      level: NOTE,
      path: `mods[${number}]`,
      text: `'${pin.id}' has a newer ${release.status ? `${release.status} ` : ""}release '${release.version}'; the pin stays until you move it`,
      newer: release.version,
      fits: fits(index, [...pins.filter((_, other) => other !== number), moved], moved),
    });
  });
  return found;
}

function names(reason, id) {
  const escaped = id.replace(/[.*+?^${}()|[\]\\-]/g, "\\$&");
  return new RegExp(`(?<![A-Za-z0-9._-])${escaped}(?![A-Za-z0-9_-]|\\.[A-Za-z0-9])`, "i").test(reason);
}

function later(a, b) {
  const [left, right] = [Date.parse(a), Date.parse(b)];
  return Number.isNaN(left) || Number.isNaN(right) || left > right;
}

// The notes and errors of a later version of a listed pack, whose id is own.
export function nextVersionNotes(document, index, own) {
  const pack = document.type === "modpack" ? packOf(index, own) : null;
  if (!pack) return [];
  const found = [];
  if (pack.status) {
    found.push({ level: NOTE, path: "id", text: `the index marks this pack ${pack.status.state}${pack.status.reason ? `: ${pack.status.reason}` : ""}` });
  }
  const pins = Array.isArray(document.mods) ? document.mods : [];
  for (const { version, retracted } of pack.versions) {
    if (!retracted) continue;
    const reason = typeof retracted.reason === "string" ? retracted.reason : "";
    found.push({ level: NOTE, path: "version", text: `version '${version}' of this pack is retracted${reason ? `: ${reason}` : ""}` });
    pins.forEach((pin, number) => {
      if (reason && isObject(pin) && typeof pin.id === "string" && names(reason, pin.id)) {
        found.push({ level: NOTE, path: `mods[${number}]`, text: `the retraction of version '${version}' names '${pin.id}': ${reason}` });
      }
    });
  }
  const highest = pack.versions[0];
  if (highest && (semverCompare(document.version, highest.version) ?? 1) <= 0) {
    found.push({
      level: ERROR,
      path: "version",
      text: `'${document.version}' is not higher than '${highest.version}', the highest version of this pack, retracted ones included`,
    });
  }
  const newest = pack.versions.filter((entry) => entry.releasedAt).sort((a, b) => Date.parse(b.releasedAt) - Date.parse(a.releasedAt))[0];
  if (newest && typeof document.released_at === "string" && !later(document.released_at, newest.releasedAt)) {
    found.push({
      level: ERROR,
      path: "released_at",
      text: `'${document.released_at}' is not later than '${newest.releasedAt}', the release time of version '${newest.version}'`,
    });
  }
  return found;
}

// The member list that forum rule 4.3 asks a pack thread for, in the words Borea
// writes it. A pin without an id or a release has no line yet, so it gives null.
export function forumLines(document, index) {
  return (Array.isArray(document.mods) ? document.mods : []).filter(isObject).map((pin) => {
    if (typeof pin.id !== "string" || !pin.id || typeof pin.version !== "string" || !pin.version) return null;
    const listing = index ? index.forum.get(pin.id.toLowerCase()) : undefined;
    if (!listing || !listing.downloads.has(pin.version)) return `${pin.id} ${pin.version} - Not listed in the content index`;
    return `${listing.name || listing.id} ${pin.version} - Author: ${listing.authors.join(", ")} - License: ${listing.license}`
      + ` - Download: ${listing.downloads.get(pin.version)} - Thread: ${listing.forums}`;
  });
}
