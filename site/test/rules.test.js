import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, licenseErrors, semverCompare, releaseListRules, ERROR, NOTE } from "../js/rules.js";
import { indexFacts, newestStable, gameVersionChoices } from "../js/snapshot.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const checker = createChecker({ schema: JSON.parse(read("../../schemas/authored.schema.json")), tagsText: read("../../tags.toml") });

const snapshot = {
  listings: [
    {
      id: "StarMap",
      authored: { type: "mod-loader", links: { forums: "https://forums.ahwoo.com/threads/starmap-mod-loader.384/" } },
      releases: [
        { version: "0.5.0-beta.1", release_status: "testing" },
        { version: "0.4.8", release_status: "stable", yanked: true },
        { version: "0.4.7", release_status: "stable" },
      ],
    },
    { id: "OtherMod", authored: { type: "mod", links: { forums: "https://forums.ahwoo.com/forums/mod-releases/other.500/" } }, releases: [] },
    { id: "GoneMod", index_status: { state: "delisted" } },
  ],
  packs: [{ id: "BigPack", versions: [{ authored: { version: "1.0.0", links: { forums: "https://forums.ahwoo.com/threads/pack.600/" } } }] }],
  game_versions: { versions: ["2026.8.3.5117", "2026.9.7.5402", "2026.9.10.5438"] },
};
const index = indexFacts(snapshot, checker.threadPattern);

function mod(changes = {}) {
  return {
    spec_version: 1,
    id: "ExampleMod",
    type: "mod",
    name: "Example Mod",
    authors: ["Example Author"],
    abstract: "Adds an example.",
    license: "MIT",
    tags: ["gameplay"],
    links: { forums: "https://forums.ahwoo.com/threads/example.123/" },
    compatibility: { game_min: "2026.9.10.5438" },
    ...changes,
  };
}

const texts = (found, level) => found.filter((entry) => entry.level === level).map((entry) => `${entry.path}: ${entry.text}`);

test("a valid mod has no message", () => {
  assert.deepEqual(checker.check(mod(), { index }), []);
});

test("an id held by a listing or a pack collides, in any case", () => {
  for (const id of ["starmap", "BIGPACK", "gonemod"]) {
    const errors = texts(checker.check(mod({ id }), { index }), ERROR);
    assert.ok(errors.some((text) => text.includes("is already held by") && text.includes("ids compare case-insensitively")), errors.join("\n"));
  }
});

test("the own id is no collision when a listing changes", () => {
  assert.deepEqual(texts(checker.check(mod({ id: "OtherMod" }), { index, own: "OtherMod" }), ERROR), []);
});

test("a loader must be a mod-loader and a dependency a mod, in the listed spelling", () => {
  const found = texts(checker.check(mod({
    loader: { id: "OtherMod", min: "1.0.0" },
    dependencies: [{ id: "starmap", kind: "required" }],
  }), { index }), ERROR);
  assert.ok(found.includes("loader: 'OtherMod' is listed as a mod, and a loader has to be a mod-loader"), found.join("\n"));
  assert.ok(found.includes("dependencies[0]: 'starmap' does not use the canonical id spelling 'StarMap'"), found.join("\n"));
  assert.ok(found.includes("dependencies[0]: 'starmap' is listed as a mod-loader, and a dependency has to be a mod"), found.join("\n"));
});

test("a forums thread another listing names gives a note, by thread id", () => {
  const found = texts(checker.check(mod({ links: { forums: "https://forums.ahwoo.com/index.php?threads/other.500/" } }), { index }), NOTE);
  assert.deepEqual(found, [
    "links.forums: thread 500 is also the forums thread of listings/OtherMod.toml, so the thread cannot settle an id dispute between them",
  ]);
  const own = checker.check(mod({ id: "OtherMod", links: { forums: "https://forums.ahwoo.com/threads/other.500/" } }), { index, own: "OtherMod" });
  assert.deepEqual(texts(own, NOTE), []);
});

