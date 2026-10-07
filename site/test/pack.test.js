import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { indexFacts } from "../js/snapshot.js";
import { parseDocument, writeDocument } from "../js/toml.js";
import { emptyForm, formFromDocument, documentFromForm, sectionsOf, nounOf, releaseTime } from "../js/model.js";
import {
  memberChoices, versionChoices, defaultVersion, pinNotes, gameMinNotes, packOf, ownIds, raiseVersion, nextPackForm, freeVersion, newerNotes, nextVersionNotes, forumLines,
  memberMessages, missingDependencies,
} from "../js/pack.js";
import { pullRequestLink, copyAndOpen, documentPath, rawPackUrl, URL_LIMIT, PASTE_NEW } from "../js/github.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const checker = createChecker({ schema: JSON.parse(read("../../schemas/authored.schema.json")), tagsText: read("../../tags.toml") });
const PACKS = new URL("../../packs/", import.meta.url);

const PACK_ID = "beiks-flight-planning-essentials-pack";
const packText = (version) => read(`../../packs/${PACK_ID}/${version}.toml`);

const snapshot = {
  listings: [
    {
      id: "DeltaVMap",
      authored: {
        type: "mod",
        name: "Delta-V Map",
        authors: ["Maxi"],
        license: "MIT",
        links: { forums: "https://forums.ahwoo.com/threads/deltavmap.978/" },
      },
      releases: [
        {
          version: "1.3.0",
          release_status: "stable",
          yanked: true,
          game_min: "2026.9.25.5500",
          game_min_revision: 5500,
          download: { url: "https://example.com/DeltaVMap-1.3.0.zip", unavailable_since: "2026-09-26T08:00:00Z" },
        },
        { version: "1.3.0-beta.1", release_status: "testing", game_min: "2026.9.22.5482", game_min_revision: 5482 },
        {
          version: "1.2.8",
          release_status: "stable",
          game_min: "2026.9.22.5482",
          game_min_revision: 5482,
          download: { url: "https://example.com/DeltaVMap-1.2.8.zip", unavailable_since: "2026-09-23T10:24:00Z" },
        },
        { version: "1.2.7", release_status: "stable", game_min: "2026.9.22.5482", game_min_revision: 5482 },
        {
          version: "1.2.6",
          release_status: "stable",
          game_min: "2026.9.10.5438",
          game_min_revision: 5438,
          download: { url: "https://example.com/DeltaVMap-1.2.6.zip" },
        },
      ],
    },
    {
      id: "AdvancedFlightComputer",
      authored: { type: "mod", name: "Advanced Flight Computer" },
      releases: [
        { version: "0.8.2-nightly.20260925", release_status: "dev" },
        { version: "0.8.1", release_status: "testing" },
        { version: "0.8.0", release_status: "stable" },
        { version: "0.7.5", release_status: "testing", yanked: true },
      ],
    },
    {
      id: "Compendium",
      authored: { type: "mod", name: "Compendium" },
      releases: [{ version: "0.9.13", release_status: "stable", game_min: "2026.9", game_min_revision: 5402 }],
    },
    { id: "Unreleased", authored: { type: "mod" }, releases: [] },
    {
      id: "Unscience",
      authored: { type: "mod", name: "Unscience", authors: ["meow-sci"], license: "MIT" },
      releases: [{ version: "1.66.0", release_status: "stable", download: { url: "https://example.com/unscience-1.66.0.zip", unavailable_since: "2026-09-23T10:24:00Z" } }],
    },
    {
      id: "StarMap",
      authored: { type: "mod-loader", name: "StarMap", authors: ["StarMap Team"], license: "MIT" },
      releases: [{ version: "0.4.7", release_status: "stable", download: { url: "https://example.com/StarMap-0.4.7.zip" } }],
    },
    { id: "GoneMod", index_status: { state: "delisted" } },
    { id: "HiddenMod", authored: { type: "mod" }, index_status: { state: "delisted" }, releases: [{ version: "1.0.0", release_status: "stable" }] },
  ],
  packs: [
    { id: PACK_ID, versions: [{ authored: parseDocument(packText("1.0.1")) }, { authored: parseDocument(packText("1.0.0")) }] },
    { id: "OtherPack", versions: [{ authored: { version: "1.0.0" } }] },
  ],
  game_versions: { versions: ["2026.9.10.5438", "2026.9.22.5482"] },
};
const index = indexFacts(snapshot, checker.threadPattern);

