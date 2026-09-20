import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const packageRoot = dirname(require.resolve("swagger-ui-dist/package.json"));
const { version } = JSON.parse(await readFile(resolve(packageRoot, "package.json")));
const destination = resolve(root, "static/swagger");
const check = process.argv.includes("--check");
const manifest = {
  package: "swagger-ui-dist",
  version,
  source: `https://registry.npmjs.org/swagger-ui-dist/-/swagger-ui-dist-${version}.tgz`,
  files: {},
};
await mkdir(destination, { recursive: true });
for (const name of ["swagger-ui-bundle.js", "swagger-ui.css", "LICENSE"]) {
  const bytes = await readFile(resolve(packageRoot, name));
  manifest.files[name] = {
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
  if (check) {
    const existing = await readFile(resolve(destination, name));
    if (!existing.equals(bytes)) throw new Error(`Swagger asset differs: ${name}`);
  } else {
    await writeFile(resolve(destination, name), bytes);
  }
}
const manifestPath = resolve(destination, "manifest.json");
if (check) {
  const existing = JSON.parse(await readFile(manifestPath));
  if (JSON.stringify(existing) !== JSON.stringify(manifest)) {
    throw new Error("Swagger manifest differs; run scripts/pnpm.sh sync:swagger");
  }
} else {
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
}
console.log(`Swagger ${version}: ${check ? "verified" : "synchronized"}`);
