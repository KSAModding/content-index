import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { deflateRawSync } from "node:zlib";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { indexFacts } from "../js/snapshot.js";
import { writeDocument } from "../js/toml.js";
import { emptyForm, formFromDocument, documentFromForm } from "../js/model.js";
import {
  TEXTS, KIND_TEXTS, kindText, kindChoices, listedOf, isListedLoader, boundChoices, newestBound, derivedOf, canAddBounds, dependencyCandidates,
  dependencyMatches, addDependency, dependencyNotes, modTomlDependencies, readModToml, readArchive, archiveDependencies,
  canNeedNewest, declaredFor,
} from "../js/dependencies.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const checker = createChecker({ schema: JSON.parse(read("../../schemas/authored.schema.json")), tagsText: read("../../tags.toml") });

// The snapshot the listing editor of Borea runs its dependency tests on, so both give the same answers for it.
const SNAPSHOT = JSON.parse(read("fixtures/snapshot.json"));
const BOM = String.fromCharCode(0xfeff);

function facts(edit = (snapshot) => snapshot) {
  return indexFacts(edit(structuredClone(SNAPSHOT)), checker.threadPattern);
}

// Yanks MeasureTools 1.1.10 and marks 1.1.9 as a dev build, as the Borea test does.
function yankAndMarkDev(snapshot) {
  const listing = snapshot.listings.find((entry) => entry.id === "MeasureTools");
  for (const release of listing.releases) {
    if (release.version === "1.1.10") release.yanked = true;
    if (release.version === "1.1.9") release.release_status = "dev";
  }
  return snapshot;
}

function newMod(id = "MyMod") {
  return { ...emptyForm(), id };
}

const MOD_TOML = 'name = "MyMod"\n\n[[StarMap.ModDependencies]]\nModId = "MeasureTools"\n\n[[StarMap.ModDependencies]]\nModId = "Extra"\nOptional = true\n';

test("a listed mod shows the derived dependencies of its newest release, and Add bounds adds an entry", () => {
  const index = facts();
  const derived = derivedOf(index, "AdvancedFlightComputer");
  assert.deepEqual(derived, { release: "0.7.5", dependencies: [{ id: "KittenExtensions", kind: "optional" }] });
  assert.equal(TEXTS.declared(`release ${derived.release}`),
    "The mod.toml of release 0.7.5 declares these dependencies. The index adds them to each release by itself, so add an entry only for bounds or a conflict.");
  assert.equal(TEXTS.optional("KittenExtensions"), "Optional in your mod.toml: KittenExtensions");
  assert.equal(TEXTS.required("StarMap"), "Required by your mod.toml: StarMap");

  const form = formFromDocument({ id: "AdvancedFlightComputer", type: "mod" });
  assert.equal(canAddBounds(form, "KittenExtensions"), true);
  assert.equal(addDependency(form, index, "KittenExtensions", "optional"), null);
  assert.deepEqual(form.dependencies, [{ id: "KittenExtensions", kind: "optional", min: "", max: "" }]);
  assert.equal(canAddBounds(form, "kittenextensions"), false);
  const document = documentFromForm(form, null);
  assert.match(writeDocument(document), /\[\[dependencies\]\]\nid = "KittenExtensions"\nkind = "optional"\n/);
  assert.deepEqual(dependencyNotes(document, index, checker.validId),
    [{ level: NOTE, path: "dependencies[0]", text: "KittenExtensions is not listed in the index, so players cannot install it." }]);
});

test("the derived dependencies are those of the newest release that is not yanked, without the authored ones", () => {
  const release = (version, dependencies, yanked = false) => ({ version, release_status: "stable", yanked, dependencies });
  const index = indexFacts({
    listings: [{
      id: "MyMod",
      authored: { type: "mod", name: "My Mod" },
      releases: [
        release("1.0.0", [{ id: "Old", kind: "required", source: "derived" }]),
        release("1.2.0", [{ id: "Bad", kind: "required", source: "derived" }], true),
        release("1.1.0", [
          { id: "Lib", kind: "required", source: "derived" },
          { id: "Extra", kind: "optional", source: "derived" },
          { id: "Bounded", kind: "required", min: "1.0.0", source: "authored" },
          { any_of: [{ id: "A" }, { id: "B" }], kind: "required", source: "authored" },
        ]),
      ],
    }],
  }, checker.threadPattern);

  assert.deepEqual(derivedOf(index, "mymod"), { release: "1.1.0", dependencies: [{ id: "Lib", kind: "required" }, { id: "Extra", kind: "optional" }] });
  assert.equal(derivedOf(index, "Other"), null);
});

