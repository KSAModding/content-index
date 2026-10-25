export const INDEX_REPOSITORY = "KSAModding/content-index";
// GitHub refused a link of about 5,900 characters while it forked the index for a new author (#110), so stay at the 2,000 that browsers and servers commonly accept.
export const URL_LIMIT = 2000;
export const PASTE_NEW = "The file is too long for the link. The button copies it, so paste it into the empty file on GitHub.";
export const PASTE_EDIT = "GitHub opens the old file. The button copies your new file, so replace the whole old file with it.";
const REPOSITORY = /^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?\/[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$/;

// The folder of each type that is not a mod, mod loader or pack (RFC 0085).
const FOLDERS = { vehicle: "vehicles", save: "saves" };

function listingFolder(type) {
  return Object.hasOwn(FOLDERS, type) ? FOLDERS[type] : "listings";
}

// The top folder a document of this type lives in.
export function folderOf(type) {
  return type === "modpack" ? "packs" : listingFolder(type);
}

export function listingPath(id, type = "mod") {
  return `${listingFolder(type)}/${id}.toml`;
}

export function packPath(id, version) {
  return `packs/${id}/${version}.toml`;
}

export function ownerPath(id) {
  return `packs/${id}/owner.json`;
}

// The path a document belongs at, with a placeholder for what is not written yet.
// A link encodes each part, so an id or a version cannot add a folder.
export function documentPath(document, encode = (part) => part) {
  const id = encode(String(document.id || "<id>"));
  return document.type === "modpack" ? packPath(id, encode(String(document.version || "<version>"))) : listingPath(id, document.type);
}

// Raw GitHub, not the contents API, which allows 60 calls an hour without a token.
export function rawFileUrl(encodedPath) {
  return `https://raw.githubusercontent.com/${INDEX_REPOSITORY}/main/${encodedPath}`;
}

export function rawListingUrl(id, type) {
  return rawFileUrl(listingPath(encodeURIComponent(id), type));
}

export function rawPackUrl(id, version) {
  return rawFileUrl(packPath(encodeURIComponent(id), encodeURIComponent(version)));
}

export function rawOwnerUrl(id) {
  return rawFileUrl(ownerPath(encodeURIComponent(id)));
}

export function newFileUrl(encodedPath, text) {
  const base = `https://github.com/${INDEX_REPOSITORY}/new/main?filename=${encodedPath}`;
  const filled = `${base}&value=${encodeURIComponent(text)}`;
  return filled.length <= URL_LIMIT ? { url: filled, filled: true } : { url: base, filled: false };
}

export function editUrl(id, type) {
  return `https://github.com/${INDEX_REPOSITORY}/edit/main/${listingPath(encodeURIComponent(id), type)}`;
}

// A loaded listing is changed in place. A loaded pack version is immutable, so
// its next version is always a new file.
export function pullRequestLink(encodedPath, text, base = null) {
  if (base && base.type !== "modpack") return { url: editUrl(base.id, base.type), step: PASTE_EDIT };
  const link = newFileUrl(encodedPath, text);
  return { url: link.url, step: link.filled ? "" : PASTE_NEW };
}

// The copy comes before the new tab, because the tab takes the focus and the
// browser refuses to write the clipboard for a page that does not have it.
export async function copyAndOpen(url, text, clipboard, open) {
  let copied = true;
  try {
    await clipboard.writeText(text);
  } catch {
    copied = false;
  }
  const tab = open(url);
  if (tab) tab.opener = null;
  return { copied, opened: Boolean(tab) };
}

export function repositoryApiUrl(repository) {
  return REPOSITORY.test(repository) ? `https://api.github.com/repos/${repository}` : null;
}

export function prefillFromRepository(answer) {
  const license = answer.license && answer.license.spdx_id;
  const htmlUrl = typeof answer.html_url === "string" ? answer.html_url : "";
  return {
    name: typeof answer.name === "string" ? answer.name : "",
    abstract: typeof answer.description === "string" ? answer.description.trim() : "",
    license: license && license !== "NOASSERTION" && license !== "OTHER" ? license : "",
    repository: htmlUrl,
    bugtracker: htmlUrl && answer.has_issues ? `${htmlUrl}/issues` : "",
    owner: answer.owner && typeof answer.owner.login === "string" ? answer.owner.login : "",
    organization: Boolean(answer.owner && answer.owner.type === "Organization"),
    fork: Boolean(answer.fork),
  };
}
