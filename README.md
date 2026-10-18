# errrt

The official home of errrt — tiny software for everyday annoyances.

This is a dependency-free static site made for GitHub Pages. GitHub publishes the repository root from `main`.

## File structure

```text
index.html          # Page and SEO metadata
.nojekyll           # Disables Jekyll processing on GitHub Pages
dist/
├── favicon.svg
├── og-image.png
├── og-image.svg
├── site-config.js  # Product and social URLs
└── styles.css
scripts/
├── build.mjs       # Lightweight validation
└── dev.mjs         # Local static server
```

## Local development

No dependency installation or compilation is required.

```sh
npm run dev
```

Open `http://localhost:4173`. Run the same validation used in CI with:

```sh
npm run build
```

## Update links

All product, X, and GitHub URLs live in `dist/site-config.js`. Replace the empty strings in `SITE_LINKS`; no HTML editing is needed. Empty URLs are displayed as unavailable links.

## Deploy to GitHub Pages

1. Push this project to the `main` branch of `errrt/errrt.github.io`.
2. Open the repository's **Settings → Pages**.
3. Under **Build and deployment**, select **Deploy from a branch**.
4. Select the `main` branch and `/ (root)`, then save.

The site is published automatically after every push to `main`. No build action or generated branch is needed.

## Custom domain

1. Open **Settings → Pages → Custom domain** and enter the domain.
2. Configure the required DNS record with your DNS provider.
   - For a subdomain such as `www.example.com`, create a `CNAME` pointing to `<user-or-org>.github.io` without a repository path.
   - For an apex domain such as `example.com`, use the current `A`, `AAAA`, `ALIAS`, or `ANAME` values from GitHub's documentation.
3. After DNS is active, enable **Enforce HTTPS** in the Pages settings.
4. Update the canonical URL, `og:url`, and Open Graph image URLs in `index.html` to the custom domain.

GitHub creates a `CNAME` file when a custom domain is saved for a branch-published site. Pull that commit before making later changes.

- [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
- [GitHub Pages custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site)
