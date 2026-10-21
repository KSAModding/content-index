import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { indexFacts, readTypeFile, withTypeFiles, SNAPSHOT_URL, TYPE_FILES } from "../js/snapshot.js";
import { typeChoices } from "../js/model.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
const app = fs.readFileSync(new URL("../js/app.js", import.meta.url), "utf8");

function markupIds() {
  return [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
}

function tokens(attribute) {
  return [...html.matchAll(new RegExp(`${attribute}="([^"]+)"`, "g"))].flatMap((match) => match[1].split(" "));
}

test("the markup names every element once", () => {
  const seen = new Set();
  for (const id of markupIds()) {
    assert.ok(!seen.has(id), `${id} is used twice`);
    seen.add(id);
  }
});

test("every element the page looks up is in the markup", () => {
  const known = new Set(markupIds());
  for (const [, id] of app.matchAll(/\$\("([^"]+)"\)/g)) {
    assert.ok(known.has(id), `js/app.js looks up ${id}, which the markup has not`);
  }
});

test("every label, hint and message container belongs to a field of the markup", () => {
  const known = new Set(markupIds());
  for (const attribute of ["for", "aria-describedby", "aria-labelledby"]) {
    for (const id of tokens(attribute)) {
      assert.ok(known.has(id), `${attribute} names ${id}, which the markup has not`);
    }
  }
});

test("the type is chosen before the releases and the id", () => {
  const type = html.indexOf('id="type"');
  assert.ok(type > 0 && type < html.indexOf('id="releases-section"') && type < html.indexOf('id="id"'));
});

test("a text that a pack shows names what is listed through the word the type sets", () => {
  for (const id of ["hint-forums", "hint-link-spacedock", "hint-game-min", "hint-game-max"]) {
    const hint = new RegExp(`<p id="${id}"[^>]*>([\\s\\S]*?)</p>`).exec(html)[1];
    assert.match(hint, /<span class="noun">mod<\/span>/, id);
    assert.doesNotMatch(hint.replace(/<span class="noun">mod<\/span>/g, ""), /\b(your|the) mod\b/, id);
  }
  assert.match(html, /<label for="license">License of your <span class="noun">mod<\/span><\/label>/);
  const render = /function renderTypeSections\(\) \{([\s\S]*?)\n\}/.exec(app)[1];
  assert.match(render, /querySelectorAll\("\.noun"\)\) word\.textContent = nounOf\(state\.form\.type\)/);
  assert.match(render, /querySelectorAll\("\.not-pack"\)\) part\.hidden = shown\.pack/);
});

test("the type select offers what the deployed schema accepts, so lifting the gate needs no page change", () => {
  const schema = JSON.parse(read("../../schemas/authored.schema.json"));
  const ungated = structuredClone(schema);
  delete ungated.properties.type.not;
  const gated = new Set(schema.properties.type.not ? schema.properties.type.not.enum : []);
  for (const type of ["vehicle", "save"]) {
    assert.equal(typeChoices(schema).includes(type), !gated.has(type), type);
    assert.ok(typeChoices(ungated).includes(type), type);
  }
  assert.match(app, /checker = createChecker\(\{ schema, tagsText, hostsText \}\);\n    types = typeChoices\(schema\);/);
  assert.match(body("function renderMode()"), /renderTypeOptions\(\);/);
  assert.match(body("function renderTypeOptions()"), /\$\("type"\)\.replaceChildren\(\.\.\.offered\.map/);
});

test("a vehicle or a save shows its own texts in place of the mod ones", () => {
  const render = body("function renderTypeSections()");
  assert.match(render, /querySelectorAll\("\.share-only"\)\) part\.hidden = !shown\.share/);
  assert.match(render, /querySelectorAll\("\.not-share"\)\) part\.hidden = shown\.share/);
  for (const id of ["hint-forums", "hint-game-min", "hint-id"]) {
    const hint = new RegExp(`<p id="${id}"[^>]*>([\\s\\S]*?)</p>`).exec(html)[1];
    assert.match(hint, /<span class="not-share">/, id);
    assert.match(hint, /<span class="share-only" hidden>/, id);
  }
  assert.match(html, /Optional for a vehicle or a save, because the forum may have no place for them\./);
  assert.match(html, /the watcher takes it from <code>version<\/code> in the <code>meta\.toml<\/code> in the zip/);
  assert.match(html, /The page does not read the part ids in <code>vehicle\.xml<\/code> or <code>universe\.xml<\/code>/);
});