function packForm() {
  const form = emptyForm();
  Object.assign(form, {
    id: "ExamplePack",
    type: "modpack",
    name: "Example Pack",
    authors: "Example Author",
    abstract: "Two mods for mission planning.",
    license: "MIT",
    tags: ["user-interface"],
    gameMin: "2026.9.22.5482",
    version: "1.0.0",
    releasedAt: "2026-09-25T12:00:00Z",
    changelog: "The first version.",
    members: [{ id: "DeltaVMap", version: "1.2.7" }, { id: "", version: "" }, { id: "Compendium", version: "0.9.13" }],
  });
  form.links.forums = "https://forums.ahwoo.com/threads/example-pack.1/";
  return form;
}

test("a pack form writes a valid document at packs/<id>/<version>.toml, the one tools/test_vectors.py checks", () => {
  const document = documentFromForm(packForm(), null);
  assert.equal(documentPath(document), "packs/ExamplePack/1.0.0.toml");
  assert.equal(writeDocument(document), read(`fixtures/${documentPath(document)}`));
  assert.deepEqual(checker.check(document, { index }).filter((entry) => entry.level === ERROR), []);
  assert.deepEqual(pinNotes(document, index), []);
  assert.deepEqual(memberMessages(document, index), []);
  assert.deepEqual(gameMinNotes(document, index), []);
});

const needing = indexFacts({
  listings: [
    {
      id: "ShaderExtensions",
      authored: { type: "mod" },
      releases: [
        { version: "1.0.5", release_status: "stable", dependencies: [{ id: "KittenExtensions", kind: "required", min: "0.5.0", source: "authored" }] },
        { version: "1.0.2", release_status: "stable", dependencies: [] },
      ],
    },
    {
      id: "Telescope",
      authored: { type: "mod" },
      releases: [{ version: "2.0.0", release_status: "stable", dependencies: [{ kind: "required", any_of: [{ id: "LensA" }, { id: "LensB" }] }] }],
    },
    {
      id: "Alpha",
      authored: { type: "mod" },
      releases: [{
        version: "1.0.0",
        release_status: "stable",
        dependencies: [
          { id: "Beta", kind: "required", min: "1.5", max: "2.0.0", source: "authored" },
          { id: "Gamma", kind: "optional", source: "authored" },
          { kind: "required", any_of: [{ id: "Beta" }, { id: "Gamma" }] },
        ],
      }],
    },
    {
      id: "Beta",
      authored: { type: "mod" },
      releases: [
        { version: "3.0.0", release_status: "stable" },
        { version: "2.0.1", release_status: "stable" },
        { version: "2.0.0-rc.1", release_status: "testing" },
        { version: "1.9.0", release_status: "stable", yanked: true },
        { version: "1.8.0", release_status: "stable", download: { unavailable_since: "2026-09-23T10:24:00Z" } },
        { version: "1.7.0", release_status: "stable" },
        { version: "1.0.0", release_status: "stable" },
      ],
    },
    { id: "Gamma", authored: { type: "mod" }, releases: [{ version: "1.0.0", release_status: "stable" }] },
    {
      id: "Delta",
      authored: { type: "mod" },
      releases: [{
        version: "1.0.0",
        release_status: "stable",
        dependencies: [
          { id: "Beta", kind: "required", min: "2.5.0", source: "authored" },
          { id: "KittenExtensions", kind: "required", source: "derived" },
          { kind: "required", any_of: [{ id: "LensA" }, { id: "Gamma" }] },
        ],
      }],
    },
  ],
  packs: [],
}, checker.threadPattern);

test("the picker marks a release whose required dependency is not a listed mod, and does not choose it", () => {
  assert.deepEqual(versionChoices(needing, "ShaderExtensions"), [
    ["1.0.5", "1.0.5 (stable, cannot be pinned, because it needs 'KittenExtensions')"],
    ["1.0.2", "1.0.2 (stable)"],
  ]);
  assert.deepEqual(versionChoices(needing, "Telescope"), [["2.0.0", "2.0.0 (stable, cannot be pinned, because it needs one of 'LensA', 'LensB')"]]);
  assert.deepEqual(versionChoices(needing, "Alpha"), [["1.0.0", "1.0.0 (stable)"]]);
  assert.equal(defaultVersion(needing, "ShaderExtensions"), "1.0.2");
  assert.equal(defaultVersion(needing, "Telescope"), "2.0.0");
});

