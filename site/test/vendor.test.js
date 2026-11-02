import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

// Dependabot watches site/vendor/package.json, but the page loads the bundles, which only a new build changes.
// So a version bump there has to come with a new bundle and a README table that names the same version.
function readmeVersions(text) {
  const versions = {};
  const esbuild = text.match(/bundled with esbuild (\S+) /);
  assert.ok(esbuild, "the README names no esbuild version");
  versions.esbuild = esbuild[1];
  for (const line of text.split("\n")) {
    const row = line.match(/^\| `[^`]+\.js` \| (.+) \|$/);
    if (!row) continue;
    for (const item of row[1].split(", ")) {
      const entry = item.match(/^(\S+) (\d\S*)/);
      assert.ok(entry, `the README names no version in "${item}"`);
      assert.equal(versions[entry[1]], undefined, `the README names ${entry[1]} twice`);
      versions[entry[1]] = entry[2];
    }
  }
  return versions;
}

test("the vendor package.json names the versions the vendor README names", () => {
  const manifest = JSON.parse(read("../vendor/package.json")).devDependencies;
  const readme = readmeVersions(read("../vendor/README.md"));
  assert.ok(Object.keys(readme).length > 1, "the README table has no package rows");
  assert.deepEqual(
    manifest,
    readme,
    "site/vendor/package.json and the table in site/vendor/README.md disagree, so build the bundle again from the new versions and update the table",
  );
});

test("the vendor package.json pins exact versions", () => {
  for (const [name, version] of Object.entries(JSON.parse(read("../vendor/package.json")).devDependencies)) {
    assert.match(version, /^\d+\.\d+\.\d+$/, `${name} is not pinned to one version`);
  }
});
