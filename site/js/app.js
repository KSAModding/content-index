import { createChecker, ERROR, NOTE, ABSTRACT_LIMIT } from "./rules.js";
import { parseDocument, writeDocument } from "./toml.js";
import { indexFacts, gameVersionChoices, SNAPSHOT_URL } from "./snapshot.js";
import { emptyForm, emptyRecord, formFromDocument, documentFromForm, KINDS, PLATFORMS } from "./model.js";
import { measure, readCapped, LIMITS, MEASURE_FACTOR, ICON, DESCRIPTION } from "./images.js";
import { renderPreview } from "./markdown.js";
import { zipNames, inspectArchive, StampError } from "./archive.js";
import { newFileUrl, editUrl, rawListingUrl, repositoryApiUrl, prefillFromRepository, listingPath } from "./github.js";

const STORAGE_KEY = "ksa-listing-page/v1";
const TIMEOUT = 20000;
const SECTION_INPUTS = { links: "link-forums", compatibility: "game-min" };
const MANUAL = new Set(["msg-load", "msg-prefill", "msg-output", "msg-pr", "archive-result"]);

const $ = (id) => document.getElementById(id);

let checker = null;
let index = null;
let snapshotState = "loading";
let state = { mode: "new", baseText: null, base: null, form: emptyForm() };
const measured = new WeakMap();
const tickets = new WeakMap();
let archiveNames = null;
let archiveTicket = null;
let current = { document: {}, text: "", messages: [] };
let saveTimer = null;
const touched = new Set();
let tagsTouched = false;

function element(tag, attributes = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "text") node.textContent = value;
    else if (name === "className") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children) node.append(child);
  return node;
}

function say(container, level, text) {
  const target = typeof container === "string" ? $(container) : container;
  target.replaceChildren();
  if (text) target.append(line(level, text));
}

function line(level, text) {
  const label = level === ERROR ? "Error" : level === NOTE ? "Note" : "";
  const node = element("p", { className: `msg ${level || "info"}` });
  if (label) node.append(element("span", { className: "label", text: label }), " ");
  node.append(text);
  return node;
}

function status(text) {
  $("status").textContent = text;
}

function persist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ mode: state.mode, baseText: state.baseText, form: state.form }));
    } catch {
      // Storage can be full or blocked, and the page works without it.
    }
  }, 300);
}

function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    if (!saved || typeof saved !== "object" || !saved.form) return;
    const form = { ...emptyForm(), ...saved.form };
    form.platforms = { ...emptyForm().platforms, ...form.platforms };
    form.links = { ...emptyForm().links, ...form.links };
    state = {
      mode: saved.mode === "edit" && saved.baseText ? "edit" : "new",
      baseText: saved.mode === "edit" ? saved.baseText : null,
      base: saved.mode === "edit" && saved.baseText ? parseDocument(saved.baseText) : null,
      form,
    };
  } catch {
    state = { mode: "new", baseText: null, base: null, form: emptyForm() };
  }
}

const FIELDS = {
  id: ["id"],
  type: ["type"],
  github: ["github"],
  spacedock: ["spacedock"],
  authority: ["authority"],
  name: ["name"],
  authors: ["authors"],
  abstract: ["abstract"],
  description: ["description"],
  license: ["license"],
  "link-forums": ["links", "forums"],
  "link-repository": ["links", "repository"],
  "link-bugtracker": ["links", "bugtracker"],
  "game-min": ["gameMin"],
  "game-max": ["gameMax"],
  "loader-min": ["loaderMin"],
  "loader-max": ["loaderMax"],
  "install-target": ["installTarget"],
  launch: ["launch"],
  "content-dir": ["contentDir"],
  "content-path": ["contentPath"],
};

function readPath(path) {
  return path.reduce((value, step) => value[step], state.form);
}

function writePath(path, value) {
  const last = path[path.length - 1];
  path.slice(0, -1).reduce((target, step) => target[step], state.form)[last] = value;
}