test("Add the missing dependencies pins the newest stable release inside the bounds, and the set then passes", () => {
  const document = { type: "modpack", mods: [{ id: "Alpha", version: "1.0.0" }] };
  assert.deepEqual(levels(memberMessages(document, needing), ERROR), [
    "mods[0]: 'Alpha' 1.0.0 requires 'Beta' 1.5 to 2.0.0, and the pack does not pin it",
    "mods[0]: 'Alpha' 1.0.0 requires one of 'Beta', 'Gamma', and the pack pins none of them",
  ]);
  const missing = missingDependencies(document, needing);
  assert.deepEqual(missing, { pins: [{ id: "Beta", version: "1.7.0" }], notes: [] });
  assert.deepEqual(memberMessages({ ...document, mods: [...document.mods, ...missing.pins] }, needing), []);
  assert.deepEqual(missingDependencies({ ...document, mods: [...document.mods, { id: "beta" }] }, needing), { pins: [], notes: [] });
});

test("what Add the missing dependencies cannot pin stays a note for the author", () => {
  const document = { type: "modpack", mods: [{ id: "Delta", version: "1.0.0" }, { id: "Alpha", version: "1.0.0" }, { id: "Telescope", version: "2.0.0" }] };
  assert.deepEqual(missingDependencies(document, needing), {
    pins: [],
    notes: [
      "'Delta' 1.0.0 requires 'Beta' 2.5.0 or newer, and no stable release of it is inside the bounds of every member that requires it",
      "'Delta' 1.0.0 requires 'KittenExtensions', and no listed mod meets this, so no pack can pin this release",
      "'Delta' 1.0.0 requires one of 'LensA', 'Gamma', so pin the one you want",
      "'Alpha' 1.0.0 requires 'Beta' 1.5 to 2.0.0, and no stable release of it is inside the bounds of every member that requires it",
      "'Alpha' 1.0.0 requires one of 'Beta', 'Gamma', so pin the one you want",
      "'Telescope' 2.0.0 requires one of 'LensA', 'LensB', and no listed mod meets this, so no pack can pin this release",
    ],
  });
  assert.deepEqual(missingDependencies({ ...document, type: "mod" }, needing), { pins: [], notes: [] });
  assert.deepEqual(missingDependencies(document, null), { pins: [], notes: [] });
});

const release = (version, dependencies = []) => ({ version, release_status: "stable", dependencies });
const moving = indexFacts({
  listings: [
    { id: "Core", authored: { type: "mod" }, releases: [release("3.0.0"), release("2.0.0"), release("1.0.0")] },
    { id: "Addon", authored: { type: "mod" }, releases: [release("1.0.0", [{ id: "Core", kind: "required", min: "1.0.0", max: "2.0.0" }])] },
    { id: "Rival", authored: { type: "mod" }, releases: [release("1.0.0", [{ id: "Core", kind: "conflict", min: "3.0.0" }])] },
    { id: "Helper", authored: { type: "mod" }, releases: [release("1.0.0")] },
    { id: "Gauge", authored: { type: "mod" }, releases: [release("1.1.0", [{ id: "Helper", kind: "required" }]), release("1.0.0")] },
    { id: "Meter", authored: { type: "mod" }, releases: [release("1.1.0", [{ id: "Core", kind: "conflict" }]), release("1.0.0")] },
    { id: "Scope", authored: { type: "mod" }, releases: [release("1.1.0", [{ id: "KittenExtensions", kind: "required" }]), release("1.0.0")] },
    {
      id: "Lens",
      authored: { type: "mod" },
      releases: [release("1.0.0", [
        { id: "KittenExtensions", kind: "required" },
        { kind: "required", any_of: [{ id: "ShaderExtensions" }, { id: "KittenExtensionsContinued" }] },
      ])],
    },
  ],
  packs: [],
}, checker.threadPattern);

test("the mark names each need once, with quoted ids and one of", () => {
  assert.deepEqual(versionChoices(moving, "Lens"), [
    ["1.0.0", "1.0.0 (stable, cannot be pinned, because it needs 'KittenExtensions' and one of 'ShaderExtensions', 'KittenExtensionsContinued')"],
  ]);
});

