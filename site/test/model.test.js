import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { parseDocument, writeDocument } from "../js/toml.js";
import { emptyForm, formFromDocument, documentFromForm } from "../js/model.js";
import { newFileUrl, editUrl, pullRequestLink, copyAndOpen, prefillFromRepository, repositoryApiUrl, listingPath, packPath, documentPath, URL_LIMIT, PASTE_NEW, PASTE_EDIT } from "../js/github.js";

const LISTINGS = new URL("../../listings/", import.meta.url);

test("a listing loaded into the form and written back is unchanged", () => {
  for (const name of fs.readdirSync(LISTINGS).filter((file) => file.endsWith(".toml"))) {
    const base = parseDocument(fs.readFileSync(new URL(name, LISTINGS), "utf8"));
    assert.deepEqual(documentFromForm(formFromDocument(base), base), base, name);
  }
});

test("a listing in the usual layout comes back byte for byte through the form", () => {
  for (const name of ["StarMap.toml", "DeltaVMap.toml", "KSArmory.toml"]) {
    const text = fs.readFileSync(new URL(`fixtures/${name}`, import.meta.url), "utf8");
    const base = parseDocument(text);
    assert.equal(writeDocument(documentFromForm(formFromDocument(base), base)), text, name);
  }
});

test("a changed listing keeps the order of its links and adds new ones at the end", () => {
  const base = { spec_version: 1, id: "M", type: "mod", links: { forums: "f", homepage: "h", repository: "r" } };
  const form = formFromDocument(base);
  form.links.bugtracker = "b";
  form.extraLinks.push({ key: "wiki", url: "w" });
  assert.deepEqual(Object.keys(documentFromForm(form, base).links), ["forums", "homepage", "repository", "bugtracker", "wiki"]);
});

test("the standard link keys are fields of the form, not extra links", () => {
  const links = { forums: "f", homepage: "h", repository: "r", spacedock: "s", bugtracker: "b", discussions: "d" };
  const form = formFromDocument({ spec_version: 1, id: "M", type: "mod", links });
  assert.deepEqual(form.extraLinks, []);
  assert.deepEqual(form.links, links);
  assert.deepEqual(documentFromForm(form, null).links, links);
});

test("an extra link that repeats a standard key leaves the field alone", () => {
  const form = emptyForm();
  form.links.homepage = "https://example.com";
  form.links.forums = "https://forums.ahwoo.com/t/1";
  form.extraLinks = [{ key: "homepage", url: "" }, { key: "forums", url: "https://elsewhere.example" }];
  const links = documentFromForm(form, null).links;
  assert.equal(links.homepage, "https://example.com");
  assert.equal(links.forums, "https://forums.ahwoo.com/t/1");
});

test("keys the form does not edit are kept", () => {
  const base = parseDocument(fs.readFileSync(new URL("fixtures/StarMap.toml", import.meta.url), "utf8"));
  base.status = "deprecated";
  base.superseded_by = "StarMap2";
  base.dependencies = [{ kind: "required", any_of: [{ id: "A" }, { id: "B", min: "1.0.0" }] }];
  const form = formFromDocument(base);
  form.dependencies.push({ id: "C", kind: "optional", min: "", max: "" });
  form.icon = { url: "https://example.invalid/icon.png", sha256: "a".repeat(64), width: "512", height: "512", size: "100", license: "", attribution: "", source: "" };
  const changed = documentFromForm(form, base);
  assert.deepEqual(changed.provides.configure, base.provides.configure);
  assert.deepEqual(changed.provides.instance, base.provides.instance);
  assert.deepEqual(changed.install.uninstall, base.install.uninstall);
  assert.equal(changed.superseded_by, "StarMap2");
  assert.deepEqual(changed.dependencies, [base.dependencies[0], { id: "C", kind: "optional" }]);
  assert.deepEqual(changed.images.icon, { url: "https://example.invalid/icon.png", sha256: "a".repeat(64), width: 512, height: 512, size: 100 });
});

