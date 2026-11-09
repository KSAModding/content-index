import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { createChecker, ERROR, NOTE } from "../js/rules.js";
import { parseDocument } from "../js/toml.js";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");
const schema = JSON.parse(read("../../schemas/authored.schema.json"));
const tagsText = read("../../tags.toml");
// Whether hosts.toml registers a share host is no vector rule, because the
// Python runner has no hosts.toml, so the share host of the vectors is registered here.
const hostsText = '[ksamods]\nkind = "share"\ntypes = ["vehicle", "save"]\n';
const checker = createChecker({ schema, tagsText, hostsText });
const { vectors } = JSON.parse(read("../../schemas/vectors.json"));

function lines(found) {
  return found.map((entry) => `${entry.path}: ${entry.text}`);
}

function run(rules, vector) {
  const document = parseDocument(vector.toml);
  return vector.game_versions
    ? rules.check(document, { gameVersions: vector.game_versions })
    : rules.offline(document);
}

function agrees(found, vector) {
  const said = lines(found);
  assert.equal(!found.some((entry) => entry.level === ERROR), vector.accepted, said.join("\n"));
  assert.equal(found.some((entry) => entry.level === NOTE), vector.noted, said.join("\n"));
  if (vector.says) {
    assert.ok(said.some((line) => line.includes(vector.says)), said.join("\n"));
  }
}

for (const vector of vectors) {
  test(`${vector.rule}: ${vector.name}`, () => {
    agrees(run(checker, vector), vector);
  });
}