test("the newest stable release that is not yanked is the loader default", () => {
  assert.equal(newestStable(snapshot.listings[0].releases), "0.4.7");
  assert.deepEqual(index.loaders, [{ id: "StarMap", newest: "0.4.7" }]);
  assert.deepEqual(index.mods, ["OtherMod"]);
});

test("game version choices list the newest version first and then the months", () => {
  assert.deepEqual(gameVersionChoices(index.gameVersions), ["2026.9.10.5438", "2026.9.7.5402", "2026.8.3.5117", "2026.9", "2026.8"]);
});

test("a month with no build in the game release list is rejected like the stamper does", () => {
  const now = new Date(Date.UTC(2026, 8, 19));
  const versions = index.gameVersions;
  assert.deepEqual(releaseListRules(mod({ compatibility: { game_min: "2026.9" } }), versions, now), []);
  assert.deepEqual(releaseListRules(mod({ compatibility: { game_min: "2026.9", game_max: "2026.12" } }), versions, now), []);
  assert.deepEqual(
    releaseListRules(mod({ compatibility: { game_min: "2026.7" } }), versions, now).map((entry) => entry.text),
    ["game_min '2026.7' names a month with no build in the game release list"],
  );
});

test("SemVer precedence follows SemVer 2.0.0", () => {
  const ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"];
  for (let index = 1; index < ordered.length; index += 1) {
    assert.equal(semverCompare(ordered[index - 1], ordered[index]), -1, `${ordered[index - 1]} < ${ordered[index]}`);
  }
  assert.equal(semverCompare("1.0.0+a", "1.0.0+b"), 0);
  assert.equal(semverCompare("v1.0.0", "1.0.0"), null);
});

test("a version with one or two numbers is filled with zero before it is compared", () => {
  assert.equal(semverCompare("0.5", "0.5.0"), 0);
  assert.equal(semverCompare("1", "1.0.0"), 0);
  assert.equal(semverCompare("0.5", "0.5.1"), -1);
  assert.equal(semverCompare("2", "1.9.9"), 1);
  assert.equal(semverCompare("1.2-rc.1", "1.2.0"), -1);
  assert.equal(semverCompare("1.2+build.7", "1.2.0"), 0);
  assert.equal(semverCompare("0.5.0.1", "0.5.0"), null);
  assert.equal(semverCompare("", "0.5.0"), null);
});

test("license texts match the Python check", () => {
  assert.deepEqual(licenseErrors("MIT OR Apache-2.0"), []);
  assert.deepEqual(licenseErrors("MIT WITH LicenseRef-x"), []);
  assert.deepEqual(licenseErrors("GPL-2.0+"), []);
  assert.deepEqual(licenseErrors("MIT AND Foo AND Bar"), [
    "'MIT AND Foo AND Bar' names Bar, Foo, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("MIT+"), [
    "'MIT+' names MIT+, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("MIT Apache-2.0"), [
    "'MIT Apache-2.0' has two license identifiers with no operator between them; join several licenses with AND or OR, such as GPL-2.0-only AND CC-BY-SA-4.0",
  ]);
  assert.deepEqual(licenseErrors("LicenseRef-a LicenseRef-b"), [
    "'LicenseRef-a LicenseRef-b' has two license identifiers with no operator between them; join several licenses with AND or OR, such as GPL-2.0-only AND CC-BY-SA-4.0",
  ]);
  assert.deepEqual(licenseErrors("MIT Classpath-exception-2.0"), [
    "'MIT Classpath-exception-2.0' names Classpath-exception-2.0, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL-2.0-only WITH Classpath-exception-2.0 Autoconf-exception-2.0"), [
    "'GPL-2.0-only WITH Classpath-exception-2.0 Autoconf-exception-2.0' names Autoconf-exception-2.0, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("MIT WITH MIT"), [
    "'MIT WITH MIT' names MIT, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
});

test("a schema message is placed at the field it names", () => {
  const found = checker.check(mod({ links: { repository: "https://github.com/x/y" } }));
  const missing = found.find((entry) => entry.text === "'forums' is a required property");
  assert.equal(missing.path, "links");
  assert.equal(missing.field, "links.forums");
});