function bindStatic() {
  for (const [id, path] of Object.entries(FIELDS)) {
    const input = $(id);
    const event = input.tagName === "SELECT" ? "change" : "input";
    input.addEventListener("blur", () => {
      if (!touched.has(input)) {
        touched.add(input);
        refresh();
      }
    });
    input.addEventListener(event, () => {
      touched.add(input);
      writePath(path, input.value);
      if (id === "type") renderTypeSteps();
      refresh();
    });
  }
  $("loader-id").addEventListener("change", () => {
    const previous = loaderDefault(state.form.loaderId);
    state.form.loaderId = $("loader-id").value;
    if (!state.form.loaderMin || state.form.loaderMin === previous) {
      state.form.loaderMin = loaderDefault(state.form.loaderId) || "";
      $("loader-min").value = state.form.loaderMin;
    }
    renderLoaderBounds();
    refresh();
  });
  $("os").addEventListener("change", () => {
    state.form.os = [...$("os").querySelectorAll("input:checked")].map((box) => box.value);
    refresh();
  });
  $("add-link").addEventListener("click", () => {
    state.form.extraLinks.push({ key: "", url: "" });
    renderExtraLinks();
    refresh();
    $("extra-links").lastElementChild.querySelector("input").focus();
  });
  $("add-dependency").addEventListener("click", () => {
    state.form.dependencies.push({ id: "", kind: "required", min: "", max: "" });
    renderDependencies();
    refresh();
    $("dependencies").lastElementChild.querySelector("input").focus();
  });
  $("add-tag").addEventListener("click", addFreeTag);
  $("tag-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addFreeTag();
    }
  });
  $("add-icon").addEventListener("click", () => {
    state.form.icon = emptyRecord(false);
    renderImages();
    refresh();
    $("icon").querySelector("input").focus();
  });
  $("add-image").addEventListener("click", () => {
    state.form.descriptionImages.push(emptyRecord(true));
    renderImages();
    refresh();
    $("description-images").lastElementChild.querySelector("input").focus();
  });
  $("preview-box").addEventListener("toggle", renderDescriptionPreview);
  $("archive").addEventListener("change", readArchive);
  $("prefill").addEventListener("click", prefill);
  $("copy").addEventListener("click", () => copyOutput("msg-output"));
  $("save").addEventListener("click", saveOutput);
  $("open-pr").addEventListener("click", openPullRequest);
  $("form").addEventListener("submit", (event) => event.preventDefault());
  for (const radio of document.querySelectorAll("input[name=mode]")) {
    radio.addEventListener("change", () => setMode(radio.value));
  }
  $("load-button").addEventListener("click", loadListing);
  $("load-id").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadListing();
    }
  });
  $("reset").addEventListener("click", () => {
    if (!window.confirm("Clear the form and start over?")) return;
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing to clear when storage is blocked.
    }
    state = { mode: "new", baseText: null, base: null, form: emptyForm() };
    archiveNames = null;
    archiveTicket = null;
    $("archive").value = "";
    say("archive-result");
    say("msg-load");
    say("msg-prefill");
    renderAll();
  });
}

function setMode(mode) {
  state.mode = mode;
  if (mode === "new") {
    state.base = null;
    state.baseText = null;
  }
  renderMode();
  refresh();
}

function renderMode() {
  const editing = state.mode === "edit";
  for (const radio of document.querySelectorAll("input[name=mode]")) radio.checked = radio.value === state.mode;
  $("load").hidden = !editing;
  $("id").readOnly = editing && Boolean(state.base);
  $("editing").hidden = !(editing && state.base);
  $("editing").textContent = editing && state.base ? `Changing ${listingPath(state.form.id)}. The id cannot change.` : "";
}

function renderFields() {
  for (const [id, path] of Object.entries(FIELDS)) $(id).value = readPath(path);
  for (const box of $("os").querySelectorAll("input")) box.checked = state.form.os.includes(box.value);
}

function loaderDefault(id) {
  const loader = index && index.loaders.find((entry) => entry.id === id);
  return loader ? loader.newest : null;
}

function renderLoaderOptions() {
  const select = $("loader-id");
  const ids = index ? index.loaders.map((entry) => entry.id) : [];
  if (state.form.loaderId && !ids.includes(state.form.loaderId)) ids.push(state.form.loaderId);
  select.replaceChildren(select.options[0], ...ids.map((id) => element("option", { value: id, text: id })));
  select.value = state.form.loaderId;
}

function renderLoaderBounds() {
  $("loader-bounds").hidden = !state.form.loaderId;
}

function renderTypeSteps() {
  const loader = state.form.type === "mod-loader";
  $("loader-step").hidden = loader;
  $("launch-step").hidden = !loader;
}

function inputField(label, value, onInput, attributes = {}) {
  const id = `f${Math.random().toString(36).slice(2)}`;
  const input = element("input", { id, value, autocomplete: "off", spellcheck: "false", ...attributes });
  input.value = value;
  input.addEventListener("input", () => {
    onInput(input.value);
    refresh();
  });
  return element("div", { className: "field grow" }, [element("label", { for: id, text: label }), input]);
}

function selectField(label, value, options, onChange) {
  const id = `f${Math.random().toString(36).slice(2)}`;
  const select = element("select", { id }, options.map(([optionValue, text]) => element("option", { value: optionValue, text })));
  select.value = value;
  select.addEventListener("change", () => {
    onChange(select.value);
    refresh();
  });
  return element("div", { className: "field grow" }, [element("label", { for: id, text: label }), select]);
}

function removeButton(label, onClick) {
  return element("button", { type: "button", className: "quiet", text: "Remove", "aria-label": label, onclick: onClick });
}

function renderExtraLinks() {
  $("extra-links").replaceChildren(...state.form.extraLinks.map((link, number) => {
    const messages = element("div", { className: "messages", "aria-live": "polite", "data-link": number });
    return element("div", { className: "item" }, [
      element("div", { className: "row" }, [
        inputField("Link name", link.key, (value) => { link.key = value; }, { placeholder: "discussions" }),
        inputField("Address", link.url, (value) => { link.url = value; }, { type: "url" }),
        removeButton(`Remove the link ${link.key}`, () => {
          state.form.extraLinks.splice(number, 1);
          renderExtraLinks();
          refresh();
        }),
      ]),
      messages,
    ]);
  }));
}

