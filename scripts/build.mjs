import { access, readFile } from "node:fs/promises";

const requiredFiles = [
  "dist/index.html",
  "dist/styles.css",
  "dist/site-config.js",
  "dist/favicon.svg",
  "dist/og-image.svg",
  "dist/og-image.png",
  "dist/.nojekyll",
];

await Promise.all(requiredFiles.map((file) => access(file)));

const html = await readFile("dist/index.html", "utf8");
const requiredCopy = [
  "errrt",
  "Tiny software for everyday annoyances.",
  "PhraseCrate",
  "Tab Parcel",
  "Tiny Expander",
];

for (const copy of requiredCopy) {
  if (!html.includes(copy)) {
    throw new Error(`Missing required copy: ${copy}`);
  }
}

const rootRelativeAssets = html.match(/(?:href|src|content)="\/(?!\/)/g);

if (rootRelativeAssets) {
  throw new Error("Root-relative asset paths break on GitHub Pages project sites.");
}

console.log("Static site checks passed.");