test("an author with a comma in the name survives a change of another field", () => {
  const base = { spec_version: 1, id: "M", type: "mod", authors: ["Smith, J.", "Doe"] };
  const form = formFromDocument(base);
  form.name = "Changed";
  assert.deepEqual(documentFromForm(form, base).authors, ["Smith, J.", "Doe"]);
});

test("an empty form gives a document with only the fixed keys", () => {
  assert.deepEqual(documentFromForm(emptyForm(), null), { spec_version: 1, type: "mod" });
});

test("the form keeps only what applies to the type", () => {
  const form = emptyForm();
  Object.assign(form, { id: "L", type: "mod-loader", loaderId: "StarMap", loaderMin: "1.0.0", launch: "L.exe", installTarget: "standalone" });
  form.platforms.linux = { launch: "L.dll", runtime: "dotnet" };
  const document = documentFromForm(form, null);
  assert.equal(document.loader, undefined);
  assert.deepEqual(document.install, { target: "standalone" });
  assert.deepEqual(document.provides, { launch: "L.exe", platform: { linux: { runtime: "dotnet", launch: "L.dll" } } });
  form.type = "mod";
  const mod = documentFromForm(form, null);
  assert.equal(mod.provides, undefined);
  assert.deepEqual(mod.loader, { id: "StarMap", min: "1.0.0" });
});

test("two release hosts keep the authority, one host drops it", () => {
  const form = emptyForm();
  Object.assign(form, { github: "a/b", spacedock: "12", authority: "github" });
  assert.deepEqual(documentFromForm(form, null).releases, { github: "a/b", spacedock: 12, authority: "github" });
  form.spacedock = "";
  assert.deepEqual(documentFromForm(form, null).releases, { github: "a/b" });
});

test("since is written next to a release host and dropped without one", () => {
  const form = emptyForm();
  Object.assign(form, { spacedock: "12", since: " 1.2 " });
  assert.deepEqual(documentFromForm(form, null).releases, { spacedock: 12, since: "1.2" });
  form.spacedock = "";
  assert.equal(documentFromForm(form, null).releases, undefined);
});

test("since comes back from a loaded listing and is written after the hosts", () => {
  const text = "[releases]\ngithub = \"a/b\"\nspacedock = 12\nauthority = \"github\"\nsince = \"0.5\"\n";
  const base = parseDocument(text);
  const form = formFromDocument(base);
  assert.equal(form.since, "0.5");
  const written = writeDocument(documentFromForm(form, base));
  assert.match(written, /\[releases\]\ngithub = "a\/b"\nspacedock = 12\nauthority = "github"\nsince = "0\.5"\n/);
});

test("the new-file address carries the file until it gets too long", () => {
  const short = newFileUrl(listingPath("MyMod"), "id = \"MyMod\"\n");
  assert.equal(short.filled, true);
  assert.equal(short.url, "https://github.com/KSAModding/content-index/new/main?filename=listings/MyMod.toml&value=id%20%3D%20%22MyMod%22%0A");
  const long = newFileUrl(listingPath("MyMod"), "x".repeat(URL_LIMIT));
  assert.equal(long.filled, false);
  assert.equal(long.url, "https://github.com/KSAModding/content-index/new/main?filename=listings/MyMod.toml");
  assert.equal(editUrl("MyMod"), "https://github.com/KSAModding/content-index/edit/main/listings/MyMod.toml");
});

test("a new listing gets the plain link and the paste step once the link would pass the limit", () => {
  const text = fs.readFileSync(new URL("fixtures/StarMap.toml", import.meta.url), "utf8");
  const plain = "https://github.com/KSAModding/content-index/new/main?filename=listings/StarMap.toml";
  const filled = `${plain}&value=${encodeURIComponent(text)}`;
  assert.ok(filled.length > URL_LIMIT && filled.length < 5900, "the fixture sits between the limit and the link GitHub refused");
  assert.deepEqual(pullRequestLink(listingPath("StarMap"), text), { url: plain, step: PASTE_NEW });
  const short = "id = \"MyMod\"\n";
  assert.deepEqual(pullRequestLink(listingPath("MyMod"), short), { url: newFileUrl(listingPath("MyMod"), short).url, step: "" });
});