test("the id search finds a listed mod by name, and an unlisted id gets the note", () => {
  const index = facts();
  const form = newMod();
  const [match, ...rest] = dependencyMatches(index, form, "flight computer");
  assert.equal(match.id, "AdvancedFlightComputer");
  assert.deepEqual(rest, []);
  assert.deepEqual(dependencyMatches(index, form, "laurens").map((listing) => listing.id), ["KSArmory"]);
  assert.deepEqual(dependencyMatches(index, form, "  "), []);

  addDependency(form, index, match.id, "required");
  assert.deepEqual(form.dependencies, [{ id: "AdvancedFlightComputer", kind: "required", min: "", max: "" }]);
  assert.equal(kindText(form.dependencies[0].kind), KIND_TEXTS.required);
  assert.deepEqual(dependencyMatches(index, form, "advanced"), []);
  assert.ok(dependencyCandidates(index, form).length > 0, "the search says that no listed mod matches");

  form.dependencies.push({ id: "NotListedMod", kind: "required", min: "", max: "" });
  const document = documentFromForm(form, null);
  assert.deepEqual(dependencyNotes(document, index, checker.validId),
    [{ level: NOTE, path: "dependencies[1]", text: "NotListedMod is not listed in the index, so players cannot install it." }]);
  const messages = checker.check(document, { index });
  assert.deepEqual(messages.filter((entry) => entry.level === ERROR && entry.path.startsWith("dependencies")), []);
});

test("the search leaves out the listing itself and every id an entry or the loader names", () => {
  const index = facts();
  const form = newMod("MeasureTools");
  assert.deepEqual(dependencyMatches(index, form, "maxi").map((listing) => listing.id), ["AdvancedFlightComputer"]);
  form.dependencies.push({ kept: { any_of: [{ id: "advancedflightcomputer" }, { id: "KSArmory" }], kind: "required" } });
  assert.deepEqual(dependencyMatches(index, form, "a"), [listedOf(index, "StarMap")]);
  form.loaderId = "StarMap";
  assert.deepEqual(dependencyMatches(index, form, "a"), []);
});

test("the search marks a loader, and picking it sets the loader of a mod", () => {
  const index = facts();
  const form = newMod();
  const [match] = dependencyMatches(index, form, "starmap");
  assert.equal(match.loader, true);
  assert.equal(isListedLoader(index, "starmap"), true);

  assert.equal(addDependency(form, index, match.id, "required"), "StarMap");
  assert.deepEqual(form.dependencies, []);
  assert.deepEqual([form.loaderId, form.loaderMin], ["StarMap", "0.4.6"]);
  assert.equal(TEXTS.loaderSet("StarMap"), "StarMap is a mod loader, so it is now the loader under Compatibility. Set its versions there.");
  assert.equal(canAddBounds(form, "StarMap"), false);
  assert.deepEqual(dependencyMatches(index, form, "starmap"), []);

  form.loaderMin = "0.4.0";
  addDependency(form, index, "starmap", "required");
  assert.equal(form.loaderMin, "0.4.0", "the loader keeps its oldest version");

  const loader = { ...newMod("MyLoader"), type: "mod-loader" };
  assert.deepEqual(dependencyMatches(index, loader, "starmap"), []);
});