test("the game_max hint says that clients block above it", () => {
  const hint = /<p id="hint-game-max"[^>]*>([\s\S]*?)<\/p>/.exec(html)[1];
  assert.match(hint, /Above this version, clients block the <span class="noun">mod<\/span>/);
  assert.doesNotMatch(hint, /warning/);
});

function body(start) {
  const from = app.indexOf(start);
  assert.ok(from >= 0, `js/app.js has no ${start}`);
  return app.slice(from, app.indexOf("\n}\n", from));
}

test("the since field shows next to a release host and tells what the watcher stamps", () => {
  const input = html.match(/<input id="since"[^>]*>/);
  assert.ok(input && /aria-describedby="[^"]*\bmsg-releases\.since\b/.test(input[0]), "the since input does not name msg-releases.since");
  assert.match(app, /\n  since: \["since"\],\n/, "the since input is not bound to state.form.since");
  assert.match(body("function refresh()"), /\$\("since-field"\)\.hidden = !\(state\.form\.github\.trim\(\) \|\| state\.form\.spacedock\.trim\(\)\);/);
  const hint = /<p id="hint-since"[^>]*>([\s\S]*?)<\/p>/.exec(html)[1];
  assert.match(hint, /stamps every older release from that version on, with the facts this listing states today/);
  assert.match(hint, /amendment/);
});

test("the tag_prefix field shows next to a GitHub repository and tells what it selects", () => {
  const input = html.match(/<input id="tag-prefix"[^>]*>/);
  assert.ok(input && /aria-describedby="[^"]*\bmsg-releases\.tag_prefix\b/.test(input[0]), "the tag-prefix input does not name msg-releases.tag_prefix");
  assert.match(app, /\n  "tag-prefix": \["tagPrefix"\],\n/, "the tag-prefix input is not bound to state.form.tagPrefix");
  assert.match(body("function refresh()"), /\$\("tag-prefix-field"\)\.hidden = !state\.form\.github\.trim\(\);/);
  assert.ok(html.indexOf('id="tag-prefix-field"') < html.indexOf('id="since-field"'), "the tag_prefix field is not next to since");
  const hint = /<p id="hint-tag-prefix"[^>]*>([\s\S]*?)<\/p>/.exec(html)[1];
  assert.match(hint, /takes only the releases whose tag starts with it/);
  assert.match(hint, /reads the version from the rest of the tag/);
});

test("a hidden field does not mark its section as done", () => {
  assert.match(body("function renderSections()"), /const filled = \[\.\.\.section\.querySelectorAll\("input, select, textarea"\)\]\.some\(\(field\) =>\s+!field\.closest\("\[hidden\]"\) && /);
});

test("a refused tag shows at the tag input and does not outlive its form", () => {
  const input = html.match(/<input id="tag-input"[^>]*>/);
  assert.ok(input && /aria-describedby="[^"]*\bmsg-tags\b/.test(input[0]), "the tag input does not name msg-tags");
  const clear = body("function clearTagEntry()");
  assert.match(clear, /tagError = null;/);
  assert.match(clear, /\$\("tag-input"\)\.value = "";/);
  for (const start of ['$("reset").addEventListener', "function useBase("]) {
    assert.match(body(start), /clearTagEntry\(\);/, `${start} keeps the refused tag of the earlier form`);
  }
});