function renderPlatforms() {
  $("platforms").replaceChildren(...PLATFORMS.map((name) => {
    const entry = state.form.platforms[name];
    return element("div", { className: "item" }, [
      element("div", { className: "row" }, [
        inputField(`File started on ${name}`, entry.launch, (value) => { entry.launch = value; }, { "data-field": `provides.platform.${name}.launch` }),
        selectField(`How it starts on ${name}`, entry.runtime, [["", "as an executable"], ["dotnet", "with dotnet"]], (value) => {
          entry.runtime = value;
        }),
      ]),
      element("div", { id: `msg-provides.platform.${name}`, className: "messages", "aria-live": "polite" }),
    ]);
  }));
}

function renderDependencies() {
  $("dependencies").replaceChildren(...state.form.dependencies.map((entry, number) => {
    const remove = removeButton("Remove this dependency", () => {
      state.form.dependencies.splice(number, 1);
      renderDependencies();
      refresh();
    });
    const messages = element("div", { className: "messages", "aria-live": "polite", "data-dependency": number });
    if (entry.kept !== undefined) {
      const names = Array.isArray(entry.kept.any_of) ? entry.kept.any_of.map((member) => member && member.id).join(" or ") : "";
      return element("div", { className: "item" }, [
        element("p", { className: "hint", text: `${entry.kept.kind || ""} ${names}: alternatives, kept as they are.` }),
        remove,
        messages,
      ]);
    }
    return element("div", { className: "item" }, [
      element("div", { className: "row" }, [
        inputField("Id", entry.id, (value) => { entry.id = value; }, { list: "mod-ids" }),
        selectField("Kind", entry.kind || "required", KINDS.map((kind) => [kind, kind]), (value) => { entry.kind = value; }),
      ]),
      element("div", { className: "row" }, [
        inputField("Oldest version (optional)", entry.min, (value) => { entry.min = value; }),
        inputField("Newest version (optional)", entry.max, (value) => { entry.max = value; }),
        remove,
      ]),
      messages,
    ]);
  }));
}

function renderTags() {
  const curated = checker ? checker.vocabulary : [];
  $("curated-tags").replaceChildren(...curated.map((entry) => {
    const on = state.form.tags.includes(entry.tag);
    return element("button", {
      type: "button",
      className: "chip",
      "aria-pressed": on ? "true" : "false",
      title: entry.meaning,
      text: entry.name || entry.tag,
      onclick: () => {
        tagsTouched = true;
        state.form.tags = on ? state.form.tags.filter((tag) => tag !== entry.tag) : [...state.form.tags, entry.tag];
        renderTags();
        refresh();
      },
    });
  }));
  const known = new Set(curated.map((entry) => entry.tag));
  $("free-tags").replaceChildren(...state.form.tags.filter((tag) => !known.has(tag)).map((tag) =>
    element("span", { className: "chip on" }, [
      tag,
      element("button", {
        type: "button",
        className: "chip-remove",
        "aria-label": `Remove the tag ${tag}`,
        text: "x",
        onclick: () => {
          state.form.tags = state.form.tags.filter((other) => other !== tag);
          renderTags();
          refresh();
        },
      }),
    ])));
}

function addFreeTag() {
  const tag = $("tag-input").value.trim();
  tagsTouched = true;
  if (!tag) return;
  if (!state.form.tags.includes(tag)) state.form.tags.push(tag);
  $("tag-input").value = "";
  renderTags();
  refresh();
}

function describeRecord(record) {
  const facts = measured.get(record);
  if (facts && facts.facts) {
    return `${facts.facts.format}, ${facts.facts.width} by ${facts.facts.height} pixels, ${facts.size} bytes, measured now.`;
  }
  if (record.sha256) {
    return `${record.width} by ${record.height} pixels, ${record.size} bytes, as recorded. Select the file to measure it again.`;
  }
  return "Not measured yet.";
}

function claim(record) {
  const ticket = {};
  tickets.set(record, ticket);
  return ticket;
}

async function measureBytes(record, role, bytes, facts, preview, ticket) {
  const result = await measure(bytes, role);
  if (tickets.get(record) !== ticket) return;
  const previous = measured.get(record);
  if (previous && previous.url) URL.revokeObjectURL(previous.url);
  const url = result.facts && !result.problems.length ? URL.createObjectURL(new Blob([bytes])) : null;
  measured.set(record, { ...result, url });
  record.sha256 = result.sha256;
  record.size = String(result.size);
  record.width = result.facts ? String(result.facts.width) : "";
  record.height = result.facts ? String(result.facts.height) : "";
  facts.textContent = describeRecord(record);
  preview.replaceChildren(...(url ? [element("img", { src: url, alt: "" })] : []));
  refresh();
}

