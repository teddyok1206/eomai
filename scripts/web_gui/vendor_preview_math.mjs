// Maintainer-only, deterministic import. No runtime network/package-manager dependency.
import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";

const version = "0.19.0";
const integrity = "v6Tznz3zJ7u3niRCoDTsumM2+HA2XXcCu+WAacCeHD2z3p9A9Ks987o5FzfTGBN0e8A0vjEgIDvLbICrXpdw/Q==";
const response = await fetch(`https://registry.npmjs.org/katex/-/katex-${version}.tgz`);
assert(response.ok, "Pinned KaTeX archive is unavailable");
const archive = Buffer.from(await response.arrayBuffer());
assert(archive.length <= 4 * 1024 * 1024, "Unexpected archive size");
assert.equal(createHash("sha512").update(archive).digest("base64"), integrity);
const entries = [
  ["package/dist/katex.mjs", `apps/web_gui/eom_web_gui/static/vendor-katex-${version}.js`],
  ["package/LICENSE", "apps/web_gui/eom_web_gui/static/vendor-katex-LICENSE.txt"],
];
let patch = "*** Begin Patch\n";
for (const [member, target] of entries) {
  // Stream an exact member, never extract archive paths into the filesystem.
  const extracted = spawnSync("tar", ["-xzO", "-f", "-", member], {
    input: archive, maxBuffer: 4 * 1024 * 1024,
  });
  assert.equal(extracted.status, 0, "Pinned archive member missing");
  const source = extracted.stdout.toString("utf8");
  assert.equal(Buffer.from(source).compare(extracted.stdout), 0, "Non-UTF8 source");
  assert(source.endsWith("\n"), "Canonical vendor source must end with newline");
  if (process.argv.includes("--check")) {
    assert.equal(readFileSync(target).compare(extracted.stdout), 0, target);
  } else {
    patch += `*** Add File: ${target}\n`;
    patch += source.slice(0, -1).split("\n").map(line => "+" + line).join("\n") + "\n";
  }
  console.log(`${target} sha256=${createHash("sha256").update(extracted.stdout).digest("hex")}`);
}
if (!process.argv.includes("--check")) {
  patch += "*** End Patch\n";
  const applied = spawnSync("apply_patch", [], {input: patch, encoding: "utf8"});
  assert.equal(applied.status, 0, applied.stderr);
  console.log(applied.stdout.trim());
}
