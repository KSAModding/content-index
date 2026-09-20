import { test } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { inspect, measure, readCapped, Invalid, ICON, DESCRIPTION } from "../js/images.js";
import { zipNames, deriveRoot, inspectArchive } from "../js/archive.js";

function u32(value, little = false) {
  const bytes = Buffer.alloc(4);
  if (little) bytes.writeUInt32LE(value);
  else bytes.writeUInt32BE(value);
  return bytes;
}

function chunk(kind, body) {
  return Buffer.concat([u32(body.length), Buffer.from(kind, "ascii"), body, u32(0)]);
}

function png(width, height, { animated = false, pixels = true } = {}) {
  const header = Buffer.concat([u32(width), u32(height), Buffer.from([8, 2, 0, 0, 0])]);
  return new Uint8Array(Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    ...(animated ? [chunk("acTL", Buffer.alloc(8))] : []),
    ...(pixels ? [chunk("IDAT", Buffer.from([0]))] : []),
    chunk("IEND", Buffer.alloc(0)),
  ]));
}

function jpeg(width, height) {
  const frame = Buffer.from([0xff, 0xc0, 0x00, 0x11, 0x08, height >> 8, height & 0xff, width >> 8, width & 0xff, 0x03]);
  return new Uint8Array(Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x04, 0x00, 0x00]), frame, Buffer.alloc(12)]));
}

function riff(chunks) {
  const body = Buffer.concat([Buffer.from("WEBP", "ascii"), ...chunks]);
  return new Uint8Array(Buffer.concat([Buffer.from("RIFF", "ascii"), u32(body.length, true), body]));
}

function webpChunk(kind, body) {
  const padded = body.length % 2 ? Buffer.concat([body, Buffer.alloc(1)]) : body;
  return Buffer.concat([Buffer.from(kind, "ascii"), u32(body.length, true), padded]);
}

function lossless(width, height) {
  const bits = (width - 1) | ((height - 1) << 14);
  return webpChunk("VP8L", Buffer.concat([Buffer.from([0x2f]), u32(bits, true)]));
}

function extended(width, height, flags) {
  const body = Buffer.alloc(10);
  body[0] = flags;
  body.writeUIntLE(width - 1, 4, 3);
  body.writeUIntLE(height - 1, 7, 3);
  return webpChunk("VP8X", body);
}

test("the format, the size and the animation come from the bytes", () => {
  assert.deepEqual(inspect(png(512, 256)), { format: "PNG", width: 512, height: 256, animated: false });
  assert.equal(inspect(png(300, 300, { animated: true })).animated, true);
  assert.deepEqual(inspect(jpeg(640, 480)), { format: "JPEG", width: 640, height: 480, animated: false });
  assert.deepEqual(inspect(riff([lossless(700, 400)])), { format: "WebP", width: 700, height: 400, animated: false });
  assert.deepEqual(inspect(riff([extended(900, 600, 0x02), webpChunk("ANIM", Buffer.alloc(6))])),
    { format: "WebP", width: 900, height: 600, animated: true });
});

test("bytes that are no image, or end early, are refused", () => {
  assert.throws(() => inspect(new TextEncoder().encode("GIF89a")), { message: "the bytes are not PNG, JPEG or WebP" });
  assert.throws(() => inspect(png(10, 10, { pixels: false })), { message: "the PNG carries no image data" });
  assert.throws(() => inspect(png(10, 10).slice(0, 30)), Invalid);
  assert.throws(() => inspect(jpeg(10, 10).slice(0, 12)), Invalid);
  assert.throws(() => inspect(riff([lossless(10, 10)]).slice(0, 20)), { message: "the WebP is shorter than its RIFF header says" });
});

test("measuring gives the digest and the problems of the role", async () => {
  const bytes = png(512, 512);
  const result = await measure(bytes, ICON);
  assert.equal(result.sha256, createHash("sha256").update(bytes).digest("hex"));
  assert.equal(result.size, bytes.length);
  assert.deepEqual(result.problems, []);
  assert.deepEqual((await measure(png(300, 700), ICON)).problems, [
    "300 by 700 pixels is outside the limits: the shorter side 256 to 1024, the longer side at most 2 times the shorter side",
  ]);
  assert.deepEqual((await measure(png(300, 300, { animated: true }), DESCRIPTION)).problems, ["the PNG is animated"]);
  assert.deepEqual((await measure(png(2049, 10), DESCRIPTION)).problems, ["2049 by 10 pixels is outside 1 to 2048 per side"]);
});

test("reading a body stops after the cap", async () => {
  let pulled = 0;
  const body = () => new ReadableStream({
    pull(controller) {
      pulled += 1;
      if (pulled > 100) controller.close();
      else controller.enqueue(new Uint8Array(10));
    },
  });
  assert.equal(await readCapped(new Response(body()), 25), null);
  assert.ok(pulled < 10, `read ${pulled} chunks`);
  pulled = 97;
  assert.deepEqual(await readCapped(new Response(body()), 30), new Uint8Array(30));
});