async function measureFromUrl(record, role, facts, preview, messages) {
  const address = record.url.trim();
  if (!/^https:\/\//i.test(address)) {
    say(messages, ERROR, "Give the https address of the image first.");
    return;
  }
  const ticket = claim(record);
  const cap = LIMITS[role].cap;
  say(messages, null, "Fetching the image.");
  let failure = null;
  let bytes = null;
  try {
    const response = await fetch(address, {
      mode: "cors", credentials: "omit", referrerPolicy: "no-referrer", cache: "no-store", signal: AbortSignal.timeout(TIMEOUT),
    });
    const length = Number(response.headers.get("Content-Length"));
    if (!response.ok) failure = [ERROR, `${address} answered HTTP ${response.status}`];
    else if (length > cap) failure = [ERROR, `${address} is ${length} bytes, above the cap of ${cap}`];
    else bytes = await readCapped(response, cap);
    if (!failure && !bytes) failure = [ERROR, `${address} is larger than the cap of ${cap} bytes`];
  } catch (error) {
    failure = error && error.name === "TimeoutError"
      ? [NOTE, "The host did not answer in time. Download the image and select the file instead."]
      : [NOTE, "The host does not let this page read the image. Download it and select the file instead."];
  }
  if (tickets.get(record) !== ticket) return;
  say(messages, ...(failure || []));
  if (bytes) await measureBytes(record, role, bytes, facts, preview, ticket);
}

function imageEditor(record, role, place, onRemove) {
  const facts = element("p", { className: "hint", text: describeRecord(record) });
  const previous = measured.get(record);
  const preview = element("div", { className: "thumb" }, previous && previous.url ? [element("img", { src: previous.url, alt: "" })] : []);
  const fetchMessages = element("div", { className: "messages", "aria-live": "polite" });
  const fileId = `f${Math.random().toString(36).slice(2)}`;
  const file = element("input", { id: fileId, type: "file", accept: "image/png,image/jpeg,image/webp" });
  file.addEventListener("change", async () => {
    const chosen = file.files && file.files[0];
    if (!chosen) return;
    const ticket = claim(record);
    if (chosen.size > LIMITS[role].cap * MEASURE_FACTOR) {
      say(fetchMessages, ERROR, `the image is larger than the cap of ${LIMITS[role].cap} bytes`);
      return;
    }
    say(fetchMessages);
    let bytes;
    try {
      bytes = new Uint8Array(await chosen.arrayBuffer());
    } catch {
      if (tickets.get(record) === ticket) say(fetchMessages, ERROR, "The browser could not read the file. Select it again.");
      return;
    }
    await measureBytes(record, role, bytes, facts, preview, ticket);
  });
  const children = [];
  if (role === DESCRIPTION) {
    children.push(inputField("Image id", record.id, (value) => { record.id = value; }, { placeholder: "settings-window", "data-field": `${place}.id` }));
  }
  children.push(
    element("div", { className: "field" }, [element("label", { for: fileId, text: "Image file" }), file]),
    element("div", { className: "row" }, [
      inputField("Https address where it is or will be hosted", record.url, (value) => { record.url = value; }, { type: "url", "data-field": `${place}.url` }),
      element("button", { type: "button", text: "Measure from the address", onclick: () => measureFromUrl(record, role, facts, preview, fetchMessages) }),
    ]),
    fetchMessages,
    element("div", { className: "measure" }, [preview, facts]),
    element("div", { className: "row" }, [
      inputField("License of the image (optional)", record.license, (value) => { record.license = value; }, { placeholder: "the mod's license", "data-field": `${place}.license` }),
      inputField("Credit (optional)", record.attribution, (value) => { record.attribution = value; }, { "data-field": `${place}.attribution` }),
    ]),
    element("div", { className: "row" }, [
      inputField("Address of the original work (optional)", record.source, (value) => { record.source = value; }, { type: "url", "data-field": `${place}.source` }),
      removeButton(role === ICON ? "Remove the icon" : "Remove this image", onRemove),
    ]),
    element("div", { id: `msg-${place}`, className: "messages", "aria-live": "polite" }),
  );
  return element("div", { className: "item" }, children);
}

function renderImages() {
  const icon = state.form.icon;
  $("icon").replaceChildren(...(icon ? [imageEditor(icon, ICON, "images.icon", () => {
    state.form.icon = null;
    renderImages();
    refresh();
  })] : []));
  $("add-icon").hidden = Boolean(icon);
  $("description-images").replaceChildren(...state.form.descriptionImages.map((record, number) =>
    imageEditor(record, DESCRIPTION, `images.description[${number}]`, () => {
      state.form.descriptionImages.splice(number, 1);
      renderImages();
      refresh();
    })));
  $("add-image").hidden = Boolean(checker) && state.form.descriptionImages.length >= checker.maxDescriptionImages;
}

const ALLOWED = new Set(["P", "H1", "H2", "H3", "H4", "H5", "H6", "EM", "STRONG", "CODE", "PRE", "BLOCKQUOTE", "UL", "OL",
  "LI", "A", "IMG", "HR", "BR", "SPAN"]);

function sanitize(html) {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const copy = (source) => {
    const fragment = document.createDocumentFragment();
    for (const node of source.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        fragment.append(node.textContent);
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (!ALLOWED.has(node.tagName)) {
          fragment.append(copy(node));
          continue;
        }
        const clean = document.createElement(node.tagName.toLowerCase());
        if (node.tagName === "A") {
          const href = node.getAttribute("href") || "";
          if (/^(?:https?:|mailto:)/i.test(href)) {
            clean.setAttribute("href", href);
            clean.setAttribute("rel", "noopener noreferrer nofollow");
            clean.setAttribute("target", "_blank");
          }
        } else if (node.tagName === "IMG") {
          const src = node.getAttribute("src") || "";
          if (!src.startsWith("blob:")) continue;
          clean.setAttribute("src", src);
          clean.setAttribute("alt", node.getAttribute("alt") || "");
        } else if (node.tagName === "OL" && node.getAttribute("start")) {
          clean.setAttribute("start", node.getAttribute("start"));
        } else if (node.tagName === "SPAN" && node.className === "missing-image") {
          clean.className = "missing-image";
        }
        clean.append(copy(node));
        fragment.append(clean);
      }
    }
    return fragment;
  };
  return copy(parsed.body);
}