test("a changed listing opens the edit page and says to replace the whole file", () => {
  assert.deepEqual(pullRequestLink(listingPath("MyMod"), "id = \"MyMod\"\n", { id: "MyMod", type: "mod" }), {
    url: "https://github.com/KSAModding/content-index/edit/main/listings/MyMod.toml",
    step: PASTE_EDIT,
  });
});

test("the button copies the file before it opens GitHub", async () => {
  const calls = [];
  const clipboard = { writeText: async (text) => calls.push(["copy", text]) };
  const tab = { opener: "page" };
  const open = (url) => calls.push(["open", url]) && tab;
  assert.deepEqual(await copyAndOpen("https://github.com/x", "id = 1\n", clipboard, open), { copied: true, opened: true });
  assert.deepEqual(calls, [["copy", "id = 1\n"], ["open", "https://github.com/x"]]);
  assert.equal(tab.opener, null);
});

test("GitHub still opens when the browser refuses the clipboard, and a blocked tab is reported", async () => {
  const refused = { writeText: async () => { throw new Error("NotAllowedError"); } };
  assert.deepEqual(await copyAndOpen("u", "t", refused, () => ({})), { copied: false, opened: true });
  assert.deepEqual(await copyAndOpen("u", "t", undefined, () => ({})), { copied: false, opened: true });
  assert.deepEqual(await copyAndOpen("u", "t", { writeText: async () => {} }, () => null), { copied: true, opened: false });
});

test("GitHub repository facts fill the form fields", () => {
  const facts = prefillFromRepository({
    name: "MyMod",
    description: " A mod. ",
    license: { spdx_id: "NOASSERTION" },
    html_url: "https://github.com/me/MyMod",
    has_issues: true,
    fork: false,
    owner: { login: "me", type: "Organization" },
  });
  assert.deepEqual(facts, {
    name: "MyMod",
    abstract: "A mod.",
    license: "",
    repository: "https://github.com/me/MyMod",
    bugtracker: "https://github.com/me/MyMod/issues",
    owner: "me",
    organization: true,
    fork: false,
  });
  assert.equal(repositoryApiUrl("me/MyMod"), "https://api.github.com/repos/me/MyMod");
  assert.equal(repositoryApiUrl("../x"), null);
});

test("a new listing written from the form matches the listing layout", () => {
  const form = emptyForm();
  Object.assign(form, {
    id: "MyMod",
    github: "me/MyMod",
    name: "My Mod",
    authors: "Me, You",
    abstract: "Does things.",
    description: "Line one.\nLine two.\n",
    license: "MIT",
    gameMin: "2026.9.10.5438",
    loaderId: "StarMap",
    loaderMin: "0.4.7",
    tags: ["gameplay"],
  });
  form.links.forums = "https://forums.ahwoo.com/threads/my-mod.1/";
  assert.equal(writeDocument(documentFromForm(form, null)), [
    "spec_version = 1",
    "id = \"MyMod\"",
    "type = \"mod\"",
    "name = \"My Mod\"",
    "authors = [\"Me\", \"You\"]",
    "abstract = \"Does things.\"",
    "description = \"\"\"",
    "Line one.",
    "Line two.",
    "\"\"\"",
    "license = \"MIT\"",
    "tags = [\"gameplay\"]",
    "",
    "[releases]",
    "github = \"me/MyMod\"",
    "",
    "[links]",
    "forums = \"https://forums.ahwoo.com/threads/my-mod.1/\"",
    "",
    "[compatibility]",
    "game_min = \"2026.9.10.5438\"",
    "",
    "[loader]",
    "id = \"StarMap\"",
    "min = \"0.4.7\"",
    "",
  ].join("\n"));
});
