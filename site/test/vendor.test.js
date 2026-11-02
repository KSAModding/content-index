import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

// Dependabot watches site/vendor/package.json and its lock, but the page loads the bundles, which only a new build changes.
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

// The lock can hold a package more than once, nested below the package that needs another version, so every copy counts.
function lockVersions(lock) {
  const versions = {};
  for (const [path, entry] of Object.entries(lock.packages)) {
    if (path === "") continue;
    const name = path.slice(path.lastIndexOf("node_modules/") + "node_modules/".length);
    (versions[name] ??= new Set()).add(entry.version);
  }
  return versions;
}

// The packages of the lock that no bundle contains, so the README table does not name them.
// argparse serves only the command line of markdown-it, esbuild leaves require-from-string out of the ajv bundle, and the @esbuild packages are the esbuild binary of each platform.
const notBundled = (name) => name === "argparse" || name === "require-from-string" || name.startsWith("@esbuild/");

const manifest = JSON.parse(read("../vendor/package.json"));
const lock = JSON.parse(read("../vendor/package-lock.json"));
const readme = readmeVersions(read("../vendor/README.md"));
const mismatch = "site/vendor and the table in site/vendor/README.md disagree, so build the bundle again from the new versions and update the table";

test("the README table has package rows", () => {
  assert.ok(Object.keys(readme).length > 1, "the README table has no package rows");
});

test("the vendor package.json pins exact versions", () => {
  for (const [name, version] of Object.entries({ ...manifest.devDependencies, ...manifest.overrides })) {
    assert.match(version, /^\d+\.\d+\.\d+$/, `${name} is not pinned to one version`);
  }
});

test("the vendor package.json names the versions the vendor README names", () => {
  for (const [name, version] of Object.entries({ ...manifest.devDependencies, ...manifest.overrides })) {
    assert.equal(version, readme[name], `package.json names ${name} ${version}, but ${mismatch}`);
  }
});

test("the vendor lock was written from the vendor package.json", () => {
  assert.deepEqual(
    lock.packages[""].devDependencies,
    manifest.devDependencies,
    "package-lock.json is not current, so run npm install --package-lock-only --ignore-scripts in site/vendor",
  );
});

test("the vendor lock resolves every package to the version the vendor README names", () => {
  const locked = lockVersions(lock);
  for (const [name, version] of Object.entries(readme)) {
    assert.deepEqual([...(locked[name] ?? [])], [version], `package-lock.json resolves ${name} differently, but ${mismatch}`);
  }
  for (const name of Object.keys(locked)) {
    assert.ok(name in readme || notBundled(name), `package-lock.json holds ${name}, which the README table does not name`);
  }
});