function renderDescriptionPreview() {
  if (!$("preview-box").open) return;
  const images = new Map();
  for (const record of state.form.descriptionImages) {
    const facts = measured.get(record);
    if (facts && facts.url && record.id) images.set(record.id.trim(), facts.url);
  }
  $("preview").replaceChildren(sanitize(renderPreview(state.form.description, images)));
}

function place(entry) {
  const candidates = [];
  for (const start of [entry.field, entry.path]) {
    let path = start;
    while (path) {
      candidates.push(path);
      const cut = Math.max(path.lastIndexOf("."), path.lastIndexOf("["));
      path = cut > 0 ? path.slice(0, cut) : "";
    }
  }
  for (const path of candidates) {
    const link = /^links\.(.+)$/.exec(path);
    if (link) {
      const number = state.form.extraLinks.findIndex((item) => item.key.trim() === link[1]);
      if (number >= 0) return $("extra-links").querySelector(`[data-link="${number}"]`);
    }
    const dependency = /^dependencies\[(\d+)\]$/.exec(path);
    if (dependency) {
      const number = dependencyRows()[Number(dependency[1])];
      if (number !== undefined) return $("dependencies").querySelector(`[data-dependency="${number}"]`);
    }
    const target = $(`msg-${path}`);
    if (target) return target;
  }
  return null;
}

function dependencyRows() {
  const rows = [];
  state.form.dependencies.forEach((entry, number) => {
    if (entry.kept !== undefined || entry.id.trim()) rows.push(number);
  });
  return rows;
}

function extraMessages() {
  const found = [];
  const records = [];
  if (state.form.icon) records.push(["images.icon", state.form.icon]);
  state.form.descriptionImages.forEach((record, number) => records.push([`images.description[${number}]`, record]));
  for (const [where, record] of records) {
    const facts = measured.get(record);
    for (const problem of facts ? facts.problems : []) found.push({ level: ERROR, path: where, text: problem });
  }
  if (archiveNames) {
    for (const problem of inspectArchive(archiveNames, current.document).problems) {
      found.push({ level: ERROR, path: "archive", text: problem });
    }
  }
  return found;
}

function renderMessages() {
  for (const container of document.querySelectorAll(".messages")) {
    const checked = container.id ? !MANUAL.has(container.id) : container.dataset.link !== undefined || container.dataset.dependency !== undefined;
    if (checked) container.replaceChildren();
  }
  for (const input of document.querySelectorAll("[aria-invalid]")) input.removeAttribute("aria-invalid");
  for (const entry of current.messages) {
    const target = entry.path === "archive" ? null : place(entry);
    if (!target) continue;
    const input = entry.path === "the document" && SECTION_INPUTS[entry.field] ? $(SECTION_INPUTS[entry.field]) : invalidInput(entry, target);
    if (entry.path === "the document" && input && !input.value && !touched.has(input)) continue;
    if (entry.path === "tags" && entry.level === NOTE && !tagsTouched) continue;
    target.append(line(entry.level, REQUIRED.test(entry.text) ? "Required." : entry.text));
    if (entry.level === ERROR && input) input.setAttribute("aria-invalid", "true");
  }
}

function invalidInput(entry, target) {
  const named = document.querySelector(`[data-field="${CSS.escape(entry.field || entry.path)}"]`);
  if (named) return named;
  if (target.id) {
    const described = [...document.querySelectorAll("[aria-describedby]")]
      .find((node) => node.getAttribute("aria-describedby").split(" ").includes(target.id));
    if (described) return described;
  }
  if (target.dataset.link !== undefined || target.dataset.dependency !== undefined) {
    return target.closest(".item").querySelector("input");
  }
  return null;
}

const SPDX_DETAIL = /SPDX license list|does not parse as an SPDX/;
const SPDX_SHAPE = /is not an SPDX license expression/;
const REQUIRED = /^'([^']+)' is a required property$/;
const MISSING_NAMES = {
  id: "Id", name: "Name", authors: "Authors", abstract: "Abstract", license: "License",
  links: "Forums thread", forums: "Forums thread", compatibility: "Oldest game version", game_min: "Oldest game version",
};