function zip(names, { note = "", prefix = "", zip64 = false } = {}) {
  const locals = [];
  const central = [];
  let offset = 0;
  for (const name of names) {
    const encoded = Buffer.from(name, "utf8");
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x800, 6);
    local.writeUInt16LE(encoded.length, 26);
    const entry = Buffer.alloc(46);
    entry.writeUInt32LE(0x02014b50, 0);
    entry.writeUInt16LE(20, 4);
    entry.writeUInt16LE(20, 6);
    entry.writeUInt16LE(0x800, 8);
    entry.writeUInt16LE(encoded.length, 28);
    entry.writeUInt32LE(offset, 42);
    locals.push(local, encoded);
    central.push(entry, encoded);
    offset += local.length + encoded.length;
  }
  const directory = Buffer.concat(central);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(names.length, 8);
  end.writeUInt16LE(names.length, 10);
  end.writeUInt32LE(zip64 ? 0xffffffff : directory.length, 12);
  end.writeUInt32LE(zip64 ? 0xffffffff : offset, 16);
  const comment = Buffer.from(note, "utf8");
  end.writeUInt16LE(comment.length, 20);
  const records = [];
  if (zip64) {
    const record = Buffer.alloc(56);
    record.writeUInt32LE(0x06064b50, 0);
    record.writeBigUInt64LE(44n, 4);
    record.writeBigUInt64LE(BigInt(names.length), 24);
    record.writeBigUInt64LE(BigInt(names.length), 32);
    record.writeBigUInt64LE(BigInt(directory.length), 40);
    record.writeBigUInt64LE(BigInt(offset), 48);
    const locator = Buffer.alloc(20);
    locator.writeUInt32LE(0x07064b50, 0);
    locator.writeBigUInt64LE(BigInt(offset + directory.length), 8);
    locator.writeUInt32LE(1, 16);
    records.push(record, locator);
  }
  return new Blob([Buffer.from(prefix), ...locals, directory, ...records, end, comment]);
}

test("the names come from the central directory of the zip", async () => {
  const names = ["MyMod/", "MyMod/mod.toml"];
  assert.deepEqual(await zipNames(zip(names)), names);
  assert.deepEqual(await zipNames(zip(names, { note: "built by hand", prefix: "stub" })), names);
  assert.deepEqual(await zipNames(zip(names, { zip64: true })), names);
  assert.deepEqual(await zipNames(zip(["MyMod/a\0b"])), ["MyMod/a"]);
});

test("a file that is no zip is refused with the reason of the stamper", async () => {
  await assert.rejects(zipNames(new Blob([new Uint8Array(10)])), { message: "the archive is not a readable zip, File is not a zip file" });
  const whole = new Uint8Array(await zip(["MyMod/mod.toml"]).arrayBuffer());
  whole[whole.length - 22 - 60] = 0;
  await assert.rejects(zipNames(new Blob([whole])), { message: "the archive is not a readable zip, Bad magic number for central directory" });
});

test("the install root is derived by the rule of the stamper", () => {
  assert.equal(deriveRoot(["MyMod/mod.toml", "MyMod/MyMod.dll", "README.md"], "MyMod", "mod"), "MyMod");
  assert.equal(deriveRoot(["Docs/a.md", "MyMod/mod.toml"], "MyMod", "mod"), "MyMod");
  assert.equal(deriveRoot(["A/x", "B/y"], "MyMod", "mod"), null);
  assert.equal(deriveRoot(["Loader.exe"], "Loader", "mod-loader"), "");
  assert.throws(() => deriveRoot(["mymod/mod.toml"], "MyMod", "mod"), { message: /so the casing has to match$/ });
  assert.throws(() => deriveRoot(["Other/mod.toml"], "MyMod", "mod"),
    { message: "the archive's top-level directory is 'Other', which does not match the id 'MyMod'" });
});

test("every launch of a loader has to be in the archive", () => {
  const loader = {
    id: "Loader",
    type: "mod-loader",
    provides: { launch: "Loader.exe", platform: { linux: { runtime: "dotnet", launch: "Loader.dll" }, macos: { launch: "bin/../Loader.app" } } },
  };
  const result = inspectArchive(["Loader.exe", "Loader.app"], loader);
  assert.equal(result.root, "");
  assert.deepEqual(result.launches, ["Loader.exe", "bin/../Loader.app"]);
  assert.deepEqual(result.problems, ["the provides platform linux launch path 'Loader.dll' is not in the release archive"]);
  const authored = inspectArchive(["x/Loader.exe"], { ...loader, install: { root: "y", target: "standalone" } });
  assert.deepEqual(authored.problems, ["the authored install root 'y' is not in the archive"]);
});

test("a mod archive with no layout to derive names the standard layout", () => {
  assert.deepEqual(inspectArchive(["a.dll"], { id: "MyMod", type: "mod" }).problems, [
    "the install root is neither derivable from the archive nor authored: the standard layout is one top-level directory containing mod.toml, named 'MyMod'",
  ]);
});
