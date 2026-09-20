import { RECORD_KEYS } from "./images.js";

export const PLATFORMS = ["windows", "linux", "macos"];
export const KINDS = ["required", "optional", "recommends", "suggests", "conflict"];
export const ANCHORS = ["mods", "user-data", "game-root", "standalone"];
const FIXED_LINKS = ["forums", "repository", "bugtracker"];
const LINK_ORDER = ["forums", "repository", "spacedock", "bugtracker"];

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function text(value) {
  return value === undefined || value === null ? "" : String(value);
}

export function emptyRecord(withId) {
  const record = { url: "", sha256: "", width: "", height: "", size: "", license: "", attribution: "", source: "" };
  return withId ? { id: "", ...record } : record;
}

export function emptyForm() {
  return {
    id: "",
    type: "mod",
    github: "",
    spacedock: "",
    authority: "",
    name: "",
    authors: "",
    abstract: "",
    description: "",
    license: "",
    links: { forums: "", repository: "", bugtracker: "" },
    extraLinks: [],
    gameMin: "",
    gameMax: "",
    os: [],
    loaderId: "",
    loaderMin: "",
    loaderMax: "",
    dependencies: [],
    tags: [],
    icon: null,
    descriptionImages: [],
    installTarget: "",
    launch: "",
    contentDir: "",
    contentPath: "",
    platforms: Object.fromEntries(PLATFORMS.map((name) => [name, { launch: "", runtime: "" }])),
  };
}

function recordForm(record, withId) {
  const form = emptyRecord(withId);
  for (const key of Object.keys(form)) form[key] = text(record[key]);
  return form;
}

export function formFromDocument(document) {
  const form = emptyForm();
  form.id = text(document.id);
  form.type = document.type === "mod-loader" ? "mod-loader" : "mod";
  const releases = isObject(document.releases) ? document.releases : {};
  form.github = text(releases.github);
  form.spacedock = text(releases.spacedock);
  form.authority = text(releases.authority);
  form.name = text(document.name);
  form.authors = Array.isArray(document.authors) ? document.authors.map(text).join(", ") : "";
  form.abstract = text(document.abstract);
  form.description = text(document.description);
  form.license = text(document.license);
  const links = isObject(document.links) ? document.links : {};
  for (const key of FIXED_LINKS) form.links[key] = text(links[key]);
  form.extraLinks = Object.keys(links).filter((key) => !FIXED_LINKS.includes(key)).map((key) => ({ key, url: text(links[key]) }));
  const compatibility = isObject(document.compatibility) ? document.compatibility : {};
  form.gameMin = text(compatibility.game_min);
  form.gameMax = text(compatibility.game_max);
  form.os = Array.isArray(compatibility.os) ? compatibility.os.map(text) : [];
  const loader = isObject(document.loader) ? document.loader : {};
  form.loaderId = text(loader.id);
  form.loaderMin = text(loader.min);
  form.loaderMax = text(loader.max);
  form.dependencies = (Array.isArray(document.dependencies) ? document.dependencies : []).map((entry) =>
    isObject(entry) && entry.any_of === undefined
      ? { id: text(entry.id), kind: text(entry.kind), min: text(entry.min), max: text(entry.max) }
      : { kept: entry },
  );
  form.tags = Array.isArray(document.tags) ? document.tags.map(text) : [];
  const images = isObject(document.images) ? document.images : {};
  form.icon = isObject(images.icon) ? recordForm(images.icon, false) : null;
  form.descriptionImages = (Array.isArray(images.description) ? images.description : [])
    .filter(isObject)
    .map((record) => recordForm(record, true));
  const install = isObject(document.install) ? document.install : {};
  const provides = isObject(document.provides) ? document.provides : {};
  form.installTarget = text(install.target);
  form.launch = text(provides.launch);
  form.contentDir = text(provides["content-dir"]);
  form.contentPath = text(provides["content-path"]);
  const platforms = isObject(provides.platform) ? provides.platform : {};
  for (const name of PLATFORMS) {
    const entry = isObject(platforms[name]) ? platforms[name] : {};
    form.platforms[name] = { launch: text(entry.launch), runtime: text(entry.runtime) };
  }
  return form;
}

function set(target, key, value) {
  if (value === undefined || value === "" || (Array.isArray(value) && !value.length) || (isObject(value) && !Object.keys(value).length)) {
    delete target[key];
  } else {
    target[key] = value;
  }
}