function renderSummary() {
  const errors = current.messages.filter((entry) => entry.level === ERROR);
  const notes = current.messages.filter((entry) => entry.level === NOTE);
  const summary = $("summary");
  const parts = [];
  const missing = errors.filter((entry) => REQUIRED.test(entry.text));
  const others = current.messages.filter((entry) => !missing.includes(entry));
  if (!errors.length && !notes.length) {
    parts.push(line(null, "The checks on this page find nothing to fix."));
  }
  if (missing.length) {
    const names = missing.map((entry) => MISSING_NAMES[REQUIRED.exec(entry.text)[1]] || REQUIRED.exec(entry.text)[1]);
    parts.push(line(ERROR, `Still missing: ${names.join(", ")}.`));
  }
  if (others.length) {
    parts.push(element("ul", {}, others.map((entry) => element("li", { className: entry.level },
      [element("span", { className: "label", text: entry.level === ERROR ? "Error" : "Note" }), ` ${entry.field || entry.path}: ${entry.text}`]))));
  }
  if (notes.length) parts.push(element("p", { className: "hint", text: "Notes do not block the pull request." }));
  if (snapshotState === "loading") {
    parts.push(line(null, "The index snapshot is still loading, so the id is not yet checked against the listed ids."));
  } else if (!index) {
    parts.push(line(NOTE, "The index snapshot did not load, so the id is not checked against the listed ids."));
  }
  summary.replaceChildren(...parts);
}

const SVG = "http://www.w3.org/2000/svg";

function icon(className, shapes) {
  const node = document.createElementNS(SVG, "svg");
  node.setAttribute("viewBox", "0 0 24 24");
  node.setAttribute("class", className);
  node.setAttribute("aria-hidden", "true");
  for (const [tag, attributes] of shapes) {
    const shape = document.createElementNS(SVG, tag);
    for (const [name, value] of Object.entries(attributes)) shape.setAttribute(name, value);
    node.append(shape);
  }
  return node;
}

const PUZZLE = [["path", { d: "M5 8h3.5a2 2 0 1 1 4 0H16v3.5a2 2 0 1 1 0 4V19H5v-3.5a2 2 0 1 0 0-4z" }]];
const STATUS_ICONS = {
  done: [["path", { d: "M7 12.5l3.5 3.5L17 9" }]],
  fix: [["path", { d: "M12 7.5v5.5" }], ["circle", { cx: "12", cy: "16.5", r: "0.5" }]],
  open: [],
  optional: [],
};

function renderCard() {
  const form = state.form;
  const names = new Map((checker ? checker.vocabulary : []).map((entry) => [entry.tag, entry.name || entry.tag]));
  const facts = form.icon ? measured.get(form.icon) : null;
  const picture = element("div", { className: "card-icon" }, [
    facts && facts.url ? element("img", { src: facts.url, alt: "" }) : icon("placeholder", PUZZLE),
  ]);
  const authors = form.authors.split(",").map((name) => name.trim()).filter(Boolean);
  const title = element("p", { className: "card-title" }, [
    element("span", { className: "card-name", text: form.name.trim() || form.id.trim() || "Your mod" }),
  ]);
  if (authors.length) title.append(" ", element("span", { className: "card-by", text: `by ${authors.join(", ")}` }));
  const body = element("div", { className: "card-body" }, [
    title,
    element("p", { className: "card-abstract", text: form.abstract.trim() || "The abstract shows here, in lists and search." }),
  ]);
  if (form.tags.length) {
    body.append(element("div", { className: "card-chips" }, form.tags.map((tag) => element("span", { className: "tag", text: names.get(tag) || tag }))));
  }
  $("card").replaceChildren(picture, body);
}

function renderSteps() {
  const errors = new Map();
  for (const entry of current.messages) {
    if (entry.level !== ERROR || entry.path === "archive") continue;
    const target = place(entry);
    const section = target && target.closest("section");
    if (section) errors.set(section, (errors.get(section) || 0) + 1);
  }
  let open = 0;
  const items = [];
  for (const section of $("form").querySelectorAll(":scope > section")) {
    if (section.hidden || section.dataset.nav === "off") continue;
    const heading = section.querySelector("h2");
    const number = heading.querySelector(".step").textContent;
    const title = [...heading.childNodes].filter((node) => node.nodeType === Node.TEXT_NODE).map((node) => node.textContent).join("").trim();
    const shown = section.querySelectorAll(".msg.error").length;
    const filled = [...section.querySelectorAll("input, select, textarea")].some((field) =>
      field.type === "checkbox" ? field.checked : field.type !== "file" && field.type !== "radio" && field.value.trim() && field.tagName !== "SELECT")
      || section.querySelector(".item, [aria-pressed=true]") !== null;
    const count = errors.get(section) || 0;
    const kind = count && shown ? "fix" : count ? "open" : filled ? "done" : "optional";
    if (kind === "fix" || kind === "open") open += 1;
    const detail = kind === "fix" ? `${count} to fix` : kind === "open" ? "To do" : kind === "done" ? "Done" : section.dataset.empty || "Optional";
    items.push(element("li", { className: `step-item ${kind}` }, [
      element("a", { href: `#${heading.id}` }, [
        element("span", { className: "step-mark" }, [icon("mark", STATUS_ICONS[kind])]),
        element("span", { className: "step-name", text: `${number}. ${title}` }),
        element("span", { className: "step-detail", text: detail }),
      ]),
    ]));
  }
  $("step-nav").replaceChildren(...items);
  $("check-count").textContent = open ? `${open} step(s) still need something.` : "Every step passes the checks of this page.";
}

