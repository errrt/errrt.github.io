import { access, readFile } from "node:fs/promises";

const requiredFiles = [
  "index.html",
  "dist/styles.css",
  "dist/site-config.js",
  "dist/favicon.svg",
  "dist/og-image.svg",
  "dist/og-image.png",
  ".nojekyll",
];

await Promise.all(requiredFiles.map((file) => access(file)));

const html = await readFile("index.html", "utf8");
const requiredCopy = [
  "errrt",
  "Tiny software for everyday annoyances.",
  "PhraseCrate",
  "Tab Parcel",
  "Tiny Expander",
  "https://static.cloudflareinsights.com/beacon.min.js",
  "657f2e4fac22497e950b574f04ad4208",
];

for (const copy of requiredCopy) {
  if (!html.includes(copy)) {
    throw new Error(`Missing required copy: ${copy}`);
  }
}

console.log("Static site checks passed.");