test("Pin <newer> shows only when the other pins accept the newer release, and the note stays", () => {
  const moves = (...mods) => newerNotes({ type: "modpack", mods: mods.map(([id, version]) => ({ id, version })) }, moving)
    .map((entry) => [entry.path, entry.newer, entry.fits]);
  assert.deepEqual(moves(["Core", "1.0.0"]), [["mods[0]", "3.0.0", true]]);
  assert.deepEqual(moves(["Core", "1.0.0"], ["Core", "2.0.0"]), [["mods[0]", "3.0.0", true], ["mods[1]", "3.0.0", true]]);
  // Outside the bounds that another pinned release sets.
  assert.deepEqual(moves(["Core", "1.0.0"], ["Addon", "1.0.0"]), [["mods[0]", "3.0.0", false]]);
  // Another pinned release conflicts with it.
  assert.deepEqual(moves(["Core", "1.0.0"], ["Rival", "1.0.0"]), [["mods[0]", "3.0.0", false]]);
  // The pins do not meet its required dependencies.
  assert.deepEqual(moves(["Gauge", "1.0.0"]), [["mods[0]", "1.1.0", false]]);
  assert.deepEqual(moves(["Gauge", "1.0.0"], ["Helper", "1.0.0"]), [["mods[0]", "1.1.0", true]]);
  // It conflicts with another pin.
  assert.deepEqual(moves(["Meter", "1.0.0"], ["Core", "3.0.0"]), [["mods[0]", "1.1.0", false]]);
  assert.deepEqual(moves(["Meter", "1.0.0"]), [["mods[0]", "1.1.0", true]]);
  // No pack can pin it.
  assert.deepEqual(moves(["Scope", "1.0.0"]), [["mods[0]", "1.1.0", false]]);
});

test("a pack loaded into the form and written back is unchanged", () => {
  for (const folder of fs.readdirSync(PACKS, { withFileTypes: true }).filter((entry) => entry.isDirectory())) {
    for (const name of fs.readdirSync(new URL(`${folder.name}/`, PACKS)).filter((file) => file.endsWith(".toml"))) {
      const base = parseDocument(fs.readFileSync(new URL(`${folder.name}/${name}`, PACKS), "utf8"));
      assert.deepEqual(documentFromForm(formFromDocument(base), base), base, name);
    }
  }
});

test("the picker offers listed mods at releases that are not yanked and still download, newest first", () => {
  assert.deepEqual(memberChoices(index), [
    ["AdvancedFlightComputer", "Advanced Flight Computer (AdvancedFlightComputer)"],
    ["Compendium", "Compendium"],
    ["DeltaVMap", "Delta-V Map (DeltaVMap)"],
  ]);
  assert.deepEqual(versionChoices(index, "DeltaVMap"), [
    ["1.3.0-beta.1", "1.3.0-beta.1 (testing)"],
    ["1.2.7", "1.2.7 (stable)"],
    ["1.2.6", "1.2.6 (stable)"],
  ]);
  assert.deepEqual(versionChoices(index, "StarMap"), []);
  assert.deepEqual(versionChoices(index, "HiddenMod"), []);
  assert.equal(defaultVersion(index, "DeltaVMap"), "1.2.7");
});

test("a loaded pin that the checks refuse stays in the file and gets their error", () => {
  const base = documentFromForm(packForm(), null);
  base.mods = [
    { id: "DeltaVMap", version: "1.3.0" },
    { id: "NotListed", version: "2.0.0" },
    { id: "StarMap", version: "0.4.7" },
    { id: "GoneMod", version: "1.0.0" },
    { id: "HiddenMod", version: "1.0.0" },
    { id: "Compendium", version: "0.9.12" },
  ];
  const form = formFromDocument(base);
  const document = documentFromForm(form, null);
  assert.deepEqual(document.mods, base.mods);
  assert.deepEqual(memberMessages(document, index).map((entry) => [entry.level, entry.path, entry.text]), [
    [ERROR, "mods[0]", "'DeltaVMap' 1.3.0 is yanked"],
    [ERROR, "mods[1]", "'NotListed' is not a listed mod, and a pack pins only listed mods"],
    [ERROR, "mods[2]", "'StarMap' is listed as a mod-loader, and a pack pins only mods"],
    [ERROR, "mods[3]", "'GoneMod' is delisted, and a pack pins only listed mods"],
    [ERROR, "mods[4]", "'HiddenMod' is delisted, and a pack pins only listed mods"],
    [ERROR, "mods[5]", "'Compendium' has no stamped release 0.9.12"],
  ]);
  assert.deepEqual(pinNotes(document, index), []);
  assert.deepEqual(memberMessages(document, null), []);
  assert.deepEqual(memberMessages({ ...document, type: "mod" }, index), []);
  assert.deepEqual(memberChoices(index, "NotListed").at(-1), ["NotListed", "NotListed (not offered by the index)"]);
  assert.deepEqual(versionChoices(index, "NotListed", "2.0.0"), [["2.0.0", "2.0.0 (not offered by the index)"]]);
  assert.deepEqual(versionChoices(index, "DeltaVMap", "1.3.0").at(-1), ["1.3.0", "1.3.0 (not offered by the index)"]);
});