function renderOutput() {
  $("output").value = current.text;
  $("output").rows = Math.max(6, current.text.split("\n").length + 1);
  $("output-label").textContent = listingPath(current.document.id || "<id>");
  const blocked = current.messages.some((entry) => entry.level === ERROR) || !current.document.id;
  const link = $("open-pr");
  link.setAttribute("aria-disabled", blocked ? "true" : "false");
  link.classList.toggle("disabled", blocked);
  link.textContent = state.mode === "edit" && state.base ? "Open the edit page on GitHub" : "Open pull request on GitHub";
  if (state.mode === "edit" && state.base) {
    link.href = editUrl(state.base.id);
  } else {
    link.href = newFileUrl(String(current.document.id || ""), current.text).url;
  }
}

function refresh() {
  if (!checker) return;
  const own = state.mode === "edit" && state.base ? state.base.id : null;
  current.document = documentFromForm(state.form, state.mode === "edit" ? state.base : null);
  current.text = writeDocument(current.document);
  current.messages = checker.check(current.document, { index, own, gameVersions: index ? index.gameVersions : null });
  current.messages.push(...extraMessages());
  const explained = new Set(current.messages.filter((entry) => SPDX_DETAIL.test(entry.text)).map((entry) => entry.path));
  current.messages = current.messages.filter((entry) => !(explained.has(entry.path) && SPDX_SHAPE.test(entry.text)));
  const count = Array.from(state.form.abstract.trim()).length;
  $("abstract-count").textContent = `${count} of ${ABSTRACT_LIMIT}.`;
  $("authority-field").hidden = !(state.form.github.trim() && state.form.spacedock.trim());
  renderMessages();
  renderSummary();
  renderCard();
  renderSteps();
  renderOutput();
  renderArchiveResult();
  renderDescriptionPreview();
  persist();
}

function renderAll() {
  renderMode();
  renderFields();
  renderLoaderOptions();
  renderLoaderBounds();
  renderTypeSteps();
  renderExtraLinks();
  renderPlatforms();
  renderDependencies();
  renderTags();
  renderImages();
  refresh();
}

async function fetchListing(id) {
  try {
    const response = await fetch(rawListingUrl(id), { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT) });
    if (response.status === 404) return { error: `There is no ${listingPath(id)} on main.` };
    if (!response.ok) return { error: `GitHub answered HTTP ${response.status}.` };
    return { text: await response.text() };
  } catch {
    return { error: "GitHub did not answer. Try again." };
  }
}

async function checkBase() {
  if (state.mode !== "edit" || !state.base) return;
  const { base, baseText } = state;
  const answer = await fetchListing(base.id);
  if (state.base !== base || answer.text === baseText) return;
  const reload = element("button", {
    type: "button",
    text: "Load it again",
    onclick: () => {
      $("load-id").value = base.id;
      loadListing();
    },
  });
  const text = answer.error
    ? `The page could not check whether ${listingPath(base.id)} changed on main since you loaded it. ${answer.error}`
    : `${listingPath(base.id)} changed on main since you loaded it, and pasting this file would undo that change. Load it again and redo your changes.`;
  $("msg-load").replaceChildren(line(NOTE, text), reload);
}

async function loadListing() {
  const typed = $("load-id").value.trim();
  if (!typed) {
    say("msg-load", ERROR, "Give the id of the listing.");
    return;
  }
  const holder = index && index.holders.get(typed.toLowerCase());
  const id = holder ? holder.id : typed;
  say("msg-load", null, `Loading ${listingPath(id)}.`);
  const answer = await fetchListing(id);
  if (answer.error) {
    say("msg-load", ERROR, answer.error);
    return;
  }
  const text = answer.text;
  let base;
  try {
    base = parseDocument(text);
  } catch (error) {
    say("msg-load", ERROR, `The listing is not valid TOML: ${error.message}`);
    return;
  }
  state = { mode: "edit", baseText: text, base, form: formFromDocument(base) };
  archiveNames = null;
  archiveTicket = null;
  $("archive").value = "";
  say("msg-load", null, `Loaded ${listingPath(id)}.`);
  renderAll();
}

async function prefill() {
  const repository = state.form.github.trim();
  const url = repositoryApiUrl(repository);
  if (!url) {
    say("msg-prefill", ERROR, "Give the repository as owner/repository first.");
    return;
  }
  say("msg-prefill", null, "Asking GitHub.");
  let response;
  let answer;
  try {
    response = await fetch(url, { headers: { Accept: "application/vnd.github+json" }, cache: "no-store", signal: AbortSignal.timeout(TIMEOUT) });
    if (response.ok) answer = await response.json();
  } catch {
    say("msg-prefill", ERROR, "GitHub did not answer. Try again, or fill the fields by hand.");
    return;
  }
  if (response.status === 404) {
    say("msg-prefill", ERROR, `GitHub has no public repository ${repository}.`);
    return;
  }
  if (!response.ok) {
    say("msg-prefill", ERROR, `GitHub answered HTTP ${response.status}, often its limit for visitors. Try again later, or fill the fields by hand.`);
    return;
  }
  const facts = prefillFromRepository(answer);
  const filled = [];
  const fill = (label, path, value) => {
    if (value && !readPath(path).trim()) {
      writePath(path, value);
      filled.push(label);
    }
  };
  fill("name", ["name"], facts.name);
  fill("abstract", ["abstract"], facts.abstract);
  fill("license", ["license"], facts.license);
  fill("repository", ["links", "repository"], facts.repository);
  fill("bug tracker", ["links", "bugtracker"], facts.bugtracker);
  renderFields();
  const notes = [filled.length ? `Filled ${filled.join(", ")}. Check each value.` : "Nothing to fill, the fields already have values."];
  if (facts.fork) notes.push("The repository is a fork, so the first ownership proof in step 13 does not apply.");
  say("msg-prefill", null, notes.join(" "));
  $("organization-note").hidden = !facts.organization;
  $("organization-note").textContent = facts.organization
    ? `${facts.owner} is an organization. Add the topic ksa-index-<your-github-username>, in lowercase, to ${repository}, or ask an owner of ${facts.owner} to add it.`
    : "";
  refresh();
}

