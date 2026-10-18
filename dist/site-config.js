/**
 * Replace these URLs when product pages and social profiles are ready.
 * Links left empty are shown as unavailable and cannot be clicked.
 */
const SITE_LINKS = {
  phraseCrate: "https://chromewebstore.google.com/detail/phrasecrate/gngjinfejkkiflogppaadaandlenomcd?authuser=0&hl=ja",
  tabParcel: "https://chromewebstore.google.com/detail/tab-parcel/pohjmphoidcblbneaeabbpjhcjjlbhke?authuser=0&hl=ja",
  tinyExpander: "",
  x: "",
  github: "",
};

document.querySelectorAll("[data-link]").forEach((link) => {
  const url = SITE_LINKS[link.dataset.link];

  if (url) {
    link.href = url;
    link.target = "_blank";
    return;
  }

  link.removeAttribute("href");
  link.setAttribute("aria-disabled", "true");
  link.title = "Coming soon";
});

document.querySelector("#year").textContent = new Date().getFullYear();