function trimmed(value) {
  return text(value).trim();
}

function integerOr(value) {
  const written = trimmed(value);
  return /^[0-9]+$/.test(written) && Number.isSafeInteger(Number(written)) ? Number(written) : written;
}

export function recordFromForm(form) {
  const record = {};
  for (const key of RECORD_KEYS) {
    if (!(key in form)) continue;
    set(record, key, ["width", "height", "size"].includes(key) ? integerOr(form[key]) : trimmed(form[key]));
  }
  return record;
}

export function documentFromForm(form, base) {
  const document = base ? structuredClone(base) : {};
  set(document, "spec_version", document.spec_version ?? 1);
  set(document, "id", trimmed(form.id));
  set(document, "type", form.type);
  set(document, "name", trimmed(form.name));
  const unchangedAuthors = Array.isArray(document.authors) && document.authors.map(text).join(", ") === form.authors;
  if (!unchangedAuthors) set(document, "authors", text(form.authors).split(",").map((name) => name.trim()).filter(Boolean));
  set(document, "abstract", trimmed(form.abstract));
  set(document, "description", text(form.description).trim() ? text(form.description) : "");
  set(document, "license", trimmed(form.license));
  set(document, "tags", [...new Set(form.tags.map(trimmed).filter(Boolean))]);

  const releases = {};
  set(releases, "github", trimmed(form.github));
  set(releases, "spacedock", integerOr(form.spacedock));
  set(releases, "authority", releases.github !== undefined && releases.spacedock !== undefined ? trimmed(form.authority) : "");
  set(document, "releases", releases);

  const wanted = new Map(FIXED_LINKS.map((key) => [key, trimmed(form.links[key])]));
  for (const { key, url } of form.extraLinks) {
    if (trimmed(key)) wanted.set(trimmed(key), trimmed(url));
  }
  const order = base && isObject(base.links) ? Object.keys(base.links) : LINK_ORDER;
  const links = {};
  for (const key of [...order.filter((name) => wanted.has(name)), ...wanted.keys()]) {
    if (!(key in links)) set(links, key, wanted.get(key));
  }
  set(document, "links", links);

  const compatibility = isObject(document.compatibility) ? document.compatibility : {};
  set(compatibility, "game_min", trimmed(form.gameMin));
  set(compatibility, "game_max", trimmed(form.gameMax));
  set(compatibility, "os", PLATFORMS.filter((name) => form.os.includes(name)));
  set(document, "compatibility", compatibility);

  if (form.type === "mod") {
    const loader = {};
    set(loader, "id", trimmed(form.loaderId));
    set(loader, "min", trimmed(form.loaderMin));
    set(loader, "max", trimmed(form.loaderMax));
    set(document, "loader", loader.id === undefined ? {} : loader);
  } else {
    delete document.loader;
  }

  const dependencies = [];
  for (const entry of form.dependencies) {
    if (entry.kept !== undefined) {
      dependencies.push(entry.kept);
      continue;
    }
    if (!trimmed(entry.id)) continue;
    const dependency = {};
    set(dependency, "id", trimmed(entry.id));
    set(dependency, "kind", trimmed(entry.kind) || "required");
    set(dependency, "min", trimmed(entry.min));
    set(dependency, "max", trimmed(entry.max));
    dependencies.push(dependency);
  }
  set(document, "dependencies", dependencies);

  const images = isObject(document.images) ? document.images : {};
  set(images, "icon", form.icon ? recordFromForm(form.icon) : undefined);
  set(images, "description", form.descriptionImages.map(recordFromForm));
  set(document, "images", images);

  if (form.type === "mod-loader") {
    const install = isObject(document.install) ? document.install : {};
    set(install, "target", trimmed(form.installTarget));
    set(document, "install", install);
    const provides = isObject(document.provides) ? document.provides : {};
    set(provides, "launch", trimmed(form.launch));
    set(provides, "content-dir", trimmed(form.contentDir));
    set(provides, "content-path", trimmed(form.contentPath));
    const platforms = isObject(provides.platform) ? provides.platform : {};
    for (const name of PLATFORMS) {
      const entry = isObject(platforms[name]) ? platforms[name] : {};
      set(entry, "runtime", trimmed(form.platforms[name].runtime));
      set(entry, "launch", trimmed(form.platforms[name].launch));
      set(platforms, name, entry);
    }
    set(provides, "platform", platforms);
    set(document, "provides", provides);
  }
  return document;
}
