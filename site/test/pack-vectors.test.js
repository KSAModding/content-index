import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { ERROR, NOTE } from "../js/rules.js";
import { indexFacts } from "../js/snapshot.js";
import { parseDocument } from "../js/toml.js";
import { memberMessages, missingDependencies, PIN_VERSION } from "../js/pack.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const { vectors } = JSON.parse(read("../../schemas/pack-vectors.json"));

// The mini snapshot of a vector as the snapshot carries it: a delisted listing
// is a tombstone, and a disputed one ships whole with its state.
function snapshotOf(mini) {
  const folded = (ids) => new Set((ids || []).map((id) => id.toLowerCase()));
  const [delisted, disputed] = [folded(mini.delisted), folded(mini.disputed)];
  return {
    listings: mini.listings.map((listing) => {
      const key = listing.id.toLowerCase();
      if (delisted.has(key)) return { id: listing.id, index_status: { state: "delisted" } };
      const entry = { id: listing.id, authored: { type: listing.type }, releases: listing.releases };
      return disputed.has(key) ? { ...entry, index_status: { state: "disputed" } } : entry;
    }),
    packs: [],
    game_versions: { versions: [] },
  };
}

const lines = (found, level) => found.filter((entry) => entry.level === level).map((entry) => `${entry.path}: ${entry.text}`);

for (const vector of vectors) {
  test(`pack members: ${vector.name}`, () => {
    const index = indexFacts(snapshotOf(vector.snapshot), /^$/);
    const document = parseDocument(vector.pack);
    const found = memberMessages(document, index);
    assert.deepEqual(lines(found, ERROR), vector.errors);
    assert.deepEqual(lines(found, NOTE), vector.notes);
    assert.equal(!found.some((entry) => entry.level === ERROR), vector.accepted);
    const { pins } = missingDependencies(document, index);
    assert.deepEqual(pins, vector.adds || []);
    if (pins.length) {
      assert.deepEqual(lines(memberMessages({ ...document, mods: [...document.mods, ...pins] }, index), ERROR), []);
    }
  });
}

test("every dependency bound in a vector is full SemVer, as the stamper writes it", () => {
  for (const vector of vectors) {
    for (const listing of vector.snapshot.listings) {
      for (const dependency of listing.releases.flatMap((entry) => entry.dependencies || [])) {
        for (const option of Array.isArray(dependency.any_of) ? [dependency, ...dependency.any_of] : [dependency]) {
          for (const bound of [option.min, option.max].filter((value) => value !== undefined)) {
            assert.match(bound, PIN_VERSION, `${vector.name}: ${listing.id} has the bound '${bound}'`);
          }
        }
      }
    }
  }
});

test("the page reads a pin version with the semver pattern of the schema", () => {
  const schema = JSON.parse(read("../../schemas/authored.schema.json"));
  assert.equal(PIN_VERSION.source, schema.$defs.semver.pattern);
});