async function readArchive() {
  const file = $("archive").files && $("archive").files[0];
  const ticket = {};
  archiveTicket = ticket;
  archiveNames = null;
  if (!file) {
    say("archive-result");
    refresh();
    return;
  }
  say("archive-result", null, "Reading the archive.");
  refresh();
  let names;
  try {
    names = await zipNames(file);
  } catch (error) {
    if (archiveTicket === ticket) {
      say("archive-result", ERROR, error instanceof StampError ? error.message : `the archive cannot be read, ${error.message}`);
    }
    return;
  }
  if (archiveTicket !== ticket) return;
  archiveNames = names;
  refresh();
}

function renderArchiveResult() {
  if (!archiveNames) return;
  const result = inspectArchive(archiveNames, current.document);
  const lines = [];
  if (result.root !== null) {
    const where = result.root ? `'${result.root}'` : "the archive root";
    const matches = current.document.type === "mod" && result.root === current.document.id;
    lines.push(line(null, `The install root is ${where}${result.derived ? ", derived from the archive" : ""}${matches ? ", and it matches the id" : ""}.`));
  }
  for (const launch of result.launches) lines.push(line(null, `${launch} is in the archive.`));
  for (const problem of result.problems) lines.push(line(ERROR, problem));
  $("archive-result").replaceChildren(...lines);
}

async function copyOutput(target) {
  try {
    await navigator.clipboard.writeText(current.text);
    say(target, null, "Copied.");
    return true;
  } catch {
    $("output").focus();
    $("output").select();
    say(target, NOTE, "The browser did not allow copying. The file is selected, copy it by hand.");
    return false;
  }
}

function saveOutput() {
  const blob = new Blob([current.text], { type: "application/toml" });
  const url = URL.createObjectURL(blob);
  const anchor = element("a", { href: url, download: `${current.document.id || "listing"}.toml` });
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function openPullRequest(event) {
  if ($("open-pr").getAttribute("aria-disabled") === "true") {
    event.preventDefault();
    say("msg-pr", ERROR, current.document.id ? "Fix the errors first. You can still copy or save the file." : "Give the id first.");
    return;
  }
  const editing = state.mode === "edit" && state.base;
  const filled = !editing && newFileUrl(String(current.document.id), current.text).filled;
  const copied = await copyOutput("msg-pr");
  if (editing) {
    say("msg-pr", null, `${copied ? "The file is copied." : ""} In the GitHub editor, select all the text and paste the file over it.`);
  } else if (!filled) {
    say("msg-pr", null, `${copied ? "The file is copied." : ""} It is too long to fill in by the address, so paste it into the GitHub editor.`);
  } else {
    say("msg-pr", null, `${copied ? "The file is also copied, " : ""}in case GitHub does not fill it in.`);
  }
}

async function loadText(url) {
  const response = await fetch(url, { cache: "no-cache", signal: AbortSignal.timeout(TIMEOUT) });
  if (!response.ok) throw new Error(`${url} answered HTTP ${response.status}`);
  return response.text();
}

async function start() {
  bindStatic();
  restore();
  status("Loading the rules of the index.");
  try {
    const [schemaText, tagsText] = await Promise.all([loadText("rules/authored.schema.json"), loadText("rules/tags.toml")]);
    checker = createChecker({ schema: JSON.parse(schemaText), tagsText });
  } catch (error) {
    status(`The rules did not load, so the page cannot check anything. Reload the page. (${error.message})`);
    return;
  }
  status("");
  renderAll();
  checkBase();
  loadSnapshot();
}

async function loadSnapshot() {
  try {
    const response = await fetch(SNAPSHOT_URL, { cache: "no-cache", signal: AbortSignal.timeout(TIMEOUT) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    index = indexFacts(await response.json(), checker.threadPattern);
    snapshotState = "ready";
  } catch {
    index = null;
    snapshotState = "failed";
    status("The index snapshot did not load. The page still checks the file, but not the id against the listed ids.");
    refresh();
    return;
  }
  $("listed-ids").replaceChildren(...[...index.holders.values()].map((holder) => element("option", { value: holder.id })));
  $("game-versions").replaceChildren(...gameVersionChoices(index.gameVersions).map((version) => element("option", { value: version })));
  const newest = index.gameVersions[index.gameVersions.length - 1];
  if (newest) $("game-min").placeholder = newest;
  $("mod-ids").replaceChildren(...index.mods.map((id) => element("option", { value: id })));
  renderLoaderOptions();
  refresh();
}

start();