test("a release whose download is gone is left out, and a loaded pin of it is kept with a note that names it and the date", () => {
  const document = { ...documentFromForm(packForm(), null), mods: [{ id: "DeltaVMap", version: "1.2.8" }, { id: "Unscience", version: "1.66.0" }] };
  assert.deepEqual(pinNotes(document, index).map((entry) => [entry.level, entry.path, entry.text]), [
    [NOTE, "mods[0]", "'DeltaVMap' 1.2.8 is no longer downloadable since 2026-09-23, so the page does not offer it; the pin stays as it is"],
    [NOTE, "mods[1]", "'Unscience' 1.66.0 is no longer downloadable since 2026-09-23, so the page does not offer it; the pin stays as it is"],
  ]);
  assert.deepEqual(checker.check(document, { index }).filter((entry) => entry.level === ERROR), []);
  assert.deepEqual(memberMessages(document, index), []);
  assert.deepEqual(pinNotes({ type: "modpack", mods: [{ id: "DeltaVMap", version: "1.3.0" }] }, index), []);
  assert.deepEqual(versionChoices(index, "DeltaVMap", "1.2.8").at(-1), ["1.2.8", "1.2.8 (no longer downloadable)"]);
  assert.deepEqual(versionChoices(index, "Unscience"), []);
  assert.deepEqual(memberChoices(index, "Unscience").at(-1), ["Unscience", "Unscience (not offered by the index)"]);
  assert.deepEqual(newerNotes({ type: "modpack", mods: [{ id: "DeltaVMap", version: "1.2.6" }] }, index).map((entry) => entry.newer), ["1.2.7"]);
  assert.deepEqual(forumLines(document, index), [
    "Delta-V Map 1.2.8 - Author: Maxi - License: MIT - Download: https://example.com/DeltaVMap-1.2.8.zip - Thread: https://forums.ahwoo.com/threads/deltavmap.978/",
    "Unscience 1.66.0 - Author: meow-sci - License: MIT - Download: https://example.com/unscience-1.66.0.zip - Thread: ",
  ]);
  const gonePin = { ...document, mods: [{ id: "DeltaVMap", version: "1.2.8" }, { id: "Compendium", version: "0.9.13" }] };
  assert.deepEqual(gameMinNotes({ ...gonePin, compatibility: {} }, index).map((entry) => entry.text), [
    "the pinned releases need at least '2026.9.22.5482', the highest game_min among them, so that is the proposed oldest game version",
  ]);
  assert.equal(gameMinNotes({ ...gonePin, compatibility: { game_min: "2026.9" } }, index).length, 1);
});

test("the same release without the mark is offered, and its pin has no note", () => {
  const unmarked = JSON.parse(JSON.stringify(snapshot, (key, value) => (key === "unavailable_since" ? undefined : value)));
  const restored = indexFacts(unmarked, checker.threadPattern);
  assert.deepEqual(versionChoices(restored, "DeltaVMap").slice(0, 2), [["1.3.0-beta.1", "1.3.0-beta.1 (testing)"], ["1.2.8", "1.2.8 (stable)"]]);
  assert.equal(defaultVersion(restored, "DeltaVMap"), "1.2.8");
  assert.deepEqual(versionChoices(restored, "Unscience"), [["1.66.0", "1.66.0 (stable)"]]);
  assert.deepEqual(pinNotes({ type: "modpack", mods: [{ id: "DeltaVMap", version: "1.2.8" }, { id: "Unscience", version: "1.66.0" }] }, restored), []);
  assert.deepEqual(newerNotes({ type: "modpack", mods: [{ id: "DeltaVMap", version: "1.2.6" }] }, restored).map((entry) => entry.newer), ["1.2.8"]);
});