test("the member rules run on every refresh, and the missing dependencies are one button away", () => {
  assert.match(body("function refresh()"), /\.\.\.memberMessages\(current\.document, index\),/);
  assert.match(body("function refresh()"), /renderMemberFix\(\);/);
  const fix = body("function renderMemberFix()");
  assert.match(fix, /\$\("add-missing"\)\.hidden = !pins\.length;/);
  assert.match(fix, /\$\("msg-members-fix"\)\.replaceChildren\(\.\.\.notes\.map\(\(text\) => line\(NOTE, text\)\)\);/);
  assert.match(body("function addMissing()"), /state\.form\.members\.push\(\.\.\.pins\.map/);
  assert.match(app, /\$\("add-missing"\)\.addEventListener\("click", addMissing\);/);
  assert.match(app, /const MANUAL = new Set\(\[[^\]]*"msg-members-fix"/);
  assert.match(html, /<button type="button" id="add-missing"[^>]*hidden>Add the missing dependencies<\/button>/);
});

test("a member row knows its pack section, and a message on vehicles[n] or saves[n] finds its row", () => {
  assert.match(app, /const PIN_PATH = \/\^\(mods\|vehicles\|saves\)\\\[\(\\d\+\)\\\]\$\/;/);
  assert.match(body("function renderMembers()"), /entry\.section = memberSection\(index, value\);/);
  assert.match(body("function place("), /const number = memberRows\(member\[1\]\)\[Number\(member\[2\]\)\];/);
  assert.match(body("function movePin("), /PIN_PATH\.exec\(path\)/);
  assert.match(body("function memberRows("), /\(state\.form\.members\[number\]\.section \|\| "mods"\) === section/);
  assert.match(body("function addMissing()"), /section: "mods"/);
});

test("Pin <newer> shows only for a newer release that the other pins accept", () => {
  assert.match(body("function renderMessages()"), /if \(entry\.newer && entry\.fits\) target\.append\(element\("button", \{ type: "button", text: `Pin \$\{entry\.newer\}`/);
});

test("the dependency help has the order of the Borea card", () => {
  const section = /<section[^>]*id="dependencies-section"[^>]*>([\s\S]*?)<\/section>/.exec(html)[1];
  const order = ["declared-text", "declared-list", "declared-pending", "msg-declared", "dependencies", "dependency-search", "add-listed-dependency",
    "dependency-matches", "dependency-no-match", "loader-set", "add-dependency"];
  const places = order.map((id) => section.indexOf(`id="${id}"`));
  assert.ok(places.every((place) => place >= 0), `the section has not all of ${order.join(", ")}`);
  assert.deepEqual([...places].sort((a, b) => a - b), places);
  const row = body("function dependencyRow(");
  assert.match(row, /\[id, kind, min, needsNewest, max\]/);
  assert.match(row, /versions,\n\s+kindLine,\n\s+messages,/);
});

test("the archive of a vehicle or a save is checked with the files the page read from it", () => {
  assert.equal(app.match(/inspectArchive\(archiveFile\.names, current\.document, archiveFile\.files\)/g).length, 2);
  const render = body("function renderArchiveResult()");
  assert.match(render, /if \(result\.folder\) lines\.push\(line\(null, `It installs as the folder '\$\{result\.folder\}', the name in its meta\.toml\.`\)\);/);
  assert.match(render, /for \(const note of result\.notes\) lines\.push\(line\(NOTE, note\)\);/);
  const hint = /<p id="hint-archive"[^>]*>([\s\S]*?)<\/p>/.exec(html)[1];
  assert.match(hint, /<span class="share-only" hidden>The page reads the file names, the <code>meta\.toml<\/code> and the <code>vehicle\.xml<\/code> or <code>universe\.xml<\/code> in it/);
});

test("a new or a loaded form forgets the selected zip and what it declared", () => {
  for (const start of ['$("reset").addEventListener', "function useBase("]) {
    assert.match(body(start), /forgetArchive\(\);/, `${start} keeps the archive of the earlier form`);
  }
  assert.match(body("function renderDeclared("), /\$\("declared-pending"\)\.hidden = !help\.pending;/);
  const render = body("function refresh()");
  assert.match(render, /renderDeclared\(\);/);
  assert.match(render, /renderDependencyMatches\(\);/);
  assert.match(render, /dependencyNotes\(current\.document, index, checker\.validId\)/);
});

const checker = createChecker({ schema: JSON.parse(read("../../schemas/authored.schema.json")), tagsText: read("../../tags.toml") });
const main = JSON.parse(read("fixtures/snapshot.json"));
const vehicleFile = JSON.parse(read("fixtures/snapshot-vehicles.json"));
const saveFile = JSON.parse(read("fixtures/snapshot-saves.json"));
const shared = indexFacts(withTypeFiles(main, { vehicles: vehicleFile.vehicles, saves: saveFile.saves }), checker.threadPattern);

function listing(changes = {}) {
  return {
    spec_version: 1, id: "NewMod", type: "mod", name: "New Mod", authors: ["Maxi"], abstract: "Adds a thing.", license: "MIT",
    links: { forums: "https://forums.ahwoo.com/threads/new-mod.2000/" }, compatibility: { game_min: "2026.10.19.5638" }, ...changes,
  };
}

const lines = (found, level) => found.filter((entry) => entry.level === level).map((entry) => `${entry.path}: ${entry.text}`);

test("an id that a vehicle, a save or a vehicle tombstone holds collides, in any case", () => {
  const holders = { examplerover: "vehicles/ExampleRover.toml", MOONBASE: "saves/MoonBase.toml", retiredrover: "vehicles/RetiredRover.toml" };
  for (const [id, where] of Object.entries(holders)) {
    assert.ok(lines(checker.check(listing({ id }), { index: shared }), ERROR)
      .includes(`id: the id '${id}' is already held by ${where}, and ids compare case-insensitively`), id);
  }
  assert.deepEqual(shared.holders.get("retiredrover"), { id: "RetiredRover", type: "vehicle", where: "vehicles/RetiredRover.toml" });
  assert.equal(shared.listed.get("retiredrover").state, "delisted");
  assert.equal(shared.listed.get("moonbase").type, "save");
});

test("the forums thread of a vehicle or a save counts as taken", () => {
  for (const [thread, where] of [["example-rover.1000", "vehicles/ExampleRover.toml"], ["moon-base.1001", "saves/MoonBase.toml"]]) {
    const notes = lines(checker.check(listing({ links: { forums: `https://forums.ahwoo.com/threads/${thread}/` } }), { index: shared }), NOTE);
    assert.ok(notes.some((text) => text.startsWith("links.forums:") && text.includes(where)), notes.join("\n"));
  }
});

test("a vehicle or a save is no mod for the dependency search", () => {
  assert.ok(!shared.mods.includes("ExampleRover"));
  assert.ok(!shared.searchable.some((entry) => entry.id === "ExampleRover" || entry.id === "MoonBase"));
});

test("a snapshot without vehicles and saves gives the same facts as before", () => {
  const plain = indexFacts(main, checker.threadPattern);
  assert.deepEqual(indexFacts(withTypeFiles(main, { vehicles: [], saves: [] }), checker.threadPattern), plain);
  assert.deepEqual(indexFacts({ ...main, vehicles: "x", saves: null }, checker.threadPattern), plain);
});

test("a vehicle in the main document stays a holder when its type file is not there", () => {
  const facts = indexFacts(withTypeFiles({ ...main, vehicles: vehicleFile.vehicles }, { vehicles: [], saves: [] }), checker.threadPattern);
  assert.equal(facts.holders.get("examplerover").where, "vehicles/ExampleRover.toml");
  assert.equal(facts.listed.get("examplerover").type, "vehicle");
});

test("a type file that is not there is empty, and any other failure is no answer", async () => {
  assert.deepEqual(await readTypeFile(new Response("", { status: 404 }), "vehicles"), []);
  assert.deepEqual(await readTypeFile(new Response(JSON.stringify({ snapshot_version: 1 })), "vehicles"), []);
  assert.deepEqual(await readTypeFile(new Response(JSON.stringify(saveFile)), "saves"), saveFile.saves);
  await assert.rejects(readTypeFile(new Response("", { status: 500 }), "vehicles"));
});

test("the type files sit next to the main document and are named in one place only", () => {
  const folder = SNAPSHOT_URL.slice(0, SNAPSHOT_URL.lastIndexOf("/") + 1);
  assert.deepEqual(Object.keys(TYPE_FILES), ["vehicles", "saves"]);
  for (const url of Object.values(TYPE_FILES)) assert.equal(url.slice(0, url.lastIndexOf("/") + 1), folder);
  const scripts = fs.readdirSync(new URL("../js/", import.meta.url)).filter((name) => name.endsWith(".js") && name !== "snapshot.js");
  for (const name of scripts) {
    assert.doesNotMatch(read(`../js/${name}`), /snapshot-(vehicles|saves)\.json/, name);
  }
  const load = body("async function loadSnapshot()");
  assert.match(load, /Object\.keys\(TYPE_FILES\)/);
  assert.match(load, /indexFacts\(withTypeFiles\(/);
});
