import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, addTag, licenseErrors, semverCompare, releaseListRules, gameMaxNotes, hostRules, shareHosts, ERROR, NOTE } from "../js/rules.js";
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

test("a pin of a pack, of another spelling or of the same mod twice is an error, as in the index checks", () => {
  const pack = mod({ type: "modpack", version: "1.0.0", released_at: "2026-09-25T12:00:00Z" });
  pack.mods = [{ id: "BigPack", version: "1.0.0" }, { id: "othermod", version: "1.0.0" }, { id: "OtherMod", version: "1.1.0" }];
  const errors = texts(checker.check(pack, { index }), ERROR);
  assert.deepEqual(errors, [
    "mods[2]: 'OtherMod' is pinned by mods[1]",
    "mods[0]: 'BigPack' is itself a pack, and a pack does not nest in spec_version 1",
    "mods[1]: 'othermod' does not use the canonical id spelling 'OtherMod'",
  ]);
});

test("a release time the calendar does not have is an error, as check_schema.check_timestamp says", () => {
  const verdicts = {
    "2026-09-31T12:00:00Z": false,
    "2026-02-29T12:00:00Z": false,
    "1900-02-29T12:00:00Z": false,
    "0000-01-01T00:00:00Z": false,
    "2026-00-01T00:00:00Z": false,
    "2026-13-01T00:00:00Z": false,
    "2026-01-00T00:00:00Z": false,
    "2026-01-01T24:00:00Z": false,
    "2026-01-01T23:60:00Z": false,
    "2026-01-01T23:59:60Z": false,
    "2024-02-29T12:00:00Z": true,
    "2000-02-29T12:00:00Z": true,
    "0001-01-01T00:00:00Z": true,
    "2026-12-31T23:59:59.1234567891Z": true,
  };
  for (const [value, real] of Object.entries(verdicts)) {
    const pack = mod({ type: "modpack", version: "1.0.0", released_at: value, mods: [{ id: "OtherMod", version: "1.0.0" }] });
    const errors = texts(checker.check(pack, { index }), ERROR);
    assert.deepEqual(errors, real ? [] : [`released_at: '${value}' is not a real date and time`], value);
  }
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

test("a game_max at the newest build of the game release list is noted and never rejected", () => {
  const bounded = (game_max) => mod({ compatibility: { game_min: "2026.8.3.5117", game_max } });
  const found = checker.check(bounded("2026.9.10.5438"), { index, gameVersions: index.gameVersions });
  assert.deepEqual(texts(found, ERROR), []);
  assert.deepEqual(texts(found, NOTE), [
    "compatibility.game_max: '2026.9.10.5438' is the newest game build the index knows, and clients block the content on every build above game_max, so a game_max that only says which build the content was tested with blocks it on the next game update",
  ]);
  assert.equal(gameMaxNotes(bounded("2026.9.10.5438"), [...index.gameVersions].reverse()).length, 1);
  assert.equal(gameMaxNotes(bounded("2026.9.9.5438"), index.gameVersions).length, 1, "only the revision compares");
  assert.deepEqual(gameMaxNotes(bounded("2026.9.7.5402"), index.gameVersions), []);
  assert.deepEqual(gameMaxNotes(bounded("2026.9"), index.gameVersions), []);
  assert.deepEqual(gameMaxNotes(bounded("2026.9.10.5438"), []), []);
  assert.deepEqual(gameMaxNotes(bounded("2026.9.10.5438"), null), []);
  assert.deepEqual(texts(checker.check(bounded("2026.9.10.5438")), NOTE), [], "no snapshot, no note");
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
    "'MIT+' names MIT+, which is not on the SPDX license list; ids close to MIT+ are MIT, MIT-0, MIT-Wu, MIT-CMU, MIT-feh and MIT-enna; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL"), [
    "'GPL' names GPL, which is not on the SPDX license list; ids close to GPL are GPL-1.0-only, GPL-2.0-only, GPL-3.0-only, GPL-1.0-or-later, GPL-2.0-or-later and GPL-3.0-or-later; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("BSD-2"), [
    "'BSD-2' names BSD-2, which is not on the SPDX license list; ids close to BSD-2 are BSD-2-Clause, BSD-2-Clause-Views, BSD-2-Clause-Darwin, BSD-2-Clause-Patent, BSD-2-Clause-first-lines and BSD-2-Clause-pkgconf-disclaimer; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("CC BY-SA 4.0"), [
    "'CC BY-SA 4.0' names CC BY-SA 4.0, which is not on the SPDX license list; the id close to CC BY-SA 4.0 is CC-BY-SA-4.0; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("Apache2"), [
    "'Apache2' names Apache2, which is not on the SPDX license list; ids close to Apache2 are Apache-1.0, Apache-1.1 and Apache-2.0; the identifiers are at https://spdx.org/licenses/",
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
  assert.deepEqual(licenseErrors("Verbatim-man-pages"), [
    "'Verbatim-man-pages' names Verbatim-man-pages, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL-2.0-only WITH Assembly-exception"), [
    "'GPL-2.0-only WITH Assembly-exception' names Assembly-exception, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL-2.0-only WITH Nokia-Qt-exception-1.1"), []);
});

test("a close id fits the place of the name", () => {
  assert.deepEqual(licenseErrors("LLVM"), [
    "'LLVM' names LLVM, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("Classpath"), [
    "'Classpath' names Classpath, which is not on the SPDX license list; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL-2.0-only WITH Classpath"), [
    "'GPL-2.0-only WITH Classpath' names Classpath, which is not on the SPDX license list; the id close to Classpath is Classpath-exception-2.0; the identifiers are at https://spdx.org/licenses/",
  ]);
  assert.deepEqual(licenseErrors("GPL-2.0-only with LLVM"), [
    "'GPL-2.0-only with LLVM' names LLVM, which is not on the SPDX license list; the id close to LLVM is LLVM-exception; the identifiers are at https://spdx.org/licenses/",
  ]);
});

test("a schema message is placed at the field it names", () => {
  const found = checker.check(mod({ links: { repository: "https://github.com/x/y" } }));
  const missing = found.find((entry) => entry.text === "'forums' is a required property");
  assert.equal(missing.path, "links");
  assert.equal(missing.field, "links.forums");
});

const saveGated = (JSON.parse(read("../../schemas/authored.schema.json")).properties.type.not?.enum || []).includes("save");

test("the rollout gate refuses a save with its title, as check_schema.explain words it", { skip: !saveGated && "the gate no longer holds saves" }, () => {
  const save = { spec_version: 1, id: "ExampleSave", type: "save", name: "Example Save", authors: ["Example Author"], abstract: "A save.", license: "CC-BY-4.0" };
  assert.deepEqual(texts(checker.offline(save), ERROR), [
    "type: 'save' is a type that the index does not accept yet, because no release host for it exists (RFC 0085 Rollout)",
  ]);
});

test("the tags of a vehicle or a save are free-form and give no note", () => {
  for (const type of ["vehicle", "save"]) {
    for (const tags of [[], ["rover"], ["parts", "rover"]]) {
      assert.deepEqual(texts(checker.offline(mod({ type, tags })), NOTE), [], `${type} ${tags}`);
    }
  }
});

function addAll(entries, tags = []) {
  for (const entry of entries) {
    const added = addTag(tags, entry, checker.tagPattern);
    assert.equal(added.error, null, entry);
    tags = added.tags;
  }
  return tags;
}

test("a typed tag is stored in its lowercase form", () => {
  assert.deepEqual(addAll(["Physics", "Space Station", "  RCS "]), ["physics", "space-station", "rcs"]);
  assert.deepEqual(addAll(["-Big_ _Engines-", "x2-engine"]), ["big-engines", "x2-engine"]);
});

test("a typed curated tag in another case selects the curated tag", () => {
  const tags = addAll(["Gameplay"]);
  assert.deepEqual(tags, ["gameplay"]);
  assert.ok(tags.every((tag) => checker.curated.includes(tag)));
});

test("a typed tag that is already there is not added twice", () => {
  assert.deepEqual(addAll(["Physics"], ["physics"]), ["physics"]);
  assert.deepEqual(addAll(["", "   "], ["physics"]), ["physics"]);
});

// The same cases and words as Documents in tools/test_check_hosts.py.
const HOSTS = shareHosts(
  '[ksamods]\nkind = "share"\nstorage = "ksamods-content/share"\ntypes = ["vehicle", "save"]\n# a comment\n',
);
const SAVES_ONLY = { ksamods: { ...HOSTS.ksamods, types: ["save"] } };

function vehicle(releases) {
  return { id: "ExampleRover", type: "vehicle", releases };
}

function hostLines(document, hosts = HOSTS) {
  return hostRules(document, hosts).map((entry) => `${entry.path}: ${entry.text}`);
}

test("hosts.toml gives its tables", () => {
  assert.deepEqual(Object.keys(HOSTS), ["ksamods"]);
  assert.deepEqual(shareHosts(""), {});
  assert.deepEqual(shareHosts("# no host yet\n"), {});
});

test("a vehicle on a registered share host passes", () => {
  assert.deepEqual(hostLines(vehicle({ ksamods: "ExampleRover" })), []);
});

test("a share host key that hosts.toml does not register is refused", () => {
  assert.deepEqual(hostLines(vehicle({ otherhost: "ExampleRover" })), [
    "releases.otherhost: 'otherhost' is not a share host that hosts.toml registers",
  ]);
  assert.deepEqual(hostLines(vehicle({ ksamods: "ExampleRover" }), {}), [
    "releases.ksamods: 'ksamods' is not a share host that hosts.toml registers",
  ]);
  assert.deepEqual(hostLines(vehicle({ constructor: "ExampleRover" })), [
    "releases.constructor: 'constructor' is not a share host that hosts.toml registers",
  ]);
});

test("a vehicle on a share host that takes only saves is refused", () => {
  assert.deepEqual(hostLines(vehicle({ ksamods: "ExampleRover" }), SAVES_ONLY), [
    "releases.ksamods: the share host 'ksamods' takes save, and this document is a vehicle",
  ]);
  const mod = { id: "ExampleMod", type: "mod", releases: { ksamods: "ExampleMod" } };
  assert.match(hostLines(mod)[0], /this document is a mod$/);
});

test("a share host is named with the id of the listing", () => {
  for (const value of ["OtherRover", "examplerover"]) {
    assert.deepEqual(hostLines(vehicle({ ksamods: value })), [
      `releases.ksamods: a share host is named with the id of the listing, 'ExampleRover', and not '${value}'`,
    ]);
  }
});

test("a share host next to another host needs an authority that the section names", () => {
  assert.deepEqual(hostLines(vehicle({ ksamods: "ExampleRover", github: "a/b" })), [
    "releases: the section names several hosts, so it needs an 'authority' key that names one of github, ksamods",
  ]);
  assert.deepEqual(hostLines(vehicle({ ksamods: "ExampleRover", github: "a/b", authority: "ksamods" })), []);
  assert.deepEqual(hostLines(vehicle({ github: "a/b", authority: "ksamods" })), [
    "releases.authority: 'ksamods' is not a host this section names",
  ]);
  const fixed = vehicle({ github: "a/b", spacedock: 4, authority: "github", since: "1.0", tag_prefix: "x-" });
  assert.deepEqual(hostLines(fixed, {}), []);
});

test("the checker runs the share host rules with the hosts.toml it was given", () => {
  const schema = JSON.parse(read("../../schemas/authored.schema.json"));
  const tagsText = read("../../tags.toml");
  const document = mod({ releases: { ksamods: "TestMod" } });
  const unregistered = createChecker({ schema, tagsText }).offline(document);
  assert.ok(unregistered.some((entry) => entry.path === "releases.ksamods" && entry.text.includes("is not a share host")));
  const hostsText = '[ksamods]\nkind = "share"\ntypes = ["vehicle"]\n';
  const registered = createChecker({ schema, tagsText, hostsText }).offline(document);
  assert.ok(registered.some((entry) => entry.text === "the share host 'ksamods' takes vehicle, and this document is a mod"));
});

test("an entry that cannot become a tag is refused with its name", () => {
  for (const entry of ["C++", "Space - Station", "---"]) {
    const added = addTag(["physics"], ` ${entry} `, checker.tagPattern);
    assert.deepEqual(added.tags, ["physics"]);
    assert.equal(added.error, `'${entry}' cannot be a tag. A tag is lowercase letters and digits in words joined by -, such as space-station.`);
  }
});