test("the page proposes the highest game_min of the pinned releases as a note", () => {
  const document = documentFromForm(packForm(), null);
  const proposal = "compatibility.game_min: the pinned releases need at least '2026.9.22.5482', the highest game_min among them, so that is the proposed oldest game version";
  const notes = (gameMin) => gameMinNotes({ ...document, compatibility: gameMin === undefined ? {} : { game_min: gameMin } }, index)
    .map((entry) => `${entry.path}: ${entry.text}`);
  assert.deepEqual(notes(undefined), [proposal]);
  assert.deepEqual(notes("2026.9.10.5438"), [proposal]);
  assert.deepEqual(notes("2026.9"), [proposal]);
  assert.deepEqual(notes("2026.9.22.5481"), [proposal]);
  assert.deepEqual(notes("2026.9.22.5482"), []);
  assert.deepEqual(notes("2026.9.0.5482"), []);
  assert.deepEqual(notes("2026.10"), []);
  assert.deepEqual(gameMinNotes({ ...document, mods: [{ id: "Compendium", version: "0.9.13" }], compatibility: { game_min: "2026.9" } }, index), []);
  assert.deepEqual(gameMinNotes({ ...document, type: "mod", compatibility: {} }, index), []);
});

test("the new-file link names the pack path, and a pack over the limit is copied instead", async () => {
  const short = documentFromForm(packForm(), null);
  short.version = "1.0.0+build.1";
  const path = documentPath(short, encodeURIComponent);
  assert.equal(path, "packs/ExamplePack/1.0.0%2Bbuild.1.toml");
  const plain = `https://github.com/KSAModding/content-index/new/main?filename=${path}`;
  assert.deepEqual(pullRequestLink(path, "x"), { url: `${plain}&value=x`, step: "" });

  const text = fs.readFileSync(new URL("beiks-flight-planning-essentials-pack/1.0.1.toml", PACKS), "utf8");
  const real = documentPath(parseDocument(text), encodeURIComponent);
  const link = pullRequestLink(real, text);
  assert.ok(encodeURIComponent(text).length > URL_LIMIT);
  assert.deepEqual(link, {
    url: "https://github.com/KSAModding/content-index/new/main?filename=packs/beiks-flight-planning-essentials-pack/1.0.1.toml",
    step: PASTE_NEW,
  });
  const copied = [];
  await copyAndOpen(link.url, text, { writeText: async (value) => copied.push(value) }, () => ({}));
  assert.deepEqual(copied, [text]);
});

test("switching the type back to mod keeps the mod fields the author typed", () => {
  const form = emptyForm();
  Object.assign(form, { id: "MyMod", github: "me/MyMod", loaderId: "StarMap", loaderMin: "0.4.7", gameMin: "2026.9.22.5482" });
  form.dependencies.push({ id: "Compendium", kind: "optional", min: "", max: "" });
  const mod = documentFromForm(form, null);
  form.type = "modpack";
  form.version = "1.0.0";
  form.members.push({ id: "DeltaVMap", version: "1.2.7" });
  const pack = documentFromForm(form, null);
  for (const key of ["releases", "loader", "dependencies", "install", "provides"]) assert.equal(pack[key], undefined, key);
  assert.deepEqual(pack.mods, [{ id: "DeltaVMap", version: "1.2.7" }]);
  form.type = "mod";
  assert.deepEqual(documentFromForm(form, null), mod);
});

test("a pack shows the pack sections and hides releases, loader, dependencies and install", () => {
  assert.deepEqual(sectionsOf("modpack"), { releases: false, loader: false, launch: false, dependencies: false, pack: true, members: true });
  assert.deepEqual(sectionsOf("mod"), { releases: true, loader: true, launch: false, dependencies: true, pack: false, members: false });
  assert.deepEqual(sectionsOf("mod-loader"), { releases: true, loader: false, launch: true, dependencies: true, pack: false, members: false });
});

test("the page calls what is listed a mod, a mod loader or a pack", () => {
  assert.equal(nounOf("mod"), "mod");
  assert.equal(nounOf("mod-loader"), "mod loader");
  assert.equal(nounOf("modpack"), "pack");
});

test("the release time is UTC to the second", () => {
  assert.equal(releaseTime(new Date(Date.UTC(2026, 8, 25, 12, 3, 4, 567))), "2026-09-25T12:03:04Z");
});

const NOW = new Date(Date.UTC(2026, 8, 25, 18, 0, 0));
const withoutVersionKeys = ({ version, released_at: releasedAt, changelog, ...rest }) => rest;
const levels = (found, level) => found.filter((entry) => entry.level === level).map((entry) => `${entry.path}: ${entry.text}`);

