import assert from "node:assert/strict";
import { readFile, access } from "node:fs/promises";
import test from "node:test";

const pages = ["index.html", "phrasecrate/index.html"];
const canonicalUrls = ["https://errrt.github.io/", "https://errrt.github.io/phrasecrate/"];
const home = await readFile(pages[0], "utf8");
const product = await readFile(pages[1], "utf8");
const beacon = home.match(/data-cf-beacon='([^']+)'/)[1];

for (const [index, file] of pages.entries()) {
  test(`${file} exposes discoverable content and links without JavaScript`, async () => {
    const html = await readFile(file, "utf8");
    assert.equal((html.match(/<h1\b/g) ?? []).length, 1);
    assert.ok(html.includes(`<link rel="canonical" href="${canonicalUrls[index]}"`));
    assert.ok(html.includes(`<meta property="og:url" content="${canonicalUrls[index]}"`));
    assert.ok(html.includes('name="description" content=' ) || html.includes('name="description"\n'));
    assert.ok(!/name="robots" content="[^"]*noindex/.test(html));
    assert.ok(!/href="#"/.test(html));
    for (const [, key, href] of html.matchAll(/data-link="([^"]+)" href="([^"]+)"/g)) {
      assert.equal(href, `/go/${key}/index.html`);
    }
    for (const [, fragment] of html.matchAll(/href="#([^"]+)"/g)) {
      assert.ok(html.includes(`id="${fragment}"`), `Missing anchor ${fragment}`);
    }
    for (const [, url] of html.matchAll(/(?:href|src)="(\/(?!\/)[^"#]+)"/g)) {
      const path = url.split("#")[0];
      await access(path === "/" ? "index.html" : path.endsWith("/") ? `${path.slice(1)}index.html` : path.slice(1));
    }
    assert.equal(html.match(/data-cf-beacon='([^']+)'/)[1], beacon);
    assert.ok(html.includes("https://static.cloudflareinsights.com/beacon.min.js"));
  });
}

test("homepage retains all products and links to the product page", () => {
  for (const name of ["PhraseCrate", "Tab Parcel", "Tiny Expander"]) assert.ok(home.includes(`<h3>${name}</h3>`));
  assert.ok(home.includes('href="/phrasecrate/"'));
  assert.ok(home.includes('data-link="tabParcel" href="/go/tabParcel/index.html"'));
  assert.ok(home.includes('data-link="tinyExpander" href="/go/tinyExpander/index.html"'));
});

test("product page preserves plan and privacy boundaries with an accessible FAQ", () => {
  assert.ok(product.includes("up to 15 phrases"));
  assert.ok(product.includes("$19") && product.includes("one-time purchase"));
  assert.ok(product.includes("up to three devices"));
  assert.ok(product.includes("before typing a search"));
  assert.ok(product.includes("Pro activation and license verification communicate with Polar"));
  assert.ok(product.includes("There is no cloud sync"));
  assert.ok(product.includes('href="https://phrasecrate-privacy.kxz.chatgpt.site"'));
  assert.ok((product.match(/<details>/g) ?? []).length >= 4);
  assert.ok(product.includes('width="1280" height="800" loading="lazy"'));
});

test("robots and sitemap expose only indexable canonical pages", async () => {
  const robots = await readFile("robots.txt", "utf8");
  const sitemap = await readFile("sitemap.xml", "utf8");
  assert.ok(robots.includes("Allow: /"));
  assert.ok(!robots.includes("Disallow:"));
  assert.ok(robots.includes("Sitemap: https://errrt.github.io/sitemap.xml"));
  assert.deepEqual([...sitemap.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) => match[1]), canonicalUrls);
  assert.ok(!sitemap.includes("/go/"));
});
