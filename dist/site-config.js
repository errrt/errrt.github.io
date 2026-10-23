const LINK_TARGETS = {
  phraseCrate: "https://chromewebstore.google.com/detail/phrasecrate/gngjinfejkkiflogppaadaandlenomcd",
  tabParcel: "https://chromewebstore.google.com/detail/tab-parcel/pohjmphoidcblbneaeabbpjhcjjlbhke",
  tinyExpander: "",
  x: "",
  github: "https://github.com/errrt",
};

const TRACKED_LINKS = new Set(["phraseCrate", "tabParcel", "github", "x"]);
const redirectKey = document.body.dataset.redirect;

if (redirectKey) {
  const target = LINK_TARGETS[redirectKey];
  const fallback = document.querySelector("[data-redirect-target]");

  if (target) {
    fallback.href = target;
    window.addEventListener("load", () => {
      window.setTimeout(() => window.location.replace(target), 500);
    });
  } else {
    document.querySelector("[data-redirect-message]").textContent = "This destination is not configured yet.";
    fallback.removeAttribute("href");
  }
} else {
  document.querySelectorAll("[data-link]").forEach((link) => {
    const key = link.dataset.link;
    const target = LINK_TARGETS[key];

    if (target) {
      link.href = TRACKED_LINKS.has(key) ? `/go/${key}/index.html` : target;
      link.target = "_blank";
      return;
    }

    link.removeAttribute("href");
    link.setAttribute("aria-disabled", "true");
    link.title = "Coming soon";
  });

  document.querySelector("#year").textContent = new Date().getFullYear();
}