test("loading the listed pack proposes the next version with the same pins and a new release time", () => {
  const base = parseDocument(packText("1.0.1"));
  const pack = packOf(index, PACK_ID.toUpperCase());
  assert.deepEqual(pack.versions.map((entry) => entry.version), ["1.0.1", "1.0.0"]);
  const document = documentFromForm(nextPackForm(base, pack, NOW), base);
  assert.equal(document.version, "1.0.2");
  assert.equal(document.released_at, "2026-09-25T18:00:00Z");
  assert.notEqual(document.released_at, base.released_at);
  assert.deepEqual(document.mods, [
    { id: "DeltaVMap", version: "1.2.6" },
    { id: "AdvancedFlightComputer", version: "0.8.0" },
    { id: "Compendium", version: "0.9.13" },
  ]);
  assert.deepEqual(withoutVersionKeys(document), withoutVersionKeys(base));
  assert.equal(documentPath(document), `packs/${PACK_ID}/1.0.2.toml`);
  assert.deepEqual(levels(nextVersionNotes(document, index, PACK_ID), ERROR), []);
});

test("the next version starts with an empty changelog, because the old one describes the old version", () => {
  const base = { ...parseDocument(packText("1.0.1")), changelog: "Adds Compendium." };
  const form = nextPackForm(base, packOf(index, PACK_ID), NOW);
  assert.equal(form.changelog, "");
  assert.equal(documentFromForm(form, base).changelog, undefined);
});

test("the pack's own id gives no id error, and another pack's id does", () => {
  const base = parseDocument(packText("1.0.1"));
  const document = documentFromForm(nextPackForm(base, packOf(index, PACK_ID), NOW), base);
  const { own, pack } = ownIds(base);
  assert.deepEqual([own, pack], [PACK_ID, PACK_ID]);
  assert.deepEqual(levels(checker.check(document, { index, own }), ERROR), []);
  assert.deepEqual(levels(nextVersionNotes(document, index, pack), ERROR), []);
  assert.ok(levels(checker.check(document, { index }), ERROR).some((text) => text.startsWith("id: ") && text.includes("is already held by")));
  assert.deepEqual(ownIds({ id: "DeltaVMap", type: "mod" }), { own: "DeltaVMap", pack: null });
  assert.deepEqual(ownIds(null), { own: null, pack: null });
});

test("a later pack version opens the new file, never the edit page of the loaded one", () => {
  const base = parseDocument(packText("1.0.1"));
  const document = documentFromForm(nextPackForm(base, packOf(index, PACK_ID), NOW), base);
  const text = writeDocument(document);
  const link = pullRequestLink(documentPath(document, encodeURIComponent), text, base);
  assert.equal(link.url, `https://github.com/KSAModding/content-index/new/main?filename=packs/${PACK_ID}/1.0.2.toml`);
  assert.equal(link.step, PASTE_NEW);
});

test("a pack whose highest version is retracted proposes a version above it and shows the reason", () => {
  const reason = "Retracted at the request of the author of DeltaVMap.";
  const newest = { ...parseDocument(packText("1.0.1")), version: "1.1.0", released_at: "2026-09-24T10:00:00Z" };
  const retracted = indexFacts({
    ...snapshot,
    packs: [{
      id: PACK_ID,
      versions: [
        { authored: parseDocument(packText("1.0.0")) },
        { authored: newest, index_status: { state: "retracted", reason } },
        { authored: parseDocument(packText("1.0.1")) },
      ],
    }],
  }, checker.threadPattern);
  const pack = packOf(retracted, PACK_ID);
  assert.deepEqual(pack.versions.map((entry) => entry.version), ["1.1.0", "1.0.1", "1.0.0"]);
  const document = documentFromForm(nextPackForm(newest, pack, NOW), newest);
  assert.equal(document.version, "1.1.1");
  assert.deepEqual(levels(nextVersionNotes(document, retracted, PACK_ID), NOTE), [
    `version: version '1.1.0' of this pack is retracted: ${reason}`,
    `mods[0]: the retraction of version '1.1.0' names 'DeltaVMap': ${reason}`,
  ]);
  assert.deepEqual(levels(nextVersionNotes(document, retracted, PACK_ID), ERROR), []);
  const behind = { ...document, version: "1.0.2", released_at: "2026-09-24T10:00:00Z" };
  assert.deepEqual(levels(nextVersionNotes(behind, retracted, PACK_ID), ERROR), [
    "version: '1.0.2' is not higher than '1.1.0', the highest version of this pack, retracted ones included",
    "released_at: '2026-09-24T10:00:00Z' is not later than '2026-09-24T10:00:00Z', the release time of version '1.1.0'",
  ]);
  assert.deepEqual(nextVersionNotes(document, retracted, null), []);
});

