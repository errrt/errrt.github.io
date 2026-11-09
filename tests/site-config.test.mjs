import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { runInNewContext } from "node:vm";

const source = await readFile("dist/site-config.js", "utf8");
const destinations = {
  phraseCrate: "https://chromewebstore.google.com/detail/phrasecrate/gngjinfejkkiflogppaadaandlenomcd",
  tabParcel: "https://chromewebstore.google.com/detail/tab-parcel/pohjmphoidcblbneaeabbpjhcjjlbhke",
  tinyExpander: "https://apps.apple.com/us/app/tiny-expander/id6821790240",
  github: "https://github.com/errrt",
  x: "https://x.com/errrt0dev",
};

test("LP links use the tracked routes for every configured destination", async () => {
  const html = await readFile("index.html", "utf8");
  const links = [...html.matchAll(/data-link="([^"]+)"/g)].map((match) => ({
    dataset: { link: match[1] },
    removeAttribute() { assert.fail("Configured link was disabled"); },
  }));
  const year = {};
  runInNewContext(source, { document: {
    body: { dataset: {} },
    querySelectorAll: () => links,
    querySelector: () => year,
  } });
  assert.deepEqual([...new Set(links.map((link) => link.dataset.link))].sort(), Object.keys(destinations).sort());
  for (const link of links) {
    assert.equal(link.href, `/go/${link.dataset.link}/index.html`);
    assert.equal(link.target, "_blank");
  }
});

for (const [key, target] of Object.entries(destinations)) {
  test(`${key} redirect retains analytics, fallback, and the correct destination`, async () => {
    const html = await readFile(`go/${key}/index.html`, "utf8");
    const lp = await readFile("index.html", "utf8");
    assert.ok(html.includes(`data-redirect="${key}"`));
    assert.ok(html.includes('src="../../dist/site-config.js" defer'));
    assert.ok(html.includes(`data-redirect-target href="${target}"`));
    assert.ok(html.includes('name="robots" content="noindex"'));
    assert.ok(html.includes("https://static.cloudflareinsights.com/beacon.min.js"));
    assert.equal(html.match(/data-cf-beacon='([^']+)'/)[1], lp.match(/data-cf-beacon='([^']+)'/)[1]);
    const fallback = {};
    let onLoad;
    let redirect;
    runInNewContext(source, {
      document: { body: { dataset: { redirect: key } }, querySelector: () => fallback },
      window: {
        addEventListener(event, callback) { assert.equal(event, "load"); onLoad = callback; },
        setTimeout(callback, delay) { assert.equal(delay, 500); callback(); },
        location: { replace(url) { redirect = url; } },
      },
    });
    assert.equal(fallback.href, target);
    assert.equal(redirect, undefined);
    onLoad();
    assert.equal(redirect, target);
  });
}
