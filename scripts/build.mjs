import { access, readFile } from "node:fs/promises";

const requiredFiles = [
  "index.html",
  "dist/styles.css",
  "dist/site-config.js",
  "dist/favicon.svg",
  "dist/og-image.svg",
  "dist/og-image.png",
  "go/phraseCrate/index.html",
  "go/tabParcel/index.html",
  "go/github/index.html",
  ".nojekyll",
];

await Promise.all(requiredFiles.map((file) => access(file)));

const html = await readFile("index.html", "utf8");
const siteConfig = await readFile("dist/site-config.js", "utf8");
const requiredCopy = [
  "errrt",
  "Tiny software for everyday annoyances.",
  "PhraseCrate",
  "Tab Parcel",
  "Tiny Expander",
  "https://static.cloudflareinsights.com/beacon.min.js",
  "1709ef2ee75e4ed88b82a65361e0588a",
];

for (const copy of requiredCopy) {
  if (!html.includes(copy)) {
    throw new Error(`Missing required copy: ${copy}`);
  }
}

const requiredLinks = [
  "https://github.com/errrt",
  "https://chromewebstore.google.com/detail/phrasecrate/gngjinfejkkiflogppaadaandlenomcd",
  "https://chromewebstore.google.com/detail/tab-parcel/pohjmphoidcblbneaeabbpjhcjjlbhke",
  "`/go/${key}/index.html`",
];

for (const link of requiredLinks) {
  if (!siteConfig.includes(link)) {
    throw new Error(`Missing required link: ${link}`);
  }
}

console.log("Static site checks passed.");