test("a proposed path that exists on raw GitHub is raised again", async () => {
  const onMain = new Set(["1.0.2", "1.0.3"]);
  const asked = [];
  const taken = async (version) => {
    asked.push(rawPackUrl(PACK_ID, version));
    return onMain.has(version);
  };
  assert.equal(await freeVersion("1.0.2", taken), "1.0.4");
  assert.deepEqual(asked, ["1.0.2", "1.0.3", "1.0.4"].map((version) =>
    `https://raw.githubusercontent.com/KSAModding/content-index/main/packs/${PACK_ID}/${version}.toml`));
  assert.equal(await freeVersion("1.0.5", taken), "1.0.5");
  assert.equal(await freeVersion("1.0.2", async () => true, 3), null);
  await assert.rejects(freeVersion("1.0.2", async () => { throw new Error("GitHub did not answer."); }));
});

test("the version is raised as npm raises a patch", () => {
  assert.equal(raiseVersion("1.0.1"), "1.0.2");
  assert.equal(raiseVersion("2.3.9+build.7"), "2.3.10");
  assert.equal(raiseVersion("1.1.0-rc.1"), "1.1.0");
  assert.equal(raiseVersion("not a version"), null);
});

test("a member with a newer release at least as stable is marked, and a newer testing release does not mark a stable pin", () => {
  const document = {
    type: "modpack",
    mods: [
      { id: "DeltaVMap", version: "1.2.6" },
      { id: "DeltaVMap", version: "1.2.7" },
      { id: "AdvancedFlightComputer", version: "0.8.0" },
      { id: "AdvancedFlightComputer", version: "0.8.1" },
      { id: "DeltaVMap", version: "1.1.0" },
      { id: "Compendium", version: "0.9.13" },
      { id: "NotListed", version: "1.0.0" },
      { id: "AdvancedFlightComputer", version: "0.7.5" },
    ],
  };
  assert.deepEqual(newerNotes(document, index).map((entry) => [entry.path, entry.newer, entry.level, entry.text]), [
    ["mods[0]", "1.2.7", NOTE, "'DeltaVMap' has a newer stable release '1.2.7'; the pin stays until you move it"],
    ["mods[4]", "1.2.7", NOTE, "'DeltaVMap' has a newer stable release '1.2.7'; the pin stays until you move it"],
    ["mods[7]", "0.8.1", NOTE, "'AdvancedFlightComputer' has a newer testing release '0.8.1'; the pin stays until you move it"],
  ]);
  assert.deepEqual(newerNotes({ ...document, type: "mod" }, index), []);
});

test("the forum list has one line per member in the words Borea writes", () => {
  const document = {
    type: "modpack",
    mods: [
      { id: "DeltaVMap", version: "1.2.6" },
      { id: "NotListed", version: "1.0.0" },
      { id: "deltavmap", version: "1.3.0" },
      { id: "StarMap", version: "0.4.7" },
      { id: "HiddenMod", version: "1.0.0" },
      { id: "DeltaVMap", version: "9.9.9" },
    ],
  };
  const thread = "Thread: https://forums.ahwoo.com/threads/deltavmap.978/";
  assert.deepEqual(forumLines(document, index), [
    `Delta-V Map 1.2.6 - Author: Maxi - License: MIT - Download: https://example.com/DeltaVMap-1.2.6.zip - ${thread}`,
    "NotListed 1.0.0 - Not listed in the content index",
    `Delta-V Map 1.3.0 - Author: Maxi - License: MIT - Download: https://example.com/DeltaVMap-1.3.0.zip - ${thread}`,
    "StarMap 0.4.7 - Author: StarMap Team - License: MIT - Download: https://example.com/StarMap-0.4.7.zip - Thread: ",
    "HiddenMod 1.0.0 - Not listed in the content index",
    "DeltaVMap 9.9.9 - Not listed in the content index",
  ]);
  assert.deepEqual(forumLines({ type: "modpack", mods: [{ id: "DeltaVMap", version: "1.2.6" }, { id: "Compendium" }] }, index).at(-1), null);
});