test("the versions are the stamped releases newest first, without the yanked ones, and take free text", () => {
  const index = facts(yankAndMarkDev);
  assert.deepEqual(boundChoices(index, "measuretools"), [
    { version: "1.1.9", status: "dev" },
    { version: "1.1.8", status: "" },
    { version: "1.1.7", status: "" },
  ]);
  assert.equal(newestBound(index, "MeasureTools"), "1.1.8");
  assert.deepEqual(boundChoices(index, "NotListedMod"), []);
  assert.equal(newestBound(index, "NotListedMod"), null);

  const dev = indexFacts({ listings: [{ id: "Dev", authored: { type: "mod" }, releases: [{ version: "0.1.0-dev.1", release_status: "dev" }] }] }, checker.threadPattern);
  assert.equal(newestBound(dev, "Dev"), "0.1.0-dev.1");

  const form = newMod();
  form.dependencies.push({ id: "MeasureTools", kind: "required", min: "0.5", max: "" });
  const document = documentFromForm(form, null);
  assert.match(writeDocument(document), /\[\[dependencies\]\]\nid = "MeasureTools"\nkind = "required"\nmin = "0\.5"\n/);
  assert.deepEqual(checker.check(document, { index }).filter((entry) => entry.path.startsWith("dependencies")), []);
});

test("each mistake of an entry is named on it with the answer of check_schema.py", () => {
  const document = documentFromForm({
    ...newMod(),
    dependencies: [
      { id: "MeasureTools", kind: "required", min: "1.1", max: "1.0.9" },
      { id: "mymod", kind: "required", min: "", max: "" },
      { id: "measuretools", kind: "conflict", min: "", max: "" },
      { id: "AdvancedFlightComputer", kind: "needs", min: "", max: "" },
    ],
  }, null);
  const index = facts();
  const lines = [...checker.check(document, { index }), ...dependencyNotes(document, index, checker.validId)]
    .filter((entry) => entry.path.startsWith("dependencies"))
    .map((entry) => `${entry.path}: ${entry.text}`);
  assert.deepEqual(lines, [
    "dependencies[3].kind: 'needs' is not one of ['required', 'optional', 'recommends', 'suggests', 'conflict']",
    "dependencies[0]: max '1.0.9' is below min '1.1'",
    "dependencies[1]: a listing cannot depend on itself",
    "dependencies[2]: 'measuretools' already has a dependency entry",
    "dependencies[2]: 'measuretools' does not use the canonical id spelling 'MeasureTools'",
  ]);
  assert.equal(kindChoices("needs")[0], "needs");
  assert.equal(kindText("needs"), null);
  assert.equal(kindText("conflict"), KIND_TEXTS.conflict);
  assert.deepEqual(kindChoices("suggests"), ["required", "optional", "recommends", "suggests", "conflict"]);
});

// The rows of the validator test of Borea, with the lines check_schema.py prints for them.
const BOUND_ROWS = [
  ["1.1", "1.0.9", ["dependencies[0]: max '1.0.9' is below min '1.1'"]],
  ["0.5", "0.5.0", []],
  ["3000000000", "1.0", ["dependencies[0]: max '1.0' is below min '3000000000'"]],
  ["99999999999999999999.0.0", "1", ["dependencies[0]: max '1' is below min '99999999999999999999.0.0'"]],
  ["v2.0", "1.0", ["dependencies[0].min: 'v2.0' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1, with one to three numbers and no leading v"]],
  ["2.0", "v1.0", ["dependencies[0].max: 'v1.0' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1, with one to three numbers and no leading v"]],
  ["02.0", "1.0", [
    "dependencies[0].min: '02.0' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1, with one to three numbers and no leading v",
    "dependencies[0]: max '1.0' is below min '02.0'",
  ]],
  ["1.0.0-01", "0.9", [
    "dependencies[0].min: '1.0.0-01' is not a version such as 1.2.3, 0.5 or 2.0.0-rc.1, with one to three numbers and no leading v",
    "dependencies[0]: max '0.9' is below min '1.0.0-01'",
  ]],
  ["1.0.0-rc.1", "1.0.0-rc", ["dependencies[0]: max '1.0.0-rc' is below min '1.0.0-rc.1'"]],
  ["1.0.0-alpha", "1.0.0-1", ["dependencies[0]: max '1.0.0-1' is below min '1.0.0-alpha'"]],
  ["1.0", "1.0.0+build", []],
];

