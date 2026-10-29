#!/usr/bin/env node
// Copy only the dependency closure of the requested packages out of a
// node_modules tree, using the hidden lockfile npm leaves in it.
//
// Usage: node prune-node-modules.js <src node_modules> <dst> <package>...
//
// Runs inside the upstream Super-Linter image during the lean image build, so
// it relies on nothing but Node itself.
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const [src, dst, ...roots] = process.argv.slice(2);
if (!src || !dst || roots.length === 0) {
  console.error("usage: prune-node-modules.js <src> <dst> <package>...");
  process.exit(2);
}

const lockPath = path.join(src, ".package-lock.json");
if (!fs.existsSync(lockPath)) {
  console.error(`missing ${lockPath}; cannot compute the dependency closure`);
  process.exit(1);
}
const packages = JSON.parse(fs.readFileSync(lockPath, "utf8")).packages;
// Hidden lockfile keys are relative to the project root: "node_modules/a",
// "node_modules/a/node_modules/b". Normalise to that form.
const has = (key) => Object.prototype.hasOwnProperty.call(packages, key);

// Node resolution: look in the package's own node_modules, then walk up.
function resolve(fromKey, dep) {
  let base = fromKey;
  for (;;) {
    const key = (base ? base + "/" : "") + "node_modules/" + dep;
    if (has(key)) return key;
    if (!base) return null;
    const i = base.lastIndexOf("/node_modules/");
    base = i < 0 ? "" : base.slice(0, i);
  }
}

const keep = new Set();
const queue = [];
for (const root of roots) {
  const key = resolve("", root);
  if (!key) {
    console.error(`package not found in ${src}: ${root}`);
    process.exit(1);
  }
  queue.push(key);
}
while (queue.length) {
  const key = queue.pop();
  if (keep.has(key)) continue;
  keep.add(key);
  const meta = packages[key];
  const deps = {
    ...meta.peerDependencies,
    ...meta.optionalDependencies,
    ...meta.dependencies,
  };
  for (const dep of Object.keys(deps)) {
    const next = resolve(key, dep);
    if (next && !keep.has(next)) queue.push(next);
  }
}

fs.rmSync(dst, { recursive: true, force: true });
fs.mkdirSync(dst, { recursive: true });
for (const key of keep) {
  const rel = key.slice("node_modules/".length); // a, a/node_modules/b, @s/n
  const from = path.join(src, rel);
  if (!fs.existsSync(from)) continue; // optional package not installed on this platform
  fs.cpSync(from, path.join(dst, rel), {
    recursive: true,
    verbatimSymlinks: true,
    // Nested node_modules are copied as their own kept keys.
    filter: (p) => !path.relative(from, p).split(path.sep).includes("node_modules"),
  });
}

// Keep the .bin shims whose targets survived.
const binSrc = path.join(src, ".bin");
if (fs.existsSync(binSrc)) {
  const binDst = path.join(dst, ".bin");
  fs.cpSync(binSrc, binDst, { recursive: true, verbatimSymlinks: true });
  for (const name of fs.readdirSync(binDst)) {
    const p = path.join(binDst, name);
    if (!fs.existsSync(p)) fs.rmSync(p, { force: true }); // dangling symlink
  }
}
console.log(`kept ${keep.size} of ${Object.keys(packages).length} packages`);