test("the bounds of an entry are compared as check_schema.py compares them", () => {
  for (const [min, max, answers] of BOUND_ROWS) {
    const document = documentFromForm({ ...newMod(), dependencies: [{ id: "MeasureTools", kind: "required", min, max }] }, null);
    const lines = checker.offline(document).filter((entry) => entry.path.startsWith("dependencies")).map((entry) => `${entry.path}: ${entry.text}`);
    assert.deepEqual(lines, answers, `${min} to ${max}`);
  }
});

test("the mod.toml dependencies are read as derived_dependencies of the stamper reads them", () => {
  const dependencies = (text) => modTomlDependencies(readModToml(new TextEncoder().encode(text), "MyMod/mod.toml"));
  assert.deepEqual(dependencies(MOD_TOML), [{ id: "MeasureTools", kind: "required" }, { id: "Extra", kind: "optional" }]);
  assert.deepEqual(dependencies(`${BOM}[[StarMap.ModDependencies]]\nModId = "  Lib "\nOptional = 0\n`), [{ id: "Lib", kind: "required" }]);
  assert.deepEqual(dependencies('[[StarMap.ModDependencies]]\nModId = "Lib"\nOptional = "no"\n'), [{ id: "Lib", kind: "optional" }]);
  assert.deepEqual(dependencies('name = "MyMod"\n'), []);
  assert.deepEqual(dependencies('StarMap = ""\n'), []);
  assert.deepEqual(dependencies("[StarMap]\nModDependencies = []\nBig = 9007199254740993\n"), []);
  const refused = [
    ['[StarMap.ModDependencies]\nModId = "A"\n', "StarMap.ModDependencies of the mod.toml is not a list of [[StarMap.ModDependencies]] blocks"],
    ['[StarMap]\nModDependencies = ["A"]\n', "a [[StarMap.ModDependencies]] block is not a table"],
    ['StarMap = "x"\n', "[StarMap] of the mod.toml is not a table"],
    ["[[StarMap.ModDependencies]]\nModId = 5\n", "a [[StarMap.ModDependencies]] block has a ModId that is not text"],
    ["[[StarMap.ModDependencies]]\nOptional = true\n", "a [[StarMap.ModDependencies]] block carries no ModId"],
    ['[[StarMap.ModDependencies]]\nModId = " "\n', "a [[StarMap.ModDependencies]] block carries no ModId"],
  ];
  for (const [text, message] of refused) assert.throws(() => dependencies(text), { message }, text);
  assert.throws(() => dependencies("name = "), { message: /^the archive's MyMod\/mod\.toml is not valid TOML, / });
  assert.throws(() => readModToml(new Uint8Array([0xff]), "MyMod/mod.toml"), { message: /^the archive's MyMod\/mod\.toml is not valid TOML, / });
});

// A zip of the files, every second one stored and the others deflated.
function zip(files) {
  const locals = [];
  const central = [];
  let offset = 0;
  files.forEach(([name, text], number) => {
    const encoded = Buffer.from(name, "utf8");
    const raw = Buffer.from(text, "utf8");
    const method = number % 2 ? 0 : 8;
    const body = method ? deflateRawSync(raw) : raw;
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x800, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(encoded.length, 26);
    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0);
    entry.writeUInt16LE(20, 4);
    entry.writeUInt16LE(20, 6);
    entry.writeUInt16LE(0x800, 8);
    entry.writeUInt16LE(method, 10);
    entry.writeUInt32LE(body.length, 20);
    entry.writeUInt32LE(raw.length, 24);
    entry.writeUInt16LE(encoded.length, 28);
    entry.writeUInt32LE(offset, 42);
    locals.push(local, encoded, body);
    central.push(entry, encoded);
    offset += local.length + encoded.length + body.length;
  });
  const directory = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return new Blob([...locals, directory, end]);
}

test("the mod.toml of the install root of a release zip gives the declared dependencies", async () => {
  const mod = { id: "MyMod", type: "mod" };
  const standard = await readArchive(zip([["MyMod/mod.toml", MOD_TOML], ["MyMod/MyMod.dll", "binary"]]));
  assert.deepEqual(standard.names, ["MyMod/mod.toml", "MyMod/MyMod.dll"]);
  assert.deepEqual(archiveDependencies(standard, mod), { dependencies: [{ id: "MeasureTools", kind: "required" }, { id: "Extra", kind: "optional" }] });

  const stored = await readArchive(zip([["MyMod/MyMod.dll", "binary"], ["MyMod/mod.toml", MOD_TOML]]));
  assert.equal(archiveDependencies(stored, mod).dependencies.length, 2);

  const authored = await readArchive(zip([["GameData/MyMod/mod.toml", MOD_TOML], ["Docs/readme.txt", "text"]]));
  assert.deepEqual(archiveDependencies(authored, mod), { missing: "root" });
  assert.equal(archiveDependencies(authored, { ...mod, install: { root: "GameData/./MyMod" } }).dependencies.length, 2);
  assert.deepEqual(archiveDependencies(authored, { ...mod, install: { root: "Docs" } }), { missing: "mod.toml" });
  assert.deepEqual(archiveDependencies(authored, { ...mod, install: { root: "Other" } }), { problem: "the authored install root 'Other' is not in the archive" });

  const atRoot = await readArchive(zip([["mod.toml", MOD_TOML], ["MyMod.dll", "binary"]]));
  assert.deepEqual(archiveDependencies(atRoot, mod), { missing: "root" });
  assert.equal(archiveDependencies(atRoot, { ...mod, install: { root: "." } }).dependencies.length, 2);

  const broken = await readArchive(zip([["MyMod/mod.toml", "[[StarMap.ModDependencies]]\nOptional = true\n"]]));
  assert.deepEqual(archiveDependencies(broken, mod), { problem: "a [[StarMap.ModDependencies]] block carries no ModId" });

  const large = await readArchive(zip([["MyMod/mod.toml", `# ${"x".repeat(1024 * 1024)}\n`]]));
  assert.deepEqual(archiveDependencies(large, mod), { problem: "the archive's MyMod/mod.toml is 1048579 bytes, above the 1048576 byte limit" });

  assert.equal(TEXTS.noRoot("MyMod.zip"),
    "The page cannot find the install root in MyMod.zip, so the index reads no mod.toml from it. The usual layout is one top-level folder that holds mod.toml and has the id as its name.");
});

test("a loader typed as the id of an entry gets the error of the checks", () => {
  const document = documentFromForm({ ...newMod(), dependencies: [{ id: "StarMap", kind: "required", min: "", max: "" }] }, null);
  const errors = checker.check(document, { index: facts() }).filter((entry) => entry.level === ERROR && entry.path.startsWith("dependencies"));
  assert.deepEqual(errors.map((entry) => entry.text), ["'StarMap' is listed as a mod-loader, and a dependency has to be a mod"]);
});

test("a zip with bytes in front of its first entry is read as the stamper reads it", async () => {
  const prefixed = await readArchive(new Blob([Buffer.alloc(600, 0x50), zip([["MyMod/mod.toml", MOD_TOML], ["MyMod/MyMod.dll", "binary"]])]));
  assert.deepEqual(archiveDependencies(prefixed, { id: "MyMod", type: "mod" }),
    { dependencies: [{ id: "MeasureTools", kind: "required" }, { id: "Extra", kind: "optional" }] });
});

test("a picked loader takes its newest stable release that a client still offers", () => {
  const index = facts((snapshot) => {
    const listing = snapshot.listings.find((entry) => entry.id === "StarMap");
    const newest = listing.releases[0];
    listing.releases.push({ ...structuredClone(newest), version: "0.4.5" });
    newest.download = { ...newest.download, unavailable_since: "2026-09-23T10:24:00Z" };
    return snapshot;
  });
  const form = newMod();
  assert.equal(addDependency(form, index, "StarMap", "required"), "StarMap");
  assert.deepEqual([form.loaderId, form.loaderMin], ["StarMap", "0.4.5"]);
  assert.deepEqual(boundChoices(index, "StarMap").map((choice) => choice.version), ["0.4.6", "0.4.5"], "a bound can still name a gone release");
});

test("Needs the newest shows for a listed mod with releases, and not for a conflict", () => {
  const index = facts();
  assert.equal(canNeedNewest(index, { id: "MeasureTools", kind: "required" }), true);
  assert.equal(canNeedNewest(index, { id: "measuretools", kind: "suggests" }), true);
  assert.equal(canNeedNewest(index, { id: "MeasureTools", kind: "conflict" }), false);
  assert.equal(canNeedNewest(index, { id: "NotListedMod", kind: "required" }), false);
});

// A read zip with the file name the declared box uses.
async function named(files, fileName) {
  return { ...await readArchive(zip(files)), fileName };
}

test("the declared box shows the zip, else the derived dependencies of the snapshot, with the line of the read", async () => {
  const index = facts();
  const mod = { id: "AdvancedFlightComputer", type: "mod" };
  const base = { id: "AdvancedFlightComputer" };
  const ask = (archive) => declaredFor({ document: mod, index, base, archive });
  const snapshot = { of: "release 0.7.5", dependencies: [{ id: "KittenExtensions", kind: "optional" }] };

  assert.deepEqual(ask(null), { shown: true, declared: snapshot, read: null, pending: false });
  const good = await named([["AdvancedFlightComputer/mod.toml", MOD_TOML]], "AFC.zip");
  assert.deepEqual(ask(good), {
    shown: true, declared: { of: "AFC.zip", dependencies: [{ id: "MeasureTools", kind: "required" }, { id: "Extra", kind: "optional" }] }, read: null, pending: false,
  });

  const noToml = await named([["AdvancedFlightComputer/AdvancedFlightComputer.dll", "binary"]], "NoToml.zip");
  assert.deepEqual(ask(noToml), { shown: true, declared: snapshot, read: [null, TEXTS.noModToml("NoToml.zip")], pending: false });
  const rootless = await named([["a.txt", "x"], ["b/c.txt", "y"], ["d/e.txt", "z"]], "Rootless.zip");
  assert.deepEqual(ask(rootless).read, [null, TEXTS.noRoot("Rootless.zip")]);
  const unreadable = await named([["AdvancedFlightComputer/mod.toml", "name = "]], "Bad.zip");
  const [level, text] = ask(unreadable).read;
  assert.equal(level, NOTE);
  assert.match(text, /^The page could not read Bad\.zip: the archive's AdvancedFlightComputer\/mod\.toml is not valid TOML, /);
  assert.deepEqual(ask(unreadable).declared, snapshot);

  for (const type of ["mod-loader", "mod-library", "modpack"]) {
    assert.deepEqual(declaredFor({ document: { ...mod, type }, index, base, archive: good }),
      { shown: false, declared: null, read: null, pending: false }, type);
  }
});

test("the declared box says when the dependencies show while it has none", async () => {
  const index = facts();
  const mod = { id: "MyMod", type: "mod" };
  assert.deepEqual(declaredFor({ document: mod, index, base: null, archive: null }), { shown: true, declared: null, read: null, pending: true });
  assert.equal(declaredFor({ document: mod, index: null, base: null, archive: null }).pending, true, "a new listing needs no snapshot for the hint");
  const unstamped = { id: "NotStampedMod" };
  assert.equal(declaredFor({ document: { ...mod, id: unstamped.id }, index, base: unstamped, archive: null }).pending, true);
  assert.deepEqual(declaredFor({ document: { id: "AdvancedFlightComputer", type: "mod" }, index: null, base: { id: "AdvancedFlightComputer" }, archive: null }),
    { shown: false, declared: null, read: null, pending: false }, "a loaded listing waits for the snapshot");

  const noToml = await named([["MyMod/MyMod.dll", "binary"]], "MyMod-1.0.zip");
  assert.deepEqual(declaredFor({ document: mod, index, base: null, archive: noToml }),
    { shown: true, declared: null, read: [null, TEXTS.noModToml("MyMod-1.0.zip")], pending: false });
  const good = await named([["MyMod/mod.toml", MOD_TOML]], "MyMod-1.0.zip");
  assert.equal(declaredFor({ document: mod, index, base: null, archive: good }).pending, false);
  assert.equal(declaredFor({ document: { ...mod, type: "mod-library" }, index, base: null, archive: null }).shown, false);
});
